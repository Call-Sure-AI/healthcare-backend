import os
import asyncio
import base64
import logging
from elevenlabs import ElevenLabs, Voice, VoiceSettings
from typing import Optional, AsyncGenerator
from app.config.voice_config import voice_config

logger = logging.getLogger(__name__)

# Initialize ElevenLabs client
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
            # ============ FIX: Use correct streaming method ============
            # ElevenLabs SDK expects stream() method, not convert_as_stream()
            audio_generator = client.text_to_speech.stream(
                text=text,
                voice_id=VOICE_ID,
                model_id="eleven_turbo_v2_5",  # Fastest model for real-time
                output_format="ulaw_8000",  # 8kHz mulaw for Twilio
                voice_settings=VoiceSettings(
                    stability=0.5,
                    similarity_boost=0.75,
                    style=0.0,
                    use_speaker_boost=True
                )
            )
            
            total_bytes = 0
            chunk_count = 0
            
            # Convert async generator to sync for ElevenLabs
            for chunk in audio_generator:
                if chunk:
                    # Encode to base64 for Twilio
                    audio_b64 = base64.b64encode(chunk).decode('ascii')
                    total_bytes += len(chunk)
                    chunk_count += 1
                    yield audio_b64
            
            logger.info(f"✓ ElevenLabs TTS -> Success ({total_bytes} bytes, {chunk_count} chunks)")
            
        except Exception as e:
            logger.error(f"❌ ElevenLabs TTS Error: {e}")
            import traceback
            traceback.print_exc()
            
            # Fallback: Generate with Deepgram if ElevenLabs fails
            logger.warning("⚠️  Falling back to Deepgram TTS")
            
            try:
                from app.services.tts_service import TTSService
                tts_fallback = TTSService()
                
                async for audio_b64 in tts_fallback.generate(text):
                    if audio_b64:
                        yield audio_b64
                        
                logger.info("✓ Fallback TTS completed")
                
            except Exception as fallback_error:
                logger.error(f"❌ Fallback TTS also failed: {fallback_error}")
                # Don't yield anything - will trigger error message

# Create singleton instance
elevenlabs_service = ElevenLabsService()
