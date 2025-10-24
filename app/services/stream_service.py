import uuid
import json
import asyncio
import base64
import logging
from typing import Dict, Optional, Callable
from collections import OrderedDict
from fastapi import WebSocket

logger = logging.getLogger(__name__)

FRAME_MS = 20
SAMPLE_RATE = 8000
BYTES_PER_SAMPLE = 1  # mu-law 8-bit
FRAME_BYTES = int(SAMPLE_RATE * BYTES_PER_SAMPLE * FRAME_MS / 1000)  # 160

class StreamService:
    """
    Manages Twilio Media Stream with buffering, framing, pacing, and mark tracking.
    """
    def __init__(self, websocket: WebSocket):
        self.ws = websocket
        self.expected_audio_index: int = 0
        self.audio_buffer: Dict[int, str] = OrderedDict()
        self.stream_sid: str = ""
        self.mark_callbacks: Dict[str, Callable] = {}

        # Background streaming
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._sender_task: Optional[asyncio.Task] = None
        self._running = False

    def set_stream_sid(self, stream_sid: str) -> None:
        """Set the Twilio Stream SID"""
        self.stream_sid = stream_sid
        logger.info(f"StreamService -> Stream SID set: {stream_sid}")

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._sender_task = asyncio.create_task(self._frame_sender())
        logger.info("StreamService -> Background frame sender started")

    async def shutdown(self) -> None:
        self._running = False
        if self._sender_task:
            try:
                self._sender_task.cancel()
            except Exception:
                pass
        logger.info("StreamService -> Background frame sender stopped")

    async def buffer(self, index: Optional[int], audio_b64: str) -> None:
        """Buffer audio chunks and send them in order."""
        if index is None:
            await self._enqueue_audio(audio_b64)
        elif index == self.expected_audio_index:
            await self._enqueue_audio(audio_b64)
            self.expected_audio_index += 1
            while self.expected_audio_index in self.audio_buffer:
                buffered_audio = self.audio_buffer.pop(self.expected_audio_index)
                await self._enqueue_audio(buffered_audio)
                self.expected_audio_index += 1
        else:
            logger.debug(f"StreamService -> Buffering audio chunk {index}")
            self.audio_buffer[index] = audio_b64

    async def _enqueue_audio(self, audio_b64: str) -> None:
        """Decode base64 mu-law and enqueue raw bytes for streaming."""
        if not self.stream_sid:
            logger.error("StreamService -> Cannot send audio: stream_sid not set")
            return
        if not audio_b64:
            logger.error("StreamService -> Cannot send empty audio")
            return
        try:
            audio_bytes = base64.b64decode(audio_b64)
            await self._queue.put(audio_bytes)
            logger.info(f"StreamService -> Enqueued audio (~{len(audio_bytes)} bytes)")
        except Exception as e:
            logger.error(f"StreamService -> Enqueue error: {e}")
            raise

    async def clear(self) -> None:
        """Clear Twilio’s playback buffer to interrupt queued audio."""
        if not self.stream_sid:
            return
        try:
            clear_message = {
                "event": "clear",
                "streamSid": self.stream_sid,
            }
            await self.ws.send_text(json.dumps(clear_message))
            logger.info("StreamService -> Sent clear")
        except Exception as e:
            logger.error(f"StreamService -> Clear error: {e}")

    async def _frame_sender(self) -> None:
        """Background task: send ~20 ms mu-law frames and a trailing mark per utterance."""
        try:
            while self._running:
                # Wait for next utterance bytes
                utterance = await self._queue.get()
                if not utterance:
                    continue

                total = len(utterance)
                sent = 0
                chunk = 0
                while sent < total and self._running:
                    frame = utterance[sent: sent + FRAME_BYTES]
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
                    # Optional: add outbound track metadata if desired
                    # media_message["media"]["track"] = "outbound"
                    await self.ws.send_text(json.dumps(media_message))
                    sent += len(frame)
                    chunk += 1
                    await asyncio.sleep(FRAME_MS / 1000.0)

                logger.info(f"StreamService -> Sent audio frames (~{total} bytes total)")

                # Send trailing mark so app can detect end of playback
                try:
                    mark_label = str(uuid.uuid4())
                    mark_message = {
                        "event": "mark",
                        "streamSid": self.stream_sid,
                        "mark": {"name": mark_label},
                    }
                    await self.ws.send_text(json.dumps(mark_message))
                    logger.debug(f"StreamService -> Sent mark {mark_label}")
                except Exception as e:
                    logger.error(f"StreamService -> Mark send error: {e}")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"StreamService -> Frame sender crashed: {e}")
        finally:
            logger.info("StreamService -> Frame sender exiting")

    def reset(self) -> None:
        """Reset the stream service state"""
        self.expected_audio_index = 0
        self.audio_buffer.clear()
        self.mark_callbacks.clear()
        logger.info("StreamService -> State reset")
