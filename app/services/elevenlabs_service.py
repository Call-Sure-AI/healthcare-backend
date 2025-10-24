import os
import asyncio
import base64
import logging
from elevenlabs.client import ElevenLabs
from elevenlabs import save
from app.config.voice_config import voice_config
from typing import Optional, AsyncGenerator

logger = logging.getLogger(__name__)

client = ElevenLabs(api_key=voice_config.ELEVENLABS_API_KEY)
VOICE_ID = voice_config.ELEVENLABS_VOICE_ID
AUDIO_DIR = "static/audio"

class ElevenLabsService:
    def __init__(self):
        os.makedirs(AUDIO_DIR, exist_ok=True)
        logger.info("✓ ElevenLabs Service initialized")
    
    def _generate_audio_sync(self, text: str, file_path: str):
        """Synchronous function to generate and save audio."""
        try:
            audio = client.text_to_speech.convert(
                text=text,
                voice_id=VOICE_ID,
                model_id="eleven_multilingual_v2",
                output_format="mp3_44100_128"
            )
            
            save(audio, file_path)
            return True
        except Exception as e:
            logger.error(f"❌ Error generating ElevenLabs audio file: {e}")
            return False
    
    async def generate_and_save_audio(self, text: str, call_sid: str) -> Optional[str]:
        """Generate and save audio file (for non-streaming use)"""
        try:
            from datetime import datetime
            file_name = f"{call_sid}_{datetime.now().strftime('%Y%m%d%H%M%S')}.mp3"
            file_path = os.path.join(AUDIO_DIR, file_name)
            success = await asyncio.to_thread(self._generate_audio_sync, text, file_path)
            
            if success:
                return f"/static/audio/{file_name}"
            else:
                return None
        except Exception as e:
            logger.error(f"❌ Error in generate_and_save_audio: {e}")
            return None
    
    async def generate(self, text: str, partial_response_index: Optional[int] = None) -> AsyncGenerator[str, None]:
        """
        Generate audio stream for Twilio (base64-encoded mulaw).
        Compatible with TTSService interface.
        
        Args:
            text: Text to convert to speech
            partial_response_index: Optional index for tracking
            
        Yields:
            Base64-encoded mulaw/8000 audio chunks
        """
        if not text or not text.strip():
            logger.warning("⚠️  Empty text provided to ElevenLabs TTS")
            return
        
        logger.info(f"🎙️ ElevenLabs TTS -> Generating audio for: '{text[:50]}...'")
        
        try:
            # Request streaming audio in mulaw format for Twilio
            audio_stream = client.text_to_speech.convert_as_stream(
                text=text,
                voice_id=VOICE_ID,
                model_id="eleven_turbo_v2_5",  # Turbo for low latency
                output_format="ulaw_8000"  # 8kHz mulaw for Twilio
            )
            
            total_bytes = 0
            chunk_count = 0
            
            # Stream chunks
            for chunk in audio_stream:
                if chunk:
                    # ElevenLabs returns raw bytes, encode to base64
                    audio_b64 = base64.b64encode(chunk).decode('ascii')
                    total_bytes += len(chunk)
                    chunk_count += 1
                    yield audio_b64
            
            logger.info(f"✓ ElevenLabs TTS -> Success ({total_bytes} bytes, {chunk_count} chunks)")
            
        except Exception as e:
            logger.error(f"❌ ElevenLabs TTS Error: {e}")
            import traceback
            traceback.print_exc()
            
            # Don't yield anything on error - this will trigger fallback
            return

# Create singleton instance
elevenlabs_service = ElevenLabsService()
