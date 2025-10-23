import uuid
import json
import asyncio
from typing import Dict, Optional, Callable
from collections import OrderedDict
from fastapi import WebSocket
import logging

logger = logging.getLogger(__name__)


class StreamService:
    """
    Manages Twilio Media Stream with proper audio buffering and mark tracking.
    """
    
    def __init__(self, websocket: WebSocket):
        self.ws = websocket
        self.expected_audio_index: int = 0
        self.audio_buffer: Dict[int, str] = OrderedDict()
        self.stream_sid: str = ""
        self.mark_callbacks: Dict[str, Callable] = {}
    
    def set_stream_sid(self, stream_sid: str) -> None:
        """Set the Twilio Stream SID"""
        self.stream_sid = stream_sid
        logger.info(f"StreamService -> Stream SID set: {stream_sid}")
    
    async def buffer(self, index: Optional[int], audio: str) -> None:
        """Buffer audio chunks and send them in order."""
        if index is None:
            await self._send_audio(audio)
        elif index == self.expected_audio_index:
            await self._send_audio(audio)
            self.expected_audio_index += 1
            
            while self.expected_audio_index in self.audio_buffer:
                buffered_audio = self.audio_buffer.pop(self.expected_audio_index)
                await self._send_audio(buffered_audio)
                self.expected_audio_index += 1
        else:
            logger.debug(f"StreamService -> Buffering audio chunk {index}")
            self.audio_buffer[index] = audio
    
    async def _send_audio(self, audio: str) -> None:
        """Send audio to Twilio."""
        if not self.stream_sid:
            logger.error("StreamService -> Cannot send audio: stream_sid not set")
            return
        
        if not audio or len(audio) == 0:
            logger.error("StreamService -> Cannot send empty audio")
            return
        
        try:
            # ✅ FIXED: Proper JSON structure
            media_message = {
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {
                    "payload": audio
                }
            }
            
            await self.ws.send_text(json.dumps(media_message))
            logger.info(f"StreamService -> Sent audio ({len(audio)} chars)")
            
            # Send mark
            mark_label = str(uuid.uuid4())
            mark_message = {
                "event": "mark",
                "streamSid": self.stream_sid,
                "mark": {
                    "name": mark_label
                }
            }
            
            await self.ws.send_text(json.dumps(mark_message))
            
        except Exception as e:
            logger.error(f"StreamService -> Error sending audio: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def reset(self) -> None:
        """Reset the stream service state"""
        self.expected_audio_index = 0
        self.audio_buffer.clear()
        self.mark_callbacks.clear()
        logger.info("StreamService -> State reset")
