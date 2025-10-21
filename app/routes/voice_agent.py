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
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream, Play
from app.config.database import get_db
from app.config.voice_config import voice_config
from app.services.voice_agent_service import VoiceAgentService
from app.services.twilio_service import twilio_service
from app.services.openai_service import openai_service
from app.services.redis_service import redis_service
from app.models.call_session import CallSession
from app.schemas.call_session import CallSessionResponse, CallSessionDetail
from app.services.elevenlabs_service import elevenlabs_service
from app.services.deepgram_service import DeepgramService, deepgram_manager

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


@router.post("/incoming")
async def handle_incoming_call(
    request: Request,
    CallSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    Twilio webhook for incoming calls.
    Connects to the WebSocket stream.
    """
    try:
        print(f"Incoming call: {CallSid} from {From}")
        base_url = str(request.base_url).rstrip("/")
        # Use wss:// if your server uses HTTPS
        websocket_url = f"ws://{request.url.hostname}/api/v1/voice/stream?call_sid={CallSid}"
        
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


@router.websocket("/stream")
async def websocket_stream(
    websocket: WebSocket,
    call_sid: str = Query(...), # Get call_sid from query param
    db: Session = Depends(get_db)
):
    """WebSocket endpoint for real-time audio streaming with STT and TTS."""
    await websocket.accept()
    print(f"WebSocket connected for call: {call_sid}")

    agent = VoiceAgentService(db)
    # Ensure call session is initiated *before* Deepgram connects
    # This prevents race conditions if Deepgram connects faster than initiate_call finishes
    await agent.initiate_call(call_sid, "WebSocket", "WebSocket") # Use placeholders for From/To

    stream_sid = None # Will be populated by 'start' event

    # --- Initialize Deepgram ---
    # Pass the callback function to handle full transcripts
    deepgram_service = deepgram_manager.create_connection(
        call_sid=call_sid,
        on_speech_end_callback=lambda transcript: handle_full_transcript(call_sid, transcript)
    )
    if not await deepgram_service.connect():
        print(f"Failed to connect to Deepgram for {call_sid}. Closing WebSocket.")
        await websocket.close(code=1011, reason="STT connection failed")
        await agent.end_call(call_sid) # Clean up session state
        await deepgram_manager.remove_connection(call_sid)
        return

    # Store context for this call
    call_context[call_sid] = {
        "websocket": websocket,
        "agent": agent,
        "deepgram": deepgram_service,
        "stream_sid": None # Will be updated on 'start'
    }

    try:
        # --- Initial Greeting ---
        # We need the stream_sid *before* we can play audio back
        # So we wait for the 'start' message, then send the greeting
        has_sent_greeting = False

        while True:
            message = await websocket.receive_text()
            data = json.loads(message)
            event = data.get("event")

            if event == "start":
                stream_sid = data.get("streamSid")
                print(f"Twilio stream started: {stream_sid} for call {call_sid}")
                call_context[call_sid]["stream_sid"] = stream_sid
                redis_service.update_session(call_sid, {"stream_sid": stream_sid})

                # Now that we have stream_sid, send the initial greeting
                if not has_sent_greeting:
                    greeting_text = f"Thank you for calling {voice_config.CLINIC_NAME}! How can I help you today?"
                    print(f"Sending initial greeting for {call_sid}")
                    async for audio_chunk in elevenlabs_service.generate_audio_stream(greeting_text):
                        if audio_chunk:
                            await send_twilio_media(websocket, stream_sid, audio_chunk)
                        else:
                            print(f"Greeting TTS stream failed for {call_sid}.")
                            break # Stop trying to send greeting
                    await send_twilio_mark(websocket, stream_sid, "agent_finished_speaking")
                    has_sent_greeting = True
                    print(f"Finished sending initial greeting for {call_sid}")


            elif event == "media":
                # Audio chunk from Twilio (user speaking)
                payload = data.get("media", {}).get("payload")
                if payload:
                    # Decode from base64 and send to Deepgram
                    audio_chunk = base64.b64decode(payload)
                    await deepgram_service.send_audio(audio_chunk)

            elif event == "mark":
                # Confirmation that our 'agent_finished_speaking' mark was received by Twilio
                mark_name = data.get("mark", {}).get("name")
                if mark_name == "agent_finished_speaking":
                    print(f"Twilio acknowledged agent finished speaking for {call_sid}")
                    # You could potentially trigger something here if needed

            elif event == "stop":
                print(f"Twilio stream stopped for call: {call_sid}")
                break # Exit loop, will trigger finally block

    except WebSocketDisconnect:
        print(f"WebSocket disconnected by client for call: {call_sid}")
    except Exception as e:
        print(f"WebSocket error for call {call_sid}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print(f"Cleaning up resources for call: {call_sid}")
        # Close Deepgram connection
        await deepgram_manager.remove_connection(call_sid)
        # Clean up context
        call_context.pop(call_sid, None)
        # End call session state (Redis + DB)
        await agent.end_call(call_sid)
        # Ensure WebSocket is closed
        try:
            await websocket.close()
        except RuntimeError: # Already closed
            pass
        print(f"Cleanup complete for call: {call_sid}")

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


"""@router.post("/gather")
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
