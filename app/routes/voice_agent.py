from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, Form, Depends, Query, status
from fastapi.responses import Response, JSONResponse
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
import json
import base64
import traceback
import asyncio
import logging
from twilio.twiml.voice_response import VoiceResponse, Connect

# Database imports
from app.config.database import SessionLocal, get_db

# Config imports
from app.config.voice_config import voice_config

# Service imports
from app.services.voice_agent_service import VoiceAgentService
from app.services.redis_service import redis_service
from app.models.call_session import CallSession

# Import new services
from app.services.stream_service import StreamService
from app.services.tts_service import TTSService
from app.services.deepgram_service import DeepgramManager

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["Voice Agent"])

# Global context storage
call_context: Dict[str, Dict[str, Any]] = {}


async def handle_full_transcript(
    call_sid: str,
    transcript: str,
    stream_service: StreamService,
    tts_service: TTSService
):
    """Callback triggered by Deepgram upon detecting end of user speech."""
    logger.info("=" * 80)
    logger.info(f"💬 Full transcript: '{transcript}'")
    
    context = call_context.get(call_sid)
    if not context or not transcript:
        logger.info("No context or empty transcript")
        return
    
    agent = context.get("agent")
    if not agent:
        logger.info("No agent in context")
        return
    
    try:
        # Get AI response
        logger.info("🤖 Processing with AI...")
        ai_result = await agent.process_user_speech(call_sid, transcript)
        response_text = ai_result.get("response")
        
        if not response_text:
            logger.info("No response from AI")
            return
        
        logger.info(f"🎯 AI Response: '{response_text}'")
        
        # Generate and stream audio
        logger.info("🎤 Generating TTS audio...")
        audio_index = 0
        
        async for audio_b64 in tts_service.generate(response_text):
            if audio_b64:
                await stream_service.buffer(audio_index, audio_b64)
                audio_index += 1
        
        logger.info(f"✓ Finished streaming ({audio_index} chunks)")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"✗ Error in transcript handler: {e}")
        traceback.print_exc()


@router.post("/incoming")
async def handle_incoming_call(
    request: Request,
    CallSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...)
):
    """Handle incoming Twilio call"""
    try:
        logger.info("\n" + "=" * 80)
        logger.info(f"📞 Incoming call: {CallSid} from {From}")
        
        response = VoiceResponse()
        
        if not voice_config.VOICE_AGENT_ENABLED:
            response.say("Assistant unavailable.", voice="Polly.Amy", language="en-GB")
            response.hangup()
            return Response(content=str(response), media_type="application/xml")
        
        # Build WebSocket URL
        websocket_url = f"wss://{request.url.hostname}/api/v1/voice/stream?call_sid={CallSid}"
        logger.info(f"🔌 WebSocket URL: {websocket_url}")
        
        # Connect to WebSocket stream
        connect = Connect()
        connect.stream(url=websocket_url)
        response.append(connect)
        
        # Keep call alive
        response.pause(length=60)
        
        logger.info("✓ TwiML response generated")
        logger.info("=" * 80)
        
        return Response(content=str(response), media_type="application/xml")
        
    except Exception as e:
        logger.error(f"✗ Error handling incoming call: {e}")
        traceback.print_exc()
        
        twiml = VoiceResponse()
        twiml.say("An error occurred.", voice="Polly.Amy", language="en-GB")
        twiml.hangup()
        return Response(content=str(twiml), media_type="application/xml")


@router.websocket("/stream")
async def websocket_stream(websocket: WebSocket):
    """Handle Twilio Media Stream WebSocket connection"""
    
    # Accept first
    try:
        logger.info("\n" + "=" * 80)
        logger.info("1. Accepting WebSocket...")
        await websocket.accept()
        logger.info("✓ WebSocket accepted")
    except Exception as e:
        logger.error(f"✗ Failed to accept WebSocket: {e}")
        traceback.print_exc()
        return
    
    # Extract call_sid manually from query parameters
    call_sid = websocket.query_params.get("call_sid")
    
    logger.info(f"2. Query parameters: {dict(websocket.query_params)}")
    logger.info(f"   call_sid: {call_sid}")
    
    if not call_sid:
        logger.error("✗ Missing call_sid in query parameters")
        try:
            await websocket.send_json({
                "error": "Missing call_sid parameter",
                "help": "Add ?call_sid=YOUR_CALL_SID to the URL"
            })
            await websocket.close(code=1008)
        except:
            pass
        return
    
    logger.info(f"3. Call SID validated: {call_sid}")
    
    # Continue with rest of your code...
    db = None
    try:
        logger.info("4. Creating database session...")
        db = SessionLocal()
        logger.info("✓ Database session created")
    except Exception as e:
        logger.error(f"✗ Database session creation failed: {e}")
        traceback.print_exc()
        try:
            await websocket.send_json({"error": "Database error"})
            await websocket.close()
        except:
            pass
        return
    
    # Step 4: Initialize services
    stream_service = None
    tts_service = None
    deepgram_manager = None
    agent = None
    deepgram_service = None
    
    try:
        logger.info("4. Initializing StreamService...")
        stream_service = StreamService(websocket)
        logger.info("✓ StreamService initialized")
        
        logger.info("5. Initializing TTSService...")
        tts_service = TTSService()
        logger.info("✓ TTSService initialized")
        
        logger.info("6. Initializing DeepgramManager...")
        deepgram_manager = DeepgramManager()
        logger.info("✓ DeepgramManager initialized")
        
        # Initialize Voice Agent
        logger.info("7. Initializing VoiceAgentService...")
        agent = VoiceAgentService(db)
        await agent.initiate_call(call_sid, "WebSocket", "WebSocket")
        logger.info("✓ VoiceAgentService initialized")
        
        # Initialize Deepgram STT
        logger.info("8. Initializing Deepgram STT...")
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
                    logger.info("✓ Deepgram connected")
                else:
                    logger.warning("⚠ Deepgram connection failed")
                    deepgram_service = None
        except Exception as e:
            logger.error(f"✗ Deepgram initialization error: {e}")
            traceback.print_exc()
            deepgram_service = None
        
        # Store context
        logger.info("9. Storing context...")
        call_context[call_sid] = {
            "websocket": websocket,
            "agent": agent,
            "deepgram": deepgram_service,
            "stream_service": stream_service,
            "tts_service": tts_service
        }
        logger.info("✓ Context stored")
        
        logger.info("10. Entering message loop...")
        logger.info("=" * 80)
        
        has_sent_greeting = False
        message_count = 0
        
        # Main message loop - THIS KEEPS THE CONNECTION ALIVE
        while True:
            try:
                message = await websocket.receive_text()
                message_count += 1
                
                data = json.loads(message)
                event = data.get("event")
                
                # Log every 100th message
                if message_count % 100 == 0:
                    logger.info(f"📊 Processed {message_count} messages")
                
                if event == "start":
                    stream_sid = data.get("streamSid")
                    stream_service.set_stream_sid(stream_sid)
                    
                    logger.info(f"\n🚀 Stream started: {stream_sid}")
                    
                    # Update Redis
                    redis_service.update_session(call_sid, {"stream_sid": stream_sid})
                    
                    # Send greeting
                    if not has_sent_greeting:
                        greeting_text = f"Thank you for calling {voice_config.CLINIC_NAME}! How can I help you today?"
                        logger.info(f"💬 Sending greeting: '{greeting_text}'")
                        
                        try:
                            async for audio_b64 in tts_service.generate(greeting_text):
                                if audio_b64:
                                    await stream_service.buffer(None, audio_b64)
                            
                            logger.info("✓ Greeting sent")
                            has_sent_greeting = True
                        except Exception as e:
                            logger.error(f"✗ Error sending greeting: {e}")
                            traceback.print_exc()
                
                elif event == "media":
                    # Forward audio to Deepgram
                    if deepgram_service:
                        payload = data.get("media", {}).get("payload")
                        if payload:
                            try:
                                audio_chunk = base64.b64decode(payload)
                                await deepgram_service.send_audio(audio_chunk)
                            except Exception as e:
                                if message_count % 100 == 0:
                                    logger.error(f"✗ Deepgram error: {e}")
                
                elif event == "mark":
                    mark_name = data.get("mark", {}).get("name")
                    if message_count % 50 == 0:
                        logger.info(f"✓ Mark: {mark_name}")
                
                elif event == "stop":
                    logger.info("\n🛑 Stop event received")
                    break
                else:
                    logger.info(f"⚠ Unknown event: {event}")
                    
            except WebSocketDisconnect:
                logger.info("\n✓ Client disconnected")
                break
            except json.JSONDecodeError as e:
                logger.error(f"✗ JSON decode error: {e}")
                continue
            except Exception as e:
                logger.error(f"✗ Error in message loop: {e}")
                traceback.print_exc()
                continue
    
    except Exception as e:
        logger.error(f"\n✗ FATAL ERROR: {e}")
        traceback.print_exc()
    
    finally:
        # Cleanup
        logger.info(f"\n{'=' * 80}")
        logger.info("🧹 Starting cleanup...")
        
        if deepgram_service and deepgram_manager:
            try:
                await deepgram_manager.remove_connection(call_sid)
                logger.info("✓ Deepgram cleaned up")
            except Exception as e:
                logger.error(f"✗ Deepgram cleanup error: {e}")
        
        call_context.pop(call_sid, None)
        logger.info("✓ Context cleared")
        
        if agent:
            try:
                await agent.end_call(call_sid)
                logger.info("✓ Call ended")
            except Exception as e:
                logger.error(f"✗ Call end error: {e}")
        
        if db:
            try:
                db.close()
                logger.info("✓ Database closed")
            except Exception as e:
                logger.error(f"✗ Database close error: {e}")
        
        try:
            if websocket.client_state.value == 1:  # CONNECTED state
                await websocket.close()
                logger.info("✓ WebSocket closed")
        except Exception as e:
            logger.error(f"✗ WebSocket close error: {e}")
        
        logger.info(f"✓ Cleanup complete for {call_sid}")
        logger.info("=" * 80)


@router.post("/status")
async def handle_call_status(
    request: Request,
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    db: Session = Depends(get_db)
):
    """Handle call status updates from Twilio"""
    try:
        logger.info(f"📊 Call status: {CallSid} - {CallStatus}")
        
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
        logger.error(f"✗ Error handling status: {e}")
        return JSONResponse({"success": False, "error": str(e)})
