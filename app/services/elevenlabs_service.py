import os
import asyncio
from elevenlabs.client import ElevenLabs
from elevenlabs import save
from app.config.voice_config import voice_config
from typing import Optional, AsyncGenerator
from datetime import datetime

client = ElevenLabs(api_key=voice_config.ELEVENLABS_API_KEY)
VOICE_ID = voice_config.ELEVENLABS_VOICE_ID
AUDIO_DIR = "static/audio"

class ElevenLabsService:
    
    def __init__(self):
        os.makedirs(AUDIO_DIR, exist_ok=True)
        print("ElevenLabs Service initialized. Audio directory ensured.")

    def _generate_audio_sync(self, text: str, file_path: str):
        """Synchronous function to generate and save audio."""
        try:
            audio = client.text_to_speech.convert(
                text=text,
                voice_id=VOICE_ID,
                model_id="eleven_multilingual_v2",
                output_format="mp3_44100_128" # Standard MP3 format for saving
            )
            save(audio, file_path)
            return True
        except Exception as e:
            print(f"Error generating ElevenLabs audio file: {e}")
            return False

    async def generate_and_save_audio(self, text: str, call_sid: str) -> Optional[str]:
        try:
            file_name = f"{call_sid}_{datetime.now().strftime('%Y%m%d%H%M%S')}.mp3"
            file_path = os.path.join(AUDIO_DIR, file_name)

            success = await asyncio.to_thread(self._generate_audio_sync, text, file_path)
            
            if success:
                return f"/static/audio/{file_name}"
            else:
                return None

        except Exception as e:
            print(f"Error in generate_and_save_audio: {e}")
            return None

    async def generate_audio_stream(self, text: str) -> AsyncGenerator[Optional[bytes], None]:
        """
        Calls ElevenLabs streaming endpoint and yields audio chunks (mulaw).
        """
        print("Starting ElevenLabs audio stream generation...")
        try:
            # Request mulaw output at 8000Hz for Twilio compatibility
            audio_stream = await client.text_to_speech.stream(
                text=text,
                voice_id=VOICE_ID,
                model_id="eleven_turbo_v2_5", # Turbo models are better for latency
                output_format="ulaw_8000" # Use mulaw (ulaw) for Twilio
            )

            # Yield chunks as they arrive
            async for chunk in audio_stream:
                if chunk:
                    yield chunk
            print("ElevenLabs audio stream finished.")

        except Exception as e:
            print(f"Error during ElevenLabs streaming: {e}")
            yield None

elevenlabs_service = ElevenLabsService()