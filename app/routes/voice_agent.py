from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, Depends, HTTPException, Form
from fastapi.responses import Response, JSONResponse
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
import json
import base64
import asyncio
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream
from app.config.database import get_db
from app.config.voice_config import voice_config
from app.services.voice_agent_service import VoiceAgentService
from app.services.twilio_service import twilio_service
from app.services.openai_service import openai_service
from app.services.redis_service import redis_service
from app.models.call_session import CallSession
from app.schemas.call_session import CallSessionResponse, CallSessionDetail

router = APIRouter(prefix="/voice", tags=["Voice Agent"])


# Active WebSocket connections
active_connections: Dict[str, WebSocket] = {}


@router.post("/incoming")
async def handle_incoming_call(
    request: Request,
    CallSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    Twilio webhook for incoming calls
    Uses Gather for speech recognition (more reliable than WebSocket)
    """
    try:
        print(f"Incoming call: {CallSid} from {From}")

        if not voice_config.VOICE_AGENT_ENABLED:
            twiml = twilio_service.create_say_response(
                "I'm sorry, the voice assistant is currently unavailable. Please try again later.",
                hangup=True
            )
            return Response(content=twiml, media_type="application/xml")

        agent = VoiceAgentService(db)
        await agent.initiate_call(CallSid, From, To)

        base_url = str(request.base_url).rstrip("/")
        gather_url = f"{base_url}/api/v1/voice/gather"

        from twilio.twiml.voice_response import VoiceResponse, Gather
        
        response = VoiceResponse()

        gather = Gather(
            input='speech',
            action=gather_url,
            method='POST',
            language='en-IN',
            speech_timeout='auto',
            speech_model='phone_call',
            enhanced=True,
            hints='appointment, doctor, booking, schedule, time, date'
        )

        gather.say(
            f"Hello! Thank you for calling {voice_config.CLINIC_NAME}. "
            "I'm your AI assistant. How may I help you today?",
            voice="Polly.Aditi",
            language="en-IN"
        )
        
        response.append(gather)

        response.say(
            "I didn't catch that. Let me try again.",
            voice="Polly.Aditi",
            language="en-IN"
        )
        response.redirect(f"{base_url}/api/v1/voice/incoming")
        
        return Response(content=str(response), media_type="application/xml")
        
    except Exception as e:
        print(f"Error handling incoming call: {e}")
        import traceback
        traceback.print_exc()
        
        twiml = twilio_service.create_say_response(
            "I'm sorry, we're experiencing technical difficulties. Please call back later.",
            hangup=True
        )
        return Response(content=twiml, media_type="application/xml")


@router.websocket("/stream")
async def websocket_stream(
    websocket: WebSocket,
    call_sid: str,
    db: Session = Depends(get_db)
):
    """
    WebSocket endpoint for real-time audio streaming
    """
    await websocket.accept()
    print(f"WebSocket connected: {call_sid}")
    
    active_connections[call_sid] = websocket
    agent = VoiceAgentService(db)
    
    audio_buffer = []
    
    try:
        while True:
            message = await websocket.receive_text()
            data = json.loads(message)
            
            event = data.get("event")
            
            if event == "start":
                print(f"🎙️ Stream started: {call_sid}")
                stream_sid = data.get("streamSid")
                redis_service.update_session(call_sid, {"stream_sid": stream_sid})
            
            elif event == "media":
                payload = data.get("media", {}).get("payload")
                if payload:
                    audio_buffer.append(payload)

                    if len(audio_buffer) >= 20:
                        await process_audio_buffer(
                            call_sid, 
                            audio_buffer, 
                            websocket, 
                            agent
                        )
                        audio_buffer.clear()
            
            elif event == "stop":
                print(f"Stream stopped: {call_sid}")
                await agent.end_call(call_sid)
                break
            
    except WebSocketDisconnect:
        print(f"WebSocket disconnected: {call_sid}")
        await agent.end_call(call_sid)
    except Exception as e:
        print(f"WebSocket error: {e}")
        await agent.end_call(call_sid)
    finally:
        active_connections.pop(call_sid, None)
        await websocket.close()


async def process_audio_buffer(
    call_sid: str,
    audio_buffer: list,
    websocket: WebSocket,
    agent: VoiceAgentService
):
    """Process accumulated audio buffer"""
    try:
        audio_data = b"".join([base64.b64decode(chunk) for chunk in audio_buffer])
        
        # Transcribe with Whisper (you'd need to implement proper audio handling)
        # For now, we'll use Twilio's speech recognition via gather
        # This is a simplified version - in production, use proper audio processing
        
        # NOTE: Real implementation would:
        # 1. Convert mulaw audio to proper format
        # 2. Send to Whisper API
        # 3. Get transcription
        # 4. Process with GPT-4
        # 5. Generate TTS response
        # 6. Stream back to Twilio
        
        print(f"Processing audio buffer for {call_sid}")
        
    except Exception as e:
        print(f"Error processing audio: {e}")


@router.post("/gather")
async def handle_gather(
    request: Request,
    CallSid: str = Form(...),
    SpeechResult: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Handle speech input from Twilio Gather
    """
    try:
        print(f"💬 Speech received for {CallSid}: {SpeechResult}")
        
        if not SpeechResult:
            # No speech detected, try again
            base_url = str(request.base_url).rstrip("/")
            
            from twilio.twiml.voice_response import VoiceResponse, Gather
            response = VoiceResponse()
            
            gather = Gather(
                input='speech',
                action=f"{base_url}/api/v1/voice/gather",
                method='POST',
                language='en-IN',
                speech_timeout='auto',
                speech_model='phone_call'
            )
            
            gather.say(
                "I didn't catch that. Could you please repeat?",
                voice="Polly.Aditi",
                language="en-IN"
            )
            
            response.append(gather)
            return Response(content=str(response), media_type="application/xml")
        
        # Process user speech with AI
        agent = VoiceAgentService(db)
        result = await agent.process_user_speech(CallSid, SpeechResult)
        
        if not result.get("success"):
            from twilio.twiml.voice_response import VoiceResponse, Gather
            response = VoiceResponse()
            
            gather = Gather(
                input='speech',
                action=f"{str(request.base_url).rstrip('/')}/api/v1/voice/gather",
                method='POST',
                language='en-IN',
                speech_timeout='auto'
            )
            
            gather.say(
                "I'm having trouble processing that. Please try again.",
                voice="Polly.Aditi",
                language="en-IN"
            )
            
            response.append(gather)
            return Response(content=str(response), media_type="application/xml")

        response_text = result.get("response", "")

        end_phrases = [
            "goodbye",
            "have a great day",
            "anything else i can help",
            "is there anything else"
        ]
        should_end = any(phrase in response_text.lower() for phrase in end_phrases)

        from twilio.twiml.voice_response import VoiceResponse, Gather
        response = VoiceResponse()
        
        if should_end:
            response.say(
                response_text,
                voice="Polly.Aditi",
                language="en-IN"
            )
            response.hangup()

            await agent.end_call(CallSid)
        else:
            base_url = str(request.base_url).rstrip("/")
            
            gather = Gather(
                input='speech',
                action=f"{base_url}/api/v1/voice/gather",
                method='POST',
                language='en-IN',
                speech_timeout='auto',
                speech_model='phone_call',
                enhanced=True
            )
            
            gather.say(
                response_text,
                voice="Polly.Aditi",
                language="en-IN"
            )
            
            response.append(gather)

            response.say(
                "Are you still there?",
                voice="Polly.Aditi",
                language="en-IN"
            )
            response.redirect(f"{base_url}/api/v1/voice/gather")
        
        return Response(content=str(response), media_type="application/xml")
        
    except Exception as e:
        print(f"Error handling gather: {e}")
        import traceback
        traceback.print_exc()
        
        from twilio.twiml.voice_response import VoiceResponse
        response = VoiceResponse()
        response.say(
            "I apologize for the inconvenience. Please call back later.",
            voice="Polly.Aditi",
            language="en-IN"
        )
        response.hangup()
        
        return Response(content=str(response), media_type="application/xml")



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
        print(f"📊 Call status update: {CallSid} - {CallStatus}")

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
        
        return {
            "status": "healthy",
            "voice_agent_enabled": voice_config.VOICE_AGENT_ENABLED,
            "redis": "connected" if redis_ok else "disconnected",
            "twilio": "configured" if twilio_ok else "not configured",
            "openai": "configured" if openai_ok else "not configured",
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
