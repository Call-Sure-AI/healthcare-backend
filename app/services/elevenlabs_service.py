# app/services/elevenlabs_service.py - OPTIMIZED VERSION

import os
import asyncio
import base64
import logging
from elevenlabs import ElevenLabs, Voice, VoiceSettings
from typing import Optional, AsyncGenerator
from app.config.voice_config import voice_config
import traceback
from app.services.tts_service import TTSService
import time

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
        """
        ⚡ OPTIMIZED: Async generator that yields chunks immediately
        """
        if not text or not text.strip():
            logger.warning("Empty text provided to ElevenLabs TTS")
            return
        
        logger.info(f"🎤 ElevenLabs TTS starting: '{text[:50]}...'")
        start_time = time.time()
        
        try:
            # Run synchronous generator in thread pool
            loop = asyncio.get_event_loop()
            
            # Create generator
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
            first_chunk_time = None

            # ⚡ CRITICAL: Iterate synchronous generator in non-blocking way
            def get_next_chunk():
                try:
                    return next(audio_generator)
                except StopIteration:
                    return None
            
            while True:
                # Run blocking operation in executor
                chunk = await loop.run_in_executor(None, get_next_chunk)
                
                if chunk is None:
                    break
                
                if chunk:
                    # Track first chunk latency
                    if chunk_count == 0:
                        first_chunk_time = time.time() - start_time
                        logger.info(f"⚡ First TTS chunk: {first_chunk_time*1000:.0f}ms")
                    
                    audio_b64 = base64.b64encode(chunk).decode('ascii')
                    total_bytes += len(chunk)
                    chunk_count += 1
                    
                    # Yield immediately - DON'T BUFFER
                    yield audio_b64
            
            total_time = time.time() - start_time
            logger.info(f"✓ ElevenLabs complete: {chunk_count} chunks, {total_bytes} bytes in {total_time:.2f}s")
            
        except Exception as e:
            logger.error(f"❌ ElevenLabs error: {e}")
            traceback.print_exc()

            logger.warning("🔄 Falling back to Deepgram TTS")
            
            try:
                tts_fallback = TTSService()
                
                async for audio_b64 in tts_fallback.generate(text):
                    if audio_b64:
                        yield audio_b64
                        
                logger.info("✓ Fallback TTS completed")
                
            except Exception as fallback_error:
                logger.error(f"❌ Fallback TTS failed: {fallback_error}")


# Global instance
elevenlabs_service = ElevenLabsService()
