# app\routes\voice_agent.py
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, Form, Query, Depends
from fastapi.responses import Response, JSONResponse
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
import json
import base64
import traceback
import asyncio
import logging
import uuid
from twilio.twiml.voice_response import VoiceResponse, Connect
from app.config.database import SessionLocal, get_db
from app.config.voice_config import voice_config
from app.services.voice_agent_service import VoiceAgentService
from app.services.redis_service import redis_service
from app.models.call_session import CallSession
from app.services.stream_service import StreamService
from app.services.elevenlabs_service import elevenlabs_service
from app.services.deepgram_service import DeepgramManager
import time
from starlette.websockets import WebSocketState
from app.utils.latency_tracker import latency_tracker

# logging.basicConfig(level=logging.INFO)
# Use clean logger
logger = logging.getLogger("voice")

router = APIRouter(prefix="/voice", tags=["Voice Agent"])

call_context: Dict[str, Dict[str, Any]] = {}

async def handle_full_transcript(
    call_sid: str,
    transcript: str,
    stream_service: StreamService,
    tts_service: any
):
    """
    ⚡ OPTIMIZED with CLEAN logging
    """
    # Start tracking
    interaction_id = str(uuid.uuid4())[:8]  # Short ID
    metrics = latency_tracker.start_interaction(call_sid, interaction_id)
    metrics.transcript_received_at = time.time()
    
    # Clean, single-line log
    logger.info(f"📝 USER: '{transcript}'")
    
    context = call_context.get(call_sid)
    if not context or not transcript.strip():
        return
    
    agent: VoiceAgentService = context.get("agent")
    if not agent:
        return
    
    try:
        # AI Processing
        ai_result = await agent.process_user_speech(call_sid, transcript, metrics)
        
        response_text = ai_result.get("response")
        if not response_text:
            response_text = "I'm sorry, could you please repeat that?"
        
        logger.info(f"💬 AI: '{response_text[:100]}{'...' if len(response_text) > 100 else ''}'")

        # TTS Generation with streaming
        metrics.tts_request_start = time.time()
        await stream_service.clear()

        chunk_count = 0
        
        # Stream chunks immediately
        async for audio_b64 in tts_service.generate(response_text):
            if audio_b64:
                if chunk_count == 0:
                    metrics.tts_first_chunk = time.time()
                    ttfa = (metrics.tts_first_chunk - metrics.transcript_received_at) * 1000
                    logger.info(f"⚡ First audio in {ttfa:.0f}ms")
                
                chunk_count += 1
                metrics.tts_chunks_count = chunk_count
                await stream_service.send_audio_chunk(audio_b64, metrics)
        
        metrics.tts_complete = time.time()
        
        if chunk_count == 0:
            logger.error("❌ No audio generated")
            return
        
        # Complete tracking (this logs the full summary)
        latency_tracker.complete_interaction(interaction_id)
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        traceback.print_exc()  # Add full traceback for debugging
        
        try:
            latency_tracker.complete_interaction(interaction_id)
        except:
            pass

        # ✅ YES - KEEP THIS ERROR RECOVERY CODE
        # It ensures the user gets a response even if something fails
        try:
            error_msg = "I apologize, I'm having trouble. Could you try again?"
            logger.info("🔧 Sending error message...")

            async for audio_b64 in tts_service.generate(error_msg):
                if audio_b64:
                    await stream_service.send_audio_chunk(audio_b64, None)

            logger.info("✓ Error message sent")

        except Exception as err:
            logger.error(f"❌ Error recovery failed: {err}")

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
        logger.info(f"Incoming call: {CallSid} from {From}")
        logger.info(f"Request URL: {request.url}")
        logger.info(f"Request path: {request.url.path}")
        
        response = VoiceResponse()
        
        if not voice_config.VOICE_AGENT_ENABLED:
            response.say("Assistant unavailable.", voice="Polly.Amy", language="en-GB")
            response.hangup()
            return Response(content=str(response), media_type="application/xml")
        
        # ⚡ DETECT ENVIRONMENT from X-Forwarded-Prefix header or path
        forwarded_prefix = request.headers.get("x-forwarded-prefix", "")
        request_path = request.url.path
        
        # Determine if this is dev or prod based on the incoming path/prefix
        if "/api/dev/" in forwarded_prefix or "/api/dev/" in request_path:
            # Development environment
            websocket_url = f"wss://{request.url.hostname}/api/dev/v1/voice/stream?call_sid={CallSid}"
            logger.info("🔧 Environment: DEVELOPMENT")
        else:
            # Production environment
            websocket_url = f"wss://{request.url.hostname}/api/v1/voice/stream?call_sid={CallSid}"
            logger.info("🏭 Environment: PRODUCTION")
        
        logger.info(f"🔌 WebSocket URL: {websocket_url}")
        
        # Connect to WebSocket stream
        connect = Connect()
        connect.stream(url=websocket_url)
        response.append(connect)

        response.pause(length=60)
        
        logger.info("TwiML response generated")
        logger.info("=" * 80)
        
        return Response(content=str(response), media_type="application/xml")
        
    except Exception as e:
        logger.error(f"Error handling incoming call: {e}")
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
    
    # Accept WebSocket
    try:
        logger.info("\n" + "=" * 80)
        logger.info("Accepting WebSocket...")
        await websocket.accept()
        logger.info("WebSocket accepted")
    except Exception as e:
        logger.error(f"Failed to accept WebSocket: {e}")
        traceback.print_exc()
        return
    
    # Get call_sid from query params or wait for start event
    call_sid = websocket.query_params.get("call_sid")
    logger.info(f"Query parameters: {dict(websocket.query_params)}")
    
    first_message_data = None
    if not call_sid:
        logger.warning("No call_sid in query params, waiting for Twilio events...")
        
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
                
                logger.info(f"Received event #{attempt + 1}: {event_type}")
                
                if event_type == "connected":
                    logger.info("Received 'connected' event")
                    continue
                    
                elif event_type == "start":
                    call_sid = data.get("start", {}).get("callSid")
                    first_message_data = data
                    logger.info(f"Extracted call_sid: {call_sid}")
                    break
                    
        except asyncio.TimeoutError:
            logger.error("Timeout waiting for start event")
            await websocket.close(code=1008)
            return
        except Exception as e:
            logger.error(f"Error receiving messages: {e}")
            await websocket.close(code=1011)
            return
    
    if not call_sid:
        logger.error("Could not obtain call_sid")
        await websocket.close(code=1008)
        return
    
    logger.info(f"Call SID validated: {call_sid}")
    
    # Initialize database
    db = None
    try:
        logger.info("Creating database session...")
        db = SessionLocal()
        logger.info("Database session created")
    except Exception as e:
        logger.error(f"Database creation failed: {e}")
        await websocket.close()
        return
    
    # Initialize services
    stream_service = None
    tts_service = None
    deepgram_manager = None
    agent = None
    deepgram_service = None
    
    try:
        logger.info("Initializing StreamService...")
        stream_service = StreamService(websocket)
        logger.info("StreamService initialized")
        
        logger.info("Initializing Elevenlabs TTSService...")
        tts_service = elevenlabs_service
        logger.info("Elevenlabs initialized")
        
        logger.info("Initializing DeepgramManager...")
        deepgram_manager = DeepgramManager()
        logger.info("DeepgramManager initialized")
        
        logger.info("Initializing VoiceAgentService...")
        agent = VoiceAgentService(db)
        await agent.initiate_call(call_sid, "WebSocket", "WebSocket")
        logger.info("VoiceAgentService initialized (AI Tools ready!)")
        
        logger.info("Initializing Deepgram STT...")
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
                    logger.info("Deepgram connected (STT ready!)")
                else:
                    logger.warning("Deepgram connection failed")
                    deepgram_service = None
        except Exception as e:
            logger.error(f"Deepgram error: {e}")
            traceback.print_exc()
            deepgram_service = None
        
        # Store context
        logger.info("Storing context...")
        call_context[call_sid] = {
            "websocket": websocket,
            "agent": agent,
            "deepgram": deepgram_service,
            "stream_service": stream_service,
            "tts_service": tts_service
        }
        logger.info("Context stored")
        
        logger.info("Entering message loop...")
        logger.info("=" * 80)
        
        has_sent_greeting = False
        message_count = 0
        
        # Process buffered start event if we have it
        if first_message_data and first_message_data.get("event") == "start":
            logger.info("Processing buffered start event...")
            stream_sid = first_message_data.get("streamSid")
            stream_service.set_stream_sid(stream_sid)
            
            logger.info(f"Stream started: {stream_sid}")
            
            # Update Redis
            try:
                redis_service.update_session(call_sid, {"stream_sid": stream_sid})
            except Exception as e:
                logger.error(f"Redis error: {e}")
            
            await stream_service.clear()
            # Send greeting
            greeting_text = f"Thank you for calling {voice_config.CLINIC_NAME}! How can I help you today?"
            logger.info(f"Sending greeting...")
            
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

                    logger.info("Greeting sent")
                    has_sent_greeting = True

                else:
                    logger.error("No greeting audio generated")

            except Exception as e:
                logger.error(f"Greeting error: {e}")
                traceback.print_exc()
            
            message_count = 2
        
        # MAIN MESSAGE LOOP
        while True:
            try:
                message = await websocket.receive_text()
                message_count += 1
                
                data = json.loads(message)
                event = data.get("event")
                
                if message_count % 100 == 0:
                    logger.debug(f"Processed {message_count} messages")
                
                if event == "connected":
                    logger.debug("Connected event")
                    
                elif event == "start":
                    if not has_sent_greeting:
                        stream_sid = data.get("streamSid")
                        stream_service.set_stream_sid(stream_sid)
                        logger.info(f"Stream started: {stream_sid}")
                        
                        try:
                            redis_service.update_session(call_sid, {"stream_sid": stream_sid})
                        except:
                            pass
                        
                        greeting_text = f"Thank you for calling {voice_config.CLINIC_NAME}! How can I help you today?"
                        logger.info("Sending greeting...")
                        
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
                    if deepgram_service and deepgram_service.is_ready():
                        payload = data.get("media", {}).get("payload")
                        if payload:
                            deepgram_service.send(payload)
                
                elif event == "mark":
                    mark_name = data.get("mark", {}).get("name")
                    if message_count % 50 == 0:
                        logger.debug(f"✓ Mark: {mark_name}")
                
                elif event == "stop":
                    logger.info("\nStop event received")
                    break
                    
            except WebSocketDisconnect:
                logger.info("\nClient disconnected")
                break
            except json.JSONDecodeError as e:
                logger.error(f"JSON error: {e}")
                continue
            except Exception as e:
                logger.error(f"Loop error: {e}")
                traceback.print_exc()
                continue
    
    except Exception as e:
        logger.error(f"\nFATAL ERROR: {e}")
        traceback.print_exc()
    
    finally:
        # Cleanup
        logger.info(f"\n{'=' * 80}")
        logger.info("Cleaning up...")
        
        if deepgram_service and deepgram_manager:
            try:
                await deepgram_manager.remove_connection(call_sid)
                logger.info("Deepgram cleaned up")
            except Exception as e:
                logger.error(f"Deepgram cleanup error: {e}")
        
        call_context.pop(call_sid, None)
        logger.info("Context cleared")
        
        if agent:
            try:
                await agent.end_call(call_sid)
                logger.info("Call ended")
            except Exception as e:
                logger.error(f"Call end error: {e}")
        
        if db:
            try:
                db.close()
                logger.info("Database closed")
            except:
                pass
        
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close()
                logger.info("WebSocket closed")
        except:
            pass
        
        logger.info(f"Cleanup complete for {call_sid}")
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
        logger.info(f"Call status: {CallSid} - {CallStatus}")
        
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
        logger.error(f"Status error: {e}")
        return JSONResponse({"success": False, "error": str(e)})
