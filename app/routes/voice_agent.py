from fastapi import (
    APIRouter, Request, WebSocket, WebSocketDisconnect, Depends, HTTPException, Form, Query
)
from fastapi.responses import Response, JSONResponse
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any, List
import json
import base64
import traceback
import asyncio
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream, Play, Gather
from app.config.database import get_db
from app.config.voice_config import voice_config
from app.services.voice_agent_service import VoiceAgentService
from app.services.twilio_service import twilio_service
from app.services.openai_service import openai_service
from app.services.redis_service import redis_service
from app.models.call_session import CallSession
from app.schemas.call_session import CallSessionResponse, CallSessionDetail
from app.services.elevenlabs_service import elevenlabs_service
from app.services.deepgram_service import DeepgramService, DeepgramManager
from starlette.websockets import WebSocketState
from app.config.database import SessionLocal

router = APIRouter(prefix="/voice", tags=["Voice Agent"])


# Active WebSocket connections
active_connections: Dict[str, WebSocket] = {}

call_context: Dict[str, Dict[str, Any]] = {}

async def send_twilio_media(websocket: WebSocket, stream_sid: str, audio_chunk: bytes):
    payload = base64.b64encode(audio_chunk).decode("utf-8")
    await websocket.send_json({
        "event": "media",
        "streamSid": stream_sid,
        "media": {
            "payload": payload
            # Twilio infers encoding (mulaw) and rate (8000) from the stream setup
        }
    })

# Helper to send mark message to Twilio
async def send_twilio_mark(websocket: WebSocket, stream_sid: str, mark_name: str):
    await websocket.send_json({
        "event": "mark",
        "streamSid": stream_sid,
        "mark": {
            "name": mark_name
        }
    })

# --- Main Callback for Transcription Results ---
async def handle_full_transcript(call_sid: str, transcript: str):
    """Callback triggered by Deepgram upon detecting end of user speech."""
    print(f"Full transcript received for {call_sid}: '{transcript}'")
    
    context = call_context.get(call_sid)
    if not context or not transcript:
        print(f"No context or empty transcript for {call_sid}, skipping AI.")
        return

    websocket = context.get("websocket")
    agent = context.get("agent")
    stream_sid = context.get("stream_sid")

    if not all([websocket, agent, stream_sid]):
        print(f"Missing context components for {call_sid}.")
        return

    try:
        # 1. Get AI response (using existing service logic)
        ai_result = await agent.process_user_speech(call_sid, transcript)
        response_text = ai_result.get("response")

        if not response_text:
            print(f"No response text from AI for {call_sid}.")
            # Optionally play a fallback message
            return

        # 2. Stream AI response using ElevenLabs TTS
        print(f"Streaming AI response for {call_sid}: '{response_text}'")
        async for audio_chunk in elevenlabs_service.generate_audio_stream(response_text):
            if audio_chunk:
                await send_twilio_media(websocket, stream_sid, audio_chunk)
            else:
                # Handle potential error during TTS streaming
                print(f"TTS stream returned None for {call_sid}, stopping playback.")
                break

        await send_twilio_mark(websocket, stream_sid, "agent_finished_speaking")
        print(f"Finished streaming AI response for {call_sid}")

    except Exception as e:
        print(f"Error handling full transcript for {call_sid}: {e}")
        traceback.print_exc()


# For websocket
@router.post("/incoming")
async def handle_incoming_call(
    request: Request,
    CallSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    db: Session = Depends(get_db)
):

    try:
        print(f"Incoming call: {CallSid} from {From}")
        base_url = str(request.base_url).rstrip("/")
        #host = "woozier-rotundly-rayan.ngrok-free.dev"
        #print(f"Request host: {host}")
        websocket_url = websocket_url = f"wss://{request.url.hostname}/api/v1/voice/stream?call_sid={CallSid}"
        #websocket_url = f"wss://{host}/test-ws"
        print(f"Connecting call {CallSid} to WebSocket: {websocket_url}")
        
        response = VoiceResponse()

        if not voice_config.VOICE_AGENT_ENABLED:
            response.say("Assistant unavailable.", voice="Polly.Amy", language="en-GB")
            response.hangup()
            return Response(content=str(response), media_type="application/xml")

        # Initiate call session state (Redis + DB)
        # agent = VoiceAgentService(db) # Agent instance created in WebSocket context now
        # await agent.initiate_call(CallSid, From, To)

        # Connect to WebSocket stream
        print(f"Connecting call {CallSid} to WebSocket: {websocket_url}")
        connect = Connect()
        connect.stream(url=websocket_url)
        response.append(connect)

        # Add a pause - Twilio needs a moment before starting stream sometimes
        response.pause(length=1) 

        # Fallback if WebSocket connection fails
        response.say("Sorry, I couldn't connect to the voice service.", voice="Polly.Amy", language="en-GB")
        response.hangup()

        return Response(content=str(response), media_type="application/xml")

    except Exception as e:
        print(f"Error handling incoming call: {e}")
        import traceback
        traceback.print_exc()
        twiml = VoiceResponse()
        twiml.say("An error occurred.", voice="Polly.Amy", language="en-GB")
        twiml.hangup()
        return Response(content=str(twiml), media_type="application/xml")

"""
@router.post("/incoming")
async def handle_incoming_call(
    request: Request,
    CallSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    db: Session = Depends(get_db)
):
    try:
        print(f"Incoming call: {CallSid} from {From}")
        base_url = str(request.base_url).rstrip("/")
        gather_url = f"{base_url}/api/v1/voice/gather" # Point to the gather endpoint
        response = VoiceResponse()

        if not voice_config.VOICE_AGENT_ENABLED:
            response.say(
                "I'm sorry, the voice assistant is currently unavailable. Please try again later.",
                 voice="Polly.Amy", language="en-GB" # Fallback voice
            )
            response.hangup()
            return Response(content=str(response), media_type="application/xml")

        # --- ELEVENLABS GREETING ---
        agent = VoiceAgentService(db)
        # Ensure session is created before generating audio that uses CallSid in filename
        await agent.initiate_call(CallSid, From, To) 

        greeting_text = f"Thank you for calling {voice_config.CLINIC_NAME}! How can I help you today?"
        
        # 1. Generate greeting audio
        greeting_audio_path = await elevenlabs_service.generate_and_save_audio(greeting_text, CallSid)

        if greeting_audio_path:
            # 2. Get full URL and use <Play>
            full_audio_url = f"{base_url}{greeting_audio_path}"
            print(f"Playing initial greeting from: {full_audio_url}")
            response.play(full_audio_url)
        else:
            # 3. Fallback to <Say> if ElevenLabs fails
            print("ElevenLabs failed for greeting, falling back to Polly.")
            response.say(greeting_text, voice="Polly.Amy", language="en-GB")
        # --- END ELEVENLABS GREETING ---

        # 4. Start Gathering *after* playing the greeting
        gather = Gather(
            input='speech',
            action=gather_url,
            method='POST',
            language='en-IN', # Or your preferred STT language
            speech_timeout='auto',
            speech_model='phone_call',
            enhanced=True,
            hints='appointment, doctor, booking, schedule, time, date'
            # No prompt needed inside Gather as it was played before
        )
        response.append(gather)

        response.say(
            "I didn't catch that. How can I help you?", 
            voice="Polly.Amy",
            language="en-GB"
        )
        # Redirect to gather, not incoming, to avoid infinite loop/new sessions
        response.redirect(gather_url) 
        
        return Response(content=str(response), media_type="application/xml")
        
    except Exception as e:
        print(f"Error handling incoming call: {e}")
        traceback.print_exc()
        
        # Generic error response
        twiml = VoiceResponse()
        twiml.say(
            "I'm sorry, we're experiencing technical difficulties. Please call back later.",
             voice="Polly.Amy", language="en-GB"
        )
        twiml.hangup()
        return Response(content=str(twiml), media_type="application/xml")
"""


@router.websocket("/stream")
async def websocket_stream(
    websocket: WebSocket,
    call_sid: Optional[str] = Query(None)
):
    
    # Accept WebSocket
    try:
        print("\n4. Attempting to accept WebSocket connection...")
        await websocket.accept()
        print("5. ✓ WebSocket accepted successfully!")
    except Exception as e:
        print(f"5. ✗ Failed to accept WebSocket: {e}")
        print(f"   Exception type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        return
    
    db = SessionLocal()
    
    if not call_sid:
        await websocket.send_json({
            "error": "Missing call_sid parameter",
            "message": "call_sid query parameter is required"
        })
        await websocket.close(code=1008, reason="Missing required parameter")
        return
    
    print(f"=" * 80)
    print(f"WebSocket accepted for call_sid: {call_sid}")
    print(f"=" * 80)

    print(f"=" * 80)
    print(f"1. WebSocket /stream endpoint hit")
    print(f"   Call SID: {call_sid}")
    print(f"   Client: {websocket.client}")
    print(f"   URL: {websocket.url}")
    print(f"=" * 80)
    
    # Log all headers
    print("2. Request Headers:")
    for key, value in websocket.headers.items():
        print(f"   {key}: {value}")
    
    # Check WebSocket specific headers
    print("\n3. WebSocket Upgrade Headers:")
    print(f"   Connection: {websocket.headers.get('connection', 'MISSING')}")
    print(f"   Upgrade: {websocket.headers.get('upgrade', 'MISSING')}")
    print(f"   Sec-WebSocket-Version: {websocket.headers.get('sec-websocket-version', 'MISSING')}")
    print(f"   Sec-WebSocket-Key: {websocket.headers.get('sec-websocket-key', 'MISSING')}")
    print(f"   Origin: {websocket.headers.get('origin', 'MISSING')}")
    print(f"   User-Agent: {websocket.headers.get('user-agent', 'MISSING')}")    
    try:
        # Initialize services
        print("\n6. Initializing Voice Agent Service...")
        agent = VoiceAgentService(db)
        await agent.initiate_call(call_sid, "WebSocket", "WebSocket")
        print("   ✓ Voice Agent initialized")
        
        stream_sid = None
        deepgram_manager = DeepgramManager()
        
        # Initialize Deepgram with better error handling
        print("\n7. Initializing Deepgram STT Service...")
        try:
            # Check if Deepgram credentials are configured
            if not hasattr(deepgram_manager, 'create_connection'):
                print("   ✗ Deepgram manager not properly initialized")
                deepgram_service = None
            else:
                deepgram_service = deepgram_manager.create_connection(
                    call_sid=call_sid,
                    on_speech_end_callback=lambda transcript: asyncio.create_task(
                        handle_full_transcript(call_sid, transcript)
                    )
                )
                print("   ✓ Deepgram connection object created")
                
                if deepgram_service:
                    connected = await deepgram_service.connect()
                    if connected:
                        print("   ✓ Deepgram connected successfully")
                    else:
                        print("   ✗ Deepgram connection failed")
                        deepgram_service = None
        except Exception as e:
            print(f"   ✗ Deepgram initialization error: {e}")
            print(f"      Error type: {type(e).__name__}")
            deepgram_service = None
        
        # If this is a test connection without Deepgram requirement, continue
        if call_sid == "test123":
            print("\n8. Test connection detected, skipping Deepgram requirement")
        elif not deepgram_service:
            print("\n8. Deepgram required but not available, closing connection")
            await websocket.send_json({
                "error": "STT service unavailable",
                "message": "Could not initialize speech-to-text service"
            })
            await websocket.close(code=1011, reason="STT connection failed")
            await agent.end_call(call_sid)
            db.close()
            return
        
        # Store context
        call_context[call_sid] = {
            "websocket": websocket,
            "agent": agent,
            "deepgram": deepgram_service,
            "stream_sid": None
        }
        print("\n9. Context stored, ready to receive messages")
        
        has_sent_greeting = False
        message_count = 0
        
        # Main message loop
        print("\n10. Entering main message loop...")
        print("=" * 80)
        
        while True:
            try:
                message = await websocket.receive_text()
                message_count += 1
                
                data = json.loads(message)
                event = data.get("event")
                
                print(f"\n[Message {message_count}] Event: {event}")
                
                if event == "start":
                    stream_sid = data.get("streamSid")
                    start_data = data.get("start", {})
                    print(f"   Stream SID: {stream_sid}")
                    print(f"   Account SID: {start_data.get('accountSid', 'N/A')}")
                    print(f"   Call SID: {start_data.get('callSid', 'N/A')}")
                    print(f"   Media Format: {start_data.get('mediaFormat', {})}")
                    
                    call_context[call_sid]["stream_sid"] = stream_sid
                    redis_service.update_session(call_sid, {"stream_sid": stream_sid})
                    
                    if not has_sent_greeting:
                        greeting_text = f"Thank you for calling {voice_config.CLINIC_NAME}! How can I help you today?"
                        print(f"   Sending greeting: '{greeting_text}'")
                        
                        try:
                            async for audio_chunk in elevenlabs_service.generate_audio_stream(greeting_text):
                                if audio_chunk:
                                    await send_twilio_media(websocket, stream_sid, audio_chunk)
                            print("   ✓ Greeting sent successfully")
                        except Exception as e:
                            print(f"   ✗ Error sending greeting: {e}")
                        
                        await send_twilio_mark(websocket, stream_sid, "agent_finished_speaking")
                        has_sent_greeting = True
                
                elif event == "media":
                    # Don't log every media event (too many)
                    if message_count % 50 == 0:  # Log every 50th media message
                        print(f"   Received {message_count} media messages...")
                    
                    payload = data.get("media", {}).get("payload")
                    if payload and deepgram_service:
                        audio_chunk = base64.b64decode(payload)
                        await deepgram_service.send_audio(audio_chunk)
                
                elif event == "mark":
                    mark_name = data.get("mark", {}).get("name")
                    print(f"   Mark received: {mark_name}")
                
                elif event == "stop":
                    print(f"   Stop event received, closing connection")
                    break
                
                else:
                    print(f"   Unknown event: {event}")
                    print(f"   Data: {json.dumps(data, indent=2)}")
                    
            except WebSocketDisconnect:
                print(f"\n✓ WebSocket disconnected by client")
                break
            except json.JSONDecodeError as e:
                print(f"\n✗ JSON decode error: {e}")
                continue
            except Exception as e:
                print(f"\n✗ Error in message loop: {e}")
                print(f"   Error type: {type(e).__name__}")
                import traceback
                traceback.print_exc()
                continue
    
    except Exception as e:
        print(f"\n✗ Fatal error in WebSocket handler: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        print(f"\n" + "=" * 80)
        print("Cleaning up connection...")
        
        if 'deepgram_service' in locals() and deepgram_service:
            try:
                await deepgram_manager.remove_connection(call_sid)
                print("   ✓ Deepgram cleaned up")
            except:
                print("   ✗ Error cleaning up Deepgram")
        
        call_context.pop(call_sid, None)
        print("   ✓ Context cleared")
        
        if 'agent' in locals():
            try:
                await agent.end_call(call_sid)
                print("   ✓ Call ended")
            except:
                print("   ✗ Error ending call")
        
        db.close()
        print("   ✓ Database closed")
        
        try:
            await websocket.close()
            print("   ✓ WebSocket closed")
        except:
            pass  # Already closed
        
        print(f"✓ Cleanup complete for call {call_sid}")
        print("=" * 80)

async def process_audio_buffer(
    call_sid: str,
    audio_buffer: list,
    websocket: WebSocket,
    agent: VoiceAgentService
):
    """Process accumulated audio buffer"""
    try:
        audio_data = b"".join([base64.b64decode(chunk) for chunk in audio_buffer])
        
        # Implement Deepgram here
        print(f"Processing audio buffer for {call_sid}")
        
    except Exception as e:
        print(f"Error processing audio: {e}")

"""
@router.post("/gather")
async def handle_gather(
    request: Request,
    CallSid: str = Form(...),
    SpeechResult: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    try:
        base_url = str(request.base_url).rstrip("/")
        gather_url = f"{base_url}/api/v1/voice/gather"
        response = VoiceResponse()
        
        print(f"Speech received for {CallSid}: {SpeechResult}")
        
        if not SpeechResult:
            # No speech detected, try again
            gather = Gather(
                input='speech',
                action=gather_url,
                method='POST',
                language='en-IN',
                speech_timeout='auto',
                speech_model='phone_call'
            )
            gather.say(
                "I didn't catch that. Could you please repeat?",
                voice="Polly.Amy", # Fallback to Polly for errors
                language="en-GB"
            )
            response.append(gather)
            return Response(content=str(response), media_type="application/xml")
        
        # Process user speech with AI
        agent = VoiceAgentService(db)
        result = await agent.process_user_speech(CallSid, SpeechResult)
        
        if not result.get("success"):
            gather = Gather(
                input='speech',
                action=gather_url,
                method='POST',
                language='en-IN',
                speech_timeout='auto'
            )
            gather.say(
                "I'm having trouble processing that. Please try again.",
                voice="Polly.Amy", # Fallback to Polly for errors
                language="en-GB"
            )
            response.append(gather)
            return Response(content=str(response), media_type="application/xml")

        response_text = result.get("response", "")

        # --- ELEVENLABS INTEGRATION ---
        # 1. Generate the audio and get the relative path
        audio_path = await elevenlabs_service.generate_and_save_audio(response_text, CallSid)
        
        if not audio_path:
            # Fallback to Polly if ElevenLabs fails
            print("ElevenLabs failed, falling back to Polly.")
            gather = Gather(input='speech', action=gather_url, method='POST')
            gather.say(response_text, voice="Polly.Amy", language="en-GB")
            response.append(gather)
            return Response(content=str(response), media_type="application/xml")

        # 2. Create the full public URL for Twilio to access
        full_audio_url = f"{base_url}{audio_path}"
        print(f"Playing ElevenLabs audio from: {full_audio_url}")

        end_phrases = ["goodbye", "have a great day"]
        should_end = any(phrase in response_text.lower() for phrase in end_phrases)
        
        if should_end:
            # 3. Use <Play> instead of <Say>
            response.play(full_audio_url)
            response.hangup()
            await agent.end_call(CallSid)
        else:
            gather = Gather(
                input='speech',
                action=gather_url,
                method='POST',
                language='en-IN',
                speech_timeout='auto',
                speech_model='phone_call',
                enhanced=True
            )
            
            # 4. Use <Play> inside <Gather>
            gather.play(full_audio_url)
            response.append(gather)

            # Fallback if user says nothing
            response.say("Are you still there?", voice="Polly.Amy", language="en-GB")
            response.redirect(gather_url)
        
        return Response(content=str(response), media_type="application/xml")
        
    except Exception as e:
        # ... (error handling)
        pass
    """

@router.post("/status")
async def handle_call_status(
    request: Request,
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    Handle call status updates from Twilio
    """
    try:
        print(f"Call status update: {CallSid} - {CallStatus}")

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
        print(f"Error handling status: {e}")
        return JSONResponse({"success": False, "error": str(e)})


@router.get("/sessions/active")
async def get_active_sessions():
    """Get all active call sessions"""
    try:
        sessions = redis_service.get_all_active_sessions()
        return {
            "success": True,
            "count": len(sessions),
            "sessions": sessions
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{call_sid}", response_model=CallSessionDetail)
async def get_call_session(call_sid: str, db: Session = Depends(get_db)):
    """Get call session details"""
    try:
        session = db.query(CallSession).filter(
            CallSession.call_sid == call_sid
        ).first()
        
        if not session:
            raise HTTPException(status_code=404, detail="Call session not found")
        
        return session
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions")
async def list_call_sessions(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """List all call sessions with pagination"""
    try:
        sessions = db.query(CallSession).order_by(
            CallSession.created_at.desc()
        ).offset(skip).limit(limit).all()
        
        total = db.query(CallSession).count()
        
        return {
            "success": True,
            "total": total,
            "count": len(sessions),
            "sessions": [s.to_dict() for s in sessions]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        redis_ok = redis_service.redis_client.ping()

        twilio_ok = bool(
            voice_config.TWILIO_ACCOUNT_SID and 
            voice_config.TWILIO_AUTH_TOKEN
        )

        openai_ok = bool(voice_config.OPENAI_API_KEY)
        elevenlabs_ok = bool(voice_config.ELEVENLABS_API_KEY)
        
        return {
            "status": "healthy",
            "voice_agent_enabled": voice_config.VOICE_AGENT_ENABLED,
            "redis": "connected" if redis_ok else "disconnected",
            "twilio": "configured" if twilio_ok else "not configured",
            "openai": "configured" if openai_ok else "not configured",
            "elevenlabs": "configured" if elevenlabs_ok else "not configured",
            "deepgram": "configured" if deepgram_ok else "not configured",
            "active_calls": len(active_connections)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test/call")
async def test_voice_agent(
    phone_number: str,
    db: Session = Depends(get_db)
):
    """
    Test endpoint to initiate a test call
    """
    try:
        from app.utils.validators import validate_phone_number
        
        is_valid, formatted = validate_phone_number(phone_number)
        if not is_valid:
            raise HTTPException(status_code=400, detail="Invalid phone number")

        call = twilio_service.client.calls.create(
            to=formatted,
            from_=voice_config.TWILIO_PHONE_NUMBER,
            url=f"{request.base_url}api/v1/voice/incoming",
            status_callback=f"{request.base_url}api/v1/voice/status"
        )
        
        return {
            "success": True,
            "call_sid": call.sid,
            "to": formatted,
            "status": call.status
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
