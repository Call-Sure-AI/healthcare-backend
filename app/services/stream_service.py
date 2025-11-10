# app/services/stream_service.py - OPTIMIZED VERSION

import uuid
import json
import base64
import logging
from fastapi import WebSocket
import time
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)

FRAME_MS = 20
SAMPLE_RATE = 8000
BYTES_PER_SAMPLE = 1
FRAME_BYTES = int(SAMPLE_RATE * BYTES_PER_SAMPLE * FRAME_MS / 1000)

class StreamService:
    def __init__(self, websocket: WebSocket):
        self.ws = websocket
        self.stream_sid: str = ""
        self.last_mark: str = ""

    def set_stream_sid(self, stream_sid: str) -> None:
        self.stream_sid = stream_sid
        logger.info(f"Stream SID: {stream_sid}")

    async def clear(self) -> None:
        """Clear Twilio's audio buffer"""
        if not self.stream_sid:
            return
        
        msg = {
            "event": "clear",
            "streamSid": self.stream_sid
        }
        await self.ws.send_text(json.dumps(msg))

    async def send_audio_chunk(self, audio_b64: str) -> None:
        """
        ⚡ OPTIMIZED: Send single audio chunk immediately
        No buffering, no combining - pure streaming
        """
        if not self.stream_sid or not audio_b64:
            return
        
        try:
            audio_bytes = base64.b64decode(audio_b64)
            sent = 0
            total = len(audio_bytes)
            
            # Send in 20ms frames for Twilio
            while sent < total:
                frame = audio_bytes[sent: sent + FRAME_BYTES]
                if not frame:
                    break
                
                payload = base64.b64encode(frame).decode("ascii")
                media_message = {
                    "event": "media",
                    "streamSid": self.stream_sid,
                    "media": {"payload": payload}
                }
                
                await self.ws.send_text(json.dumps(media_message))
                sent += len(frame)
            
        except Exception as e:
            logger.error(f"Error sending chunk: {e}")
            raise

    async def send_mark(self, mark_name: str = None) -> str:
        """Send a mark event to track playback completion"""
        if not self.stream_sid:
            return ""
        
        mark_label = mark_name or str(uuid.uuid4())
        mark_message = {
            "event": "mark",
            "streamSid": self.stream_sid,
            "mark": {"name": mark_label}
        }
        
        await self.ws.send_text(json.dumps(mark_message))
        self.last_mark = mark_label
        return mark_label