import uuid
import json
import asyncio
import base64
import logging
from typing import Dict, Optional, Callable
from collections import OrderedDict
from fastapi import WebSocket
import time
from starlette.websockets import WebSocketState
import traceback

logger = logging.getLogger(__name__)

FRAME_MS = 20
SAMPLE_RATE = 8000
BYTES_PER_SAMPLE = 1
FRAME_BYTES = int(SAMPLE_RATE * BYTES_PER_SAMPLE * FRAME_MS / 1000)

class StreamService:
    def __init__(self, websocket: WebSocket):
        self.ws = websocket
        self.expected_audio_index: int = 0
        self.audio_buffer: Dict[int, str] = OrderedDict()
        self.stream_sid: str = ""
        self.mark_callbacks: Dict[str, Callable] = {}

    def set_stream_sid(self, stream_sid: str) -> None:
        self.stream_sid = stream_sid
        logger.info(f"StreamService -> Stream SID set: {stream_sid}")

    async def clear(self) -> None:
        if not self.stream_sid:
            return
        msg = {
            "event": "clear",
            "streamSid": self.stream_sid
        }
        await self.ws.send_text(json.dumps(msg))
        logger.info("StreamService -> Sent clear")

    async def _send_audio(self, audio_b64: str) -> None:
        if not self.stream_sid:
            logger.error("StreamService -> Cannot send audio: streamSid not set")
            return
        
        if not audio_b64:
            logger.error("StreamService -> Cannot send empty audio")
            return
        
        try:
            audio_bytes = base64.b64decode(audio_b64)
            total = len(audio_bytes)

            audio_duration_sec = total / SAMPLE_RATE
            
            logger.info(f"StreamService -> Starting audio playback:")
            logger.info(f"   📊 Size: {total} bytes")
            logger.info(f"   ⏱️  Duration: ~{audio_duration_sec:.2f}s")
            
            start_time = time.time()
            sent = 0
            frames_sent = 0

            while sent < total:
                if frames_sent % 100 == 0 and frames_sent > 0:
                    if self.ws.client_state != WebSocketState.CONNECTED:
                        logger.warning(f"WebSocket disconnected (after {frames_sent} frames)")
                        break
                
                frame = audio_bytes[sent: sent + FRAME_BYTES]
                if not frame:
                    break
                
                payload = base64.b64encode(frame).decode("ascii")
                media_message = {
                    "event": "media",
                    "streamSid": self.stream_sid,
                    "media": {
                        "payload": payload
                    }
                }
                
                await self.ws.send_text(json.dumps(media_message))
                sent += len(frame)
                frames_sent += 1

            
            elapsed_time = time.time() - start_time
            
            logger.info(f"StreamService -> Audio sent:")
            logger.info(f"Frames: {frames_sent}")
            logger.info(f"Bytes: {sent}/{total}")
            logger.info(f"Time: {elapsed_time:.2f}s")

            mark_label = str(uuid.uuid4())
            mark_message = {
                "event": "mark",
                "streamSid": self.stream_sid,
                "mark": {"name": mark_label},
            }
            
            await self.ws.send_text(json.dumps(mark_message))
            
            logger.info(f"Audio sent ({frames_sent} frames, {sent} bytes)")
            
        except Exception as e:
            logger.error(f"StreamService -> Error sending audio: {e}")
            traceback.print_exc()
            raise


