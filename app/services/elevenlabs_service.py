import os
import asyncio
import base64
import logging
from elevenlabs import ElevenLabs, Voice, VoiceSettings
from typing import Optional, AsyncGenerator
from app.config.voice_config import voice_config
import traceback
from app.services.tts_service import TTSService

logger = logging.getLogger(__name__)

client = ElevenLabs(api_key=voice_config.ELEVENLABS_API_KEY)
VOICE_ID = voice_config.ELEVENLABS_VOICE_ID
AUDIO_DIR = "static/audio"

class ElevenLabsService:
    def __init__(self):
        os.makedirs(AUDIO_DIR, exist_ok=True)
        logger.info("✓ ElevenLabs Service initialized")
    
    async def generate(
        self, 
        text: str, 
        partial_response_index: Optional[int] = None
    ) -> AsyncGenerator[str, None]:

        if not text or not text.strip():
            logger.warning("Empty text provided to ElevenLabs TTS")
            return
        
        logger.info(f"ElevenLabs TTS -> Generating audio for: '{text[:50]}...'")
        
        try:

            audio_generator = client.text_to_speech.stream(
                text=text,
                voice_id=VOICE_ID,
                model_id="eleven_turbo_v2_5",
                output_format="ulaw_8000",
                voice_settings=VoiceSettings(
                    stability=0.5,
                    similarity_boost=0.75,
                    style=0.0,
                    use_speaker_boost=True
                )
            )
            
            total_bytes = 0
            chunk_count = 0

            for chunk in audio_generator:
                if chunk:
                    audio_b64 = base64.b64encode(chunk).decode('ascii')
                    total_bytes += len(chunk)
                    chunk_count += 1
                    yield audio_b64
            
            logger.info(f"ElevenLabs TTS -> Success ({total_bytes} bytes, {chunk_count} chunks)")
            
        except Exception as e:
            logger.error(f"ElevenLabs TTS Error: {e}")
            traceback.print_exc()

            logger.warning("Falling back to Deepgram TTS")
            
            try:
                tts_fallback = TTSService()
                
                async for audio_b64 in tts_fallback.generate(text):
                    if audio_b64:
                        yield audio_b64
                        
                logger.info("Fallback TTS completed")
                
            except Exception as fallback_error:
                logger.error(f"Fallback TTS also failed: {fallback_error}")

# Elevenlabs global instance
elevenlabs_service = ElevenLabsService()
