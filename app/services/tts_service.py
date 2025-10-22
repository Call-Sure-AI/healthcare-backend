import asyncio
import base64
import logging
from typing import Optional, Dict, Any, AsyncIterator
from collections import deque
import httpx
from app.config.voice_config import voice_config

logger = logging.getLogger(__name__)


class TTSService:
    """
    Manages TTS generation with rate limiting and fallback support.
    Uses Deepgram REST API primarily.
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
            logger.error("TTS -> DEEPGRAM_API_KEY not set")
            return
        
        # Check consecutive failures
        if self.consecutive_failures >= self.max_consecutive_failures:
            logger.error("TTS -> Too many consecutive failures")
            return
        
        try:
            # Rate limiting
            time_since_last = asyncio.get_event_loop().time() - self.last_request_time
            if time_since_last < self.min_request_interval:
                await asyncio.sleep(self.min_request_interval - time_since_last)
            
            # Call Deepgram TTS API
            voice_model = voice_config.VOICE_MODEL or "aura-stella-en"
            url = f"https://api.deepgram.com/v1/speak?model={voice_model}&encoding=mulaw&sample_rate=8000&container=none"
            
            logger.info(f"TTS -> Generating audio for: {text[:50]}...")
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Token {voice_config.DEEPGRAM_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={"text": text}
                )
                
                if response.status_code == 200:
                    # Get audio bytes
                    audio_bytes = response.content
                    
                    # Convert to base64
                    audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
                    
                    logger.info(f"TTS -> Success ({len(audio_bytes)} bytes)")
                    self.consecutive_failures = 0
                    self.last_request_time = asyncio.get_event_loop().time()
                    
                    yield audio_b64
                    
                elif response.status_code == 429:
                    logger.warning("TTS -> Rate limited (429)")
                    self.consecutive_failures += 1
                    
                else:
                    logger.error(f"TTS -> Failed with status {response.status_code}")
                    error_text = response.text
                    logger.error(f"TTS -> Error details: {error_text}")
                    self.consecutive_failures += 1
                    
        except asyncio.TimeoutError:
            logger.error("TTS -> Request timeout")
            self.consecutive_failures += 1
            
        except Exception as e:
            logger.error(f"TTS -> Error: {e}")
            self.consecutive_failures += 1
