from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, Depends, Form, Query
from fastapi.responses import Response, JSONResponse
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
import json
import base64
import traceback
import asyncio
from twilio.twiml.voice_response import VoiceResponse, Connect

from app.config.database import SessionLocal
from app.config.voice_config import voice_config
from app.services.voice_agent_service import VoiceAgentService
from app.services.redis_service import redis_service
from app.models.call_session import CallSession

# Import new services
from app.services.stream_service import StreamService
from app.services.tts_service import TTSService
from app.services.deepgram_service import DeepgramManager

router = APIRouter(prefix="/voice", tags=["Voice Agent"])

# Global context storage
call_context: Dict[str, Dict[str, Any]] = {}


async def handle_full_transcript(
    call_sid: str,
    transcript: str,
    stream_service: StreamService,
    tts_service: TTSService
):
    """
    Callback triggered by Deepgram upon detecting end of user speech.
    """
    print(f"=" * 80)
    print(f"💬 Full transcript received: '{transcript}'")
    
    context = call_context.get(call_sid)
    if not context or not transcript:
        print("No context or empty transcript, skipping")
        return
    
    agent = context.get("agent")
    if not agent:
        print("No agent in context")
        return
    
    try:
        # Get AI response
        print(f"🤖 Processing with AI...")
        ai_result = await agent.process_user_speech(call_sid, transcript)
        response_text = ai_result.get("response")
        
        if not response_text:
            print("No response from AI")
            return
        
        print(f"🎯 AI Response: '{response_text}'")
        
        # Generate and stream audio
        print(f"🎤 Generating TTS audio...")
        audio_index = 0
        
        async for audio_b64 in tts_service.generate(response_text):
            if audio_b64:
                # Buffer audio with index for ordered playback
                await stream_service.buffer(audio_index, audio_b64)
                audio_index += 1
        
        print(f"✓ Finished streaming AI response ({audio_index} chunks)")
        print("=" * 80)
        
    except Exception as e:
        print(f"✗ Error in transcript handler: {e}")
        traceback.print_exc()


@router.post("/incoming")
async def handle_incoming_call(
    request: Request,
    CallSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    db: Session = Depends(get_db)
):
    """Handle incoming Twilio call"""
    try:
        print(f"\n{'=' * 80}")
        print(f"📞 Incoming call: {CallSid} from {From}")
        
        response = VoiceResponse()
        
        if not voice_config.VOICE_AGENT_ENABLED:
            response.say("Assistant unavailable.", voice="Polly.Amy", language="en-GB")
            response.hangup()
            return Response(content=str(response), media_type="application/xml")
        
        # Build WebSocket URL
        websocket_url = f"wss://{request.url.hostname}/api/v1/voice/stream?call_sid={CallSid}"
        print(f"🔌 WebSocket URL: {websocket_url}")
        
        # Connect to WebSocket stream
        connect = Connect()
        connect.stream(url=websocket_url)
        response.append(connect)
        
        # Keep call alive
        response.pause(length=60)
        
        print(f"✓ TwiML response generated")
        print("=" * 80)
        
        return Response(content=str(response), media_type="application/xml")
        
    except Exception as e:
        print(f"✗ Error handling incoming call: {e}")
        traceback.print_exc()
        
        twiml = VoiceResponse()
        twiml.say("An error occurred.", voice="Polly.Amy", language="en-GB")
        twiml.hangup()
        return Response(content=str(twiml), media_type="application/xml")


@router.websocket("/stream")
async def websocket_stream(
    websocket: WebSocket,
    call_sid: Optional[str] = Query(None)
):
    """
    Handle Twilio Media Stream WebSocket connection.
    Based on TypeScript implementation with proper service integration.
    """
    # Step 1: Accept WebSocket FIRST
    try:
        await websocket.accept()
        print(f"\n{'=' * 80}")
        print(f"✓ WebSocket accepted")
    except Exception as e:
        print(f"✗ Failed to accept WebSocket: {e}")
        return
    
    # Step 2: Validate call_sid
    if not call_sid:
        await websocket.send_json({"error": "Missing call_sid parameter"})
        await websocket.close(code=1008)
        return
    
    print(f"📞 Call SID: {call_sid}")
    
    # Step 3: Initialize services
    db = SessionLocal()
    stream_service = StreamService(websocket)
    tts_service = TTSService()
    deepgram_manager = DeepgramManager()
    
    agent = None
    deepgram_service = None
    
    try:
        # Initialize Voice Agent
        print("🤖 Initializing Voice Agent...")
        agent = VoiceAgentService(db)
        await agent.initiate_call(call_sid, "WebSocket", "WebSocket")
        print("✓ Voice Agent initialized")
        
        # Initialize Deepgram STT
        print("🎤 Initializing Deepgram STT...")
        try:
            deepgram_service = deepgram_manager.create_connection(
                call_sid=call_sid,
                on_speech_end_callback=lambda transcript: asyncio.create_task(
                    handle_full_transcript(call_sid, transcript, stream_service, tts_service)
                )
            )
            
            if deepgram_service:
                connected = await deepgram_service.connect()
                if connected:
                    print("✓ Deepgram connected")
                else:
                    print("✗ Deepgram connection failed")
                    deepgram_service = None
        except Exception as e:
            print(f"✗ Deepgram error: {e}")
            traceback.print_exc()
            deepgram_service = None
        
        # Store context
        call_context[call_sid] = {
            "websocket": websocket,
            "agent": agent,
            "deepgram": deepgram_service,
            "stream_service": stream_service,
            "tts_service": tts_service
        }
        
        print("✓ Context stored")
        print("🔄 Entering message loop...")
        print("=" * 80)
        
        has_sent_greeting = False
        message_count = 0
        
        # Main message loop
        while True:
            try:
                message = await websocket.receive_text()
                message_count += 1
                
                data = json.loads(message)
                event = data.get("event")
                
                # Log every 100th message
                if message_count % 100 == 0:
                    print(f"📊 Processed {message_count} messages")
                
                if event == "start":
                    stream_sid = data.get("streamSid")
                    stream_service.set_stream_sid(stream_sid)
                    
                    print(f"\n🚀 Stream started: {stream_sid}")
                    
                    # Update Redis
                    redis_service.update_session(call_sid, {"stream_sid": stream_sid})
                    
                    # Send greeting
                    if not has_sent_greeting:
                        greeting_text = f"Thank you for calling {voice_config.CLINIC_NAME}! How can I help you today?"
                        print(f"💬 Sending greeting...")
                        
                        try:
                            async for audio_b64 in tts_service.generate(greeting_text):
                                if audio_b64:
                                    # Send with index None for immediate playback
                                    await stream_service.buffer(None, audio_b64)
                            
                            print("✓ Greeting sent")
                            has_sent_greeting = True
                        except Exception as e:
                            print(f"✗ Error sending greeting: {e}")
                
                elif event == "media":
                    # Forward audio to Deepgram
                    if deepgram_service:
                        payload = data.get("media", {}).get("payload")
                        if payload:
                            audio_chunk = base64.b64decode(payload)
                            await deepgram_service.send_audio(audio_chunk)
                
                elif event == "mark":
                    mark_name = data.get("mark", {}).get("name")
                    if message_count % 10 == 0:
                        print(f"✓ Mark received: {mark_name}")
                
                elif event == "stop":
                    print("\n🛑 Stop event received")
                    break
                    
            except WebSocketDisconnect:
                print("\n✓ Client disconnected")
                break
            except json.JSONDecodeError as e:
                print(f"✗ JSON decode error: {e}")
                continue
            except Exception as e:
                print(f"✗ Error in message loop: {e}")
                traceback.print_exc()
                continue
    
    except Exception as e:
        print(f"\n✗ Fatal error: {e}")
        traceback.print_exc()
    
    finally:
        # Cleanup
        print(f"\n{'=' * 80}")
        print("🧹 Cleaning up...")
        
        if deepgram_service:
            try:
                await deepgram_manager.remove_connection(call_sid)
                print("✓ Deepgram cleaned up")
            except Exception as e:
                print(f"✗ Error cleaning Deepgram: {e}")
        
        call_context.pop(call_sid, None)
        print("✓ Context cleared")
        
        if agent:
            try:
                await agent.end_call(call_sid)
                print("✓ Call ended")
            except Exception as e:
                print(f"✗ Error ending call: {e}")
        
        if db:
            db.close()
            print("✓ Database closed")
        
        print(f"✓ Cleanup complete for {call_sid}")
        print("=" * 80)


@router.post("/status")
async def handle_call_status(
    request: Request,
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    db: Session = Depends(get_db)
):
    """Handle call status updates from Twilio"""
    try:
        print(f"📊 Call status: {CallSid} - {CallStatus}")
        
        db_session = db.query(CallSession).filter(
            CallSession.call_sid == CallSid
        ).first()
        
        if db_session:
            db_session.status = CallStatus
            db.commit()
        
        if CallStatus in ["completed", "failed", "busy", "no-answer"]:
            agent = VoiceAgentService(db)
            await agent.end_call(CallSid)
        
        return JSONResponse({"success": True})
        
    except Exception as e:
        print(f"✗ Error handling status: {e}")
        return JSONResponse({"success": False, "error": str(e)})
