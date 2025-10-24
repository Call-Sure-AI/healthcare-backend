from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, Form, Query, Depends
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
from app.services.elevenlabs_service import elevenlabs_service
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
    tts_service: any  # Works with both ElevenLabs and Deepgram
):
    """
    Callback triggered by Deepgram when user finishes speaking.
    Combines ALL audio chunks before sending to prevent dropouts.
    """
    logger.info("=" * 80)
    logger.info(f"💬 TRANSCRIPT RECEIVED")
    logger.info(f"   Call SID: {call_sid}")
    logger.info(f"   User said: '{transcript}'")
    logger.info(f"   Length: {len(transcript)} chars")
    
    context = call_context.get(call_sid)
    if not context:
        logger.error("   ❌ No context found")
        return
    
    if not transcript or not transcript.strip():
        logger.warning("   ⚠ Empty transcript")
        return
    
    agent: VoiceAgentService = context.get("agent")
    if not agent:
        logger.error("   ❌ No agent in context")
        return
    
    try:
        import time
        import base64
        
        # ========== STEP 1: Get AI Response ==========
        ai_start = time.time()
        logger.info("🤖 Calling VoiceAgentService.process_user_speech()...")
        
        ai_result = await agent.process_user_speech(call_sid, transcript)
        
        logger.info(f"   ✓ AI Processing: {time.time() - ai_start:.2f}s")
        logger.info(f"   Success: {ai_result.get('success', False)}")
        
        response_text = ai_result.get("response")
        if not response_text:
            logger.warning("   ⚠ No response, using fallback")
            response_text = "I'm sorry, could you please repeat that?"
        
        logger.info(f"🎯 AI Response: '{response_text[:80]}...'")
        
        # ========== STEP 2: Generate TTS Audio ==========
        logger.info("🎤 Generating TTS audio...")
        tts_start = time.time()
        
        # Clear Twilio buffer first
        await stream_service.clear()
        
        # ============ CRITICAL: Collect ALL chunks first ============
        audio_chunks = []
        chunk_count = 0
        
        async for audio_b64 in tts_service.generate(response_text):
            if audio_b64:
                audio_chunks.append(audio_b64)
                chunk_count += 1
        
        if not audio_chunks:
            logger.error("   ❌ No audio generated!")
            return
        
        logger.info(f"   ✓ Generated {chunk_count} chunks from TTS")
        
        # ============ CRITICAL: Combine ALL chunks into ONE ============
        combined_audio_bytes = b''
        for chunk_b64 in audio_chunks:
            chunk_bytes = base64.b64decode(chunk_b64)
            combined_audio_bytes += chunk_bytes
        
        total_size = len(combined_audio_bytes)
        logger.info(f"   ✓ Combined into single buffer: {total_size} bytes")
        
        # Re-encode as single base64 string
        final_audio_b64 = base64.b64encode(combined_audio_bytes).decode('ascii')
        
        # ========== STEP 3: Send as ONE chunk ==========
        # stream_service._send_audio will split into proper 160-byte frames internally
        await stream_service._send_audio(final_audio_b64)
        
        tts_duration = time.time() - tts_start
        logger.info(f"✓ Audio complete: {tts_duration:.2f}s ({total_size} bytes)")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        
        # Send error message (also combined)
        try:
            error_msg = "I apologize, I'm having trouble. Could you try again?"
            logger.info("🔧 Sending error message...")
            
            error_chunks = []
            async for audio_b64 in tts_service.generate(error_msg):
                if audio_b64:
                    error_chunks.append(audio_b64)
            
            if error_chunks:
                combined = b''.join([base64.b64decode(c) for c in error_chunks])
                final = base64.b64encode(combined).decode('ascii')
                await stream_service._send_audio(final)
                logger.info("✓ Error message sent")
                
        except Exception as err:
            logger.error(f"✗ Failed to send error: {err}")

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
    """
    Handle Twilio Media Stream WebSocket connection.
    Integrates: Deepgram STT -> VoiceAgentService -> AI Tools -> TTS -> Twilio
    """
    
    # Step 1: Accept WebSocket
    try:
        logger.info("\n" + "=" * 80)
        logger.info("1. Accepting WebSocket...")
        await websocket.accept()
        logger.info("✓ WebSocket accepted")
    except Exception as e:
        logger.error(f"✗ Failed to accept WebSocket: {e}")
        traceback.print_exc()
        return
    
    # Step 2: Get call_sid from query params or wait for start event
    call_sid = websocket.query_params.get("call_sid")
    logger.info(f"2. Query parameters: {dict(websocket.query_params)}")
    
    first_message_data = None
    if not call_sid:
        logger.warning("⚠ No call_sid in query params, waiting for Twilio events...")
        
        try:
            # Wait for 'connected' and 'start' events
            max_attempts = 3
            for attempt in range(max_attempts):
                message = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=10.0
                )
                data = json.loads(message)
                event_type = data.get("event")
                
                logger.info(f"   Received event #{attempt + 1}: {event_type}")
                
                if event_type == "connected":
                    logger.info("   ✓ Received 'connected' event")
                    continue
                    
                elif event_type == "start":
                    call_sid = data.get("start", {}).get("callSid")
                    first_message_data = data
                    logger.info(f"✓ Extracted call_sid: {call_sid}")
                    break
                    
        except asyncio.TimeoutError:
            logger.error("✗ Timeout waiting for start event")
            await websocket.close(code=1008)
            return
        except Exception as e:
            logger.error(f"✗ Error receiving messages: {e}")
            await websocket.close(code=1011)
            return
    
    if not call_sid:
        logger.error("✗ Could not obtain call_sid")
        await websocket.close(code=1008)
        return
    
    logger.info(f"3. Call SID validated: {call_sid}")
    
    # Step 3: Initialize database
    db = None
    try:
        logger.info("4. Creating database session...")
        db = SessionLocal()
        logger.info("✓ Database session created")
    except Exception as e:
        logger.error(f"✗ Database creation failed: {e}")
        await websocket.close()
        return
    
    # Step 4: Initialize services
    stream_service = None
    tts_service = None
    deepgram_manager = None
    agent = None
    deepgram_service = None
    
    try:
        logger.info("5. Initializing StreamService...")
        stream_service = StreamService(websocket)
        logger.info("✓ StreamService initialized")
        
        logger.info("6. Initializing Elevenlabs TTSService...")
        tts_service = elevenlabs_service
        logger.info("✓ Elevenlabs initialized")
        
        logger.info("7. Initializing DeepgramManager...")
        deepgram_manager = DeepgramManager()
        logger.info("✓ DeepgramManager initialized")
        
        # ========== INITIALIZE VOICE AGENT SERVICE ==========
        logger.info("8. Initializing VoiceAgentService...")
        agent = VoiceAgentService(db)
        await agent.initiate_call(call_sid, "WebSocket", "WebSocket")
        logger.info("✓ VoiceAgentService initialized (AI Tools ready!)")
        
        # ========== INITIALIZE DEEPGRAM STT ==========
        logger.info("9. Initializing Deepgram STT...")
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
                    logger.info("✓ Deepgram connected (STT ready!)")
                else:
                    logger.warning("⚠ Deepgram connection failed")
                    deepgram_service = None
        except Exception as e:
            logger.error(f"✗ Deepgram error: {e}")
            traceback.print_exc()
            deepgram_service = None
        
        # Store context
        logger.info("10. Storing context...")
        call_context[call_sid] = {
            "websocket": websocket,
            "agent": agent,
            "deepgram": deepgram_service,
            "stream_service": stream_service,
            "tts_service": tts_service
        }
        logger.info("✓ Context stored")
        
        logger.info("11. Entering message loop...")
        logger.info("=" * 80)
        
        has_sent_greeting = False
        message_count = 0
        
        # Process buffered start event if we have it
        if first_message_data and first_message_data.get("event") == "start":
            logger.info("📦 Processing buffered start event...")
            stream_sid = first_message_data.get("streamSid")
            stream_service.set_stream_sid(stream_sid)
            
            logger.info(f"🚀 Stream started: {stream_sid}")
            
            # Update Redis
            try:
                redis_service.update_session(call_sid, {"stream_sid": stream_sid})
            except Exception as e:
                logger.error(f"Redis error: {e}")
            
            await stream_service.clear()
            # Send greeting
            greeting_text = f"Thank you for calling {voice_config.CLINIC_NAME}! How can I help you today?"
            logger.info(f"💬 Sending greeting...")
            
            try:
                greeting_chunks = []
                async for audio_b64 in tts_service.generate(greeting_text):
                    if audio_b64:
                        greeting_chunks.append(audio_b64)

                if greeting_chunks:
                    # Combine all chunks into one
                    combined_greeting = b''.join([base64.b64decode(c) for c in greeting_chunks])
                    final_greeting_b64 = base64.b64encode(combined_greeting).decode('ascii')
                                
                    # Send as single chunk
                    await stream_service._send_audio(final_greeting_b64)

                    logger.info("✓ Greeting sent")
                    has_sent_greeting = True

                else:
                    logger.error("❌ No greeting audio generated")

            except Exception as e:
                logger.error(f"✗ Greeting error: {e}")
                traceback.print_exc()
            
            message_count = 2
        
        # ========== MAIN MESSAGE LOOP ==========
        while True:
            try:
                message = await websocket.receive_text()
                message_count += 1
                
                data = json.loads(message)
                event = data.get("event")
                
                if message_count % 100 == 0:
                    logger.info(f"📊 Processed {message_count} messages")
                
                if event == "connected":
                    logger.debug("📡 Connected event")
                    
                elif event == "start":
                    if not has_sent_greeting:
                        stream_sid = data.get("streamSid")
                        stream_service.set_stream_sid(stream_sid)
                        logger.info(f"🚀 Stream started: {stream_sid}")
                        
                        try:
                            redis_service.update_session(call_sid, {"stream_sid": stream_sid})
                        except:
                            pass
                        
                        greeting_text = f"Thank you for calling {voice_config.CLINIC_NAME}! How can I help you today?"
                        logger.info("💬 Sending greeting...")
                        
                        try:
                            greeting_chunks = []
                            async for audio_b64 in tts_service.generate(greeting_text):
                                if audio_b64:
                                    greeting_chunks.append(audio_b64)

                            if greeting_chunks:
                                # Combine all chunks into one
                                combined_greeting = b''.join([base64.b64decode(c) for c in greeting_chunks])
                                final_greeting_b64 = base64.b64encode(combined_greeting).decode('ascii')
                                
                                # Send as single chunk
                                await stream_service._send_audio(final_greeting_b64)

                            logger.info("✓ Greeting sent")
                            has_sent_greeting = True
                        except Exception as e:
                            logger.error(f"✗ Greeting error: {e}")
                            import traceback
                            traceback.print_exc()
                
                elif event == "media":
                    # ========== FORWARD AUDIO TO DEEPGRAM FOR TRANSCRIPTION ==========
                    if deepgram_service and deepgram_service.is_ready():
                        payload = data.get("media", {}).get("payload")
                        if payload:
                            # Send base64 audio to Deepgram
                            deepgram_service.send(payload)
                
                elif event == "mark":
                    mark_name = data.get("mark", {}).get("name")
                    if message_count % 50 == 0:
                        logger.debug(f"✓ Mark: {mark_name}")
                
                elif event == "stop":
                    logger.info("\n🛑 Stop event received")
                    break
                    
            except WebSocketDisconnect:
                logger.info("\n✓ Client disconnected")
                break
            except json.JSONDecodeError as e:
                logger.error(f"✗ JSON error: {e}")
                continue
            except Exception as e:
                logger.error(f"✗ Loop error: {e}")
                traceback.print_exc()
                continue
    
    except Exception as e:
        logger.error(f"\n✗ FATAL ERROR: {e}")
        traceback.print_exc()
    
    finally:
        # Cleanup
        logger.info(f"\n{'=' * 80}")
        logger.info("🧹 Cleaning up...")
        
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
            except:
                pass
        
        try:
            from starlette.websockets import WebSocketState
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close()
                logger.info("✓ WebSocket closed")
        except:
            pass
        
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
        logger.error(f"✗ Status error: {e}")
        return JSONResponse({"success": False, "error": str(e)})
