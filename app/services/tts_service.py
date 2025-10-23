import asyncio
import base64
import logging
from typing import Optional, AsyncIterator
from collections import deque
import httpx
from app.config.voice_config import voice_config

logger = logging.getLogger(__name__)


class TTSService:
    """
    Manages TTS generation with rate limiting.
    Uses Deepgram REST API.
    """
    
    def __init__(self):
        self.request_queue = deque()
        self.is_processing = False
        self.last_request_time = 0
        self.min_request_interval = 0.2  # 200ms between requests
        self.consecutive_failures = 0
        self.max_consecutive_failures = 3

    async def generate(
        self,
        text: str,
        partial_response_index: Optional[int] = None
    ) -> AsyncIterator[str]:
        """
        Generate audio from text using Deepgram TTS REST API.
        
        Args:
            text: Text to convert to speech
            partial_response_index: Optional index for tracking
            
        Yields:
            Base64 encoded mulaw/8000 audio chunks
        """
        if not text or not text.strip():
            return

        # Check API key
        if not voice_config.DEEPGRAM_API_KEY:
            logger.error("TTS -> DEEPGRAM_API_KEY not configured")
            return

        try:
            logger.info(f"TTS -> Generating audio for: '{text[:50]}...'")
            
            url = "https://api.deepgram.com/v1/speak"
            params = {
                "model": "aura-stella-en",
                "encoding": "mulaw",
                "sample_rate": "8000",
                "container": "none"
            }
            
            headers = {
                "Authorization": f"Token {voice_config.DEEPGRAM_API_KEY}",
                "Content-Type": "application/json"
            }
            
            payload = {"text": text}
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    params=params,
                    headers=headers,
                    json=payload
                )
                
                if response.status_code == 200:
                    audio_bytes = response.content
                    audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
                    
                    logger.info(f"TTS -> Success ({len(audio_bytes)} bytes, {len(audio_b64)} b64 chars)")
                    
                    self.consecutive_failures = 0
                    yield audio_b64
                else:
                    logger.error(f"TTS -> HTTP {response.status_code}: {response.text}")
                    self.consecutive_failures += 1
                    
        except Exception as e:
            logger.error(f"TTS -> Error: {e}")
            self.consecutive_failures += 1
            import traceback
            traceback.print_exc()
