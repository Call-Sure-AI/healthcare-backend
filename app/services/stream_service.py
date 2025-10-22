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
    Ensures audio chunks are sent in order and tracks playback completion.
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
        """
        Buffer audio chunks and send them in order.
        
        Args:
            index: Sequence number (None for immediate playback like greeting)
            audio: Base64 encoded mulaw/8000 audio
        """
        # Escape hatch for intro message - send immediately
        if index is None:
            await self._send_audio(audio)
        elif index == self.expected_audio_index:
            # This is the chunk we're waiting for
            await self._send_audio(audio)
            self.expected_audio_index += 1
            
            # Check if we have buffered subsequent chunks
            while self.expected_audio_index in self.audio_buffer:
                buffered_audio = self.audio_buffer.pop(self.expected_audio_index)
                await self._send_audio(buffered_audio)
                self.expected_audio_index += 1
        else:
            # Out of order - buffer it
            logger.debug(f"StreamService -> Buffering audio chunk {index} (expecting {self.expected_audio_index})")
            self.audio_buffer[index] = audio
    
    async def _send_audio(self, audio: str) -> None:
        """
        Send audio to Twilio and attach a mark event for playback tracking.
        
        Args:
            audio: Base64 encoded mulaw/8000 audio
        """
        if not self.stream_sid:
            logger.error("StreamService -> Cannot send audio: stream_sid not set")
            return
        
        try:
            # Send media message
            await self.ws.send_text(json.dumps({
                "streamSid": self.stream_sid,
                "event": "media",
                "media": {
                    "payload": audio
                }
            }))
            
            # Send mark message to track when this audio completes
            mark_label = str(uuid.uuid4())
            await self.ws.send_text(json.dumps({
                "streamSid": self.stream_sid,
                "event": "mark",
                "mark": {
                    "name": mark_label
                }
            }))
            
            logger.debug(f"StreamService -> Sent audio chunk with mark: {mark_label}")
            
        except Exception as e:
            logger.error(f"StreamService -> Error sending audio: {e}")
            raise
    
    def reset(self) -> None:
        """Reset the stream service state"""
        self.expected_audio_index = 0
        self.audio_buffer.clear()
        self.mark_callbacks.clear()
        logger.info("StreamService -> State reset")
