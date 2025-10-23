import asyncio
import base64
import logging
from typing import Optional, AsyncIterator
from app.services.elevenlabs_service import elevenlabs_service

logger = logging.getLogger(__name__)


class TTSService:
    """
    Manages TTS generation using ElevenLabs.
    """
    
    def __init__(self):
        self.elevenlabs = elevenlabs_service
        logger.info("TTSService initialized with ElevenLabs")
    
    async def generate(
        self,
        text: str,
        partial_response_index: Optional[int] = None
    ) -> AsyncIterator[str]:
        """
        Generate audio from text using ElevenLabs.
        
        Args:
            text: Text to convert to speech
            partial_response_index: Optional index for tracking
            
        Yields:
            Base64 encoded mulaw/8000 audio chunks
        """
        if not text or not text.strip():
            return
        
        try:
            logger.info(f"TTS -> Generating audio for: '{text[:50]}...'")
            
            # Get audio from ElevenLabs
            async for audio_chunk in self.elevenlabs.generate_audio_stream(text):
                if audio_chunk:
                    # Encode to base64
                    audio_b64 = base64.b64encode(audio_chunk).decode('utf-8')
                    logger.info(f"TTS -> Success ({len(audio_chunk)} bytes, {len(audio_b64)} b64 chars)")
                    yield audio_b64
                    
        except Exception as e:
            logger.error(f"TTS -> Error: {e}")
            import traceback
            traceback.print_exc()
