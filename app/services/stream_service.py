import uuid
import json
import asyncio
import base64
import logging
from fastapi import WebSocket
from typing import Dict, Optional, Callable
from collections import OrderedDict

logger = logging.getLogger(__name__)

FRAME_MS = 20
SAMPLE_RATE = 8000
BYTES_PER_SAMPLE = 1  # mu-law is 8-bit
FRAME_BYTES = int(SAMPLE_RATE * BYTES_PER_SAMPLE * FRAME_MS / 1000)  # 160

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

    async def buffer(self, index: Optional[int], audio_b64: str) -> None:
        if index is None:
            await self.send_audio(audio_b64)
        elif index == self.expected_audio_index:
            await self.send_audio(audio_b64)
            self.expected_audio_index += 1
            while self.expected_audio_index in self.audio_buffer:
                buffered_audio = self.audio_buffer.pop(self.expected_audio_index)
                await self.send_audio(buffered_audio)
                self.expected_audio_index += 1
        else:
            logger.debug(f"StreamService -> Buffering audio chunk index={index}")
            self.audio_buffer[index] = audio_b64

    async def send_audio(self, audio_b64: str) -> None:
        if not self.stream_sid:
            logger.error("StreamService -> Cannot send audio: streamSid not set")
            return
        if not audio_b64:
            logger.error("StreamService -> Cannot send empty audio")
            return

        try:
            # 1) Decode the whole utterance
            audio_bytes = base64.b64decode(audio_b64)

            # 2) Stream as 20 ms mu-law frames
            total = len(audio_bytes)
            sent = 0
            while sent < total:
                frame = audio_bytes[sent: sent + FRAME_BYTES]
                if not frame:
                    break
                payload = base64.b64encode(frame).decode("ascii")
                media_message = {
                    "event": "media",
                    "streamSid": self.stream_sid,
                    "media": {"payload": payload},
                }
                await self.ws.send_text(json.dumps(media_message))
                sent += len(frame)

                # Real-time pacing (~20 ms per frame)
                await asyncio.sleep(FRAME_MS / 1000.0)

            logger.info(f"StreamService -> Sent audio frames (~{total} bytes total)")

            # 3) Optional: send a mark so the app knows when Twilio finished playback
            mark_label = str(uuid.uuid4())
            mark_message = {
                "event": "mark",
                "streamSid": self.stream_sid,
                "mark": {"name": mark_label},
            }
            await self.ws.send_text(json.dumps(mark_message))

        except Exception as e:
            logger.error(f"StreamService -> Error sending audio: {e}")
            import traceback; traceback.print_exc()
            raise
