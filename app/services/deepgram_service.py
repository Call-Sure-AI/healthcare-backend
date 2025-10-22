"""
Deepgram STT Service for real-time speech-to-text transcription.
Based on TypeScript DeepgramService implementation.
"""
import asyncio
import logging
from typing import Dict, Callable, Awaitable
from deepgram import (
    DeepgramClient
)
from app.config.voice_config import voice_config

logger = logging.getLogger(__name__)

# Type hint for the callback function
TranscriptCallback = Callable[[str], Awaitable[None]]


class DeepgramService:
    """
    Manages a single real-time transcription connection to Deepgram.
    An instance should be created for each concurrent call.
    """
    
    def __init__(self, on_speech_end_callback: TranscriptCallback):
        """
        Initialize Deepgram service.
        
        Args:
            on_speech_end_callback: Async function called when speech utterance ends
        """
        try:
            # Create client directly with API key (NO DeepgramClientOptions)
            self.client = DeepgramClient(voice_config.DEEPGRAM_API_KEY)
            self.dg_connection = None
            self._on_speech_end = on_speech_end_callback
            self.final_result = ""
            self.speech_final = False
            logger.info("DeepgramService -> ✓ Client created successfully")
        except Exception as e:
            logger.error(f"DeepgramService -> ❌ Failed to create client: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    async def connect(self) -> bool:
        """Establishes the WebSocket connection to Deepgram."""
        try:
            logger.info("DeepgramService -> Connecting to Deepgram...")
            
            # Create live transcription connection
            self.dg_connection = self.client.listen.asynclive.v("1")
            
            # Register event handlers
            self.dg_connection.on(LiveTranscriptionEvents.Open, self._on_open)
            self.dg_connection.on(LiveTranscriptionEvents.Transcript, self._on_message)
            self.dg_connection.on(LiveTranscriptionEvents.UtteranceEnd, self._on_utterance_end)
            self.dg_connection.on(LiveTranscriptionEvents.Error, self._on_error)
            self.dg_connection.on(LiveTranscriptionEvents.Close, self._on_close)
            
            logger.info("DeepgramService -> Event handlers registered")
            
            # Start connection with options
            options = LiveOptions(
                model="nova-2-phonecall",
                language="en-US",
                encoding="mulaw",
                sample_rate=8000,
                smart_format=True,
                interim_results=True,
                punctuate=True,
                endpointing=300,
                utterance_end_ms="1200",
                vad_events=True
            )
            
            logger.info("DeepgramService -> Starting connection with options...")
            result = await self.dg_connection.start(options)
            logger.info(f"DeepgramService -> ✓ Connection started successfully")
            return True
            
        except Exception as e:
            logger.error(f"DeepgramService -> ❌ Connection error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def send_audio(self, audio_chunk: bytes):
        """Forwards an audio chunk to Deepgram."""
        if self.dg_connection:
            try:
                await self.dg_connection.send(audio_chunk)
            except Exception as e:
                logger.error(f"DeepgramService -> Error sending audio: {e}")
    
    async def finish(self):
        """Closes the Deepgram connection."""
        if self.dg_connection:
            try:
                await self.dg_connection.finish()
                self.dg_connection = None
                logger.info("DeepgramService -> Connection finished")
            except Exception as e:
                logger.error(f"DeepgramService -> Error finishing connection: {e}")
    
    def _on_open(self, *args, **kwargs):
        """Called when connection opens"""
        logger.info("DeepgramService -> ✓✓✓ WebSocket connection OPENED ✓✓✓")
    
    def _on_message(self, *args, **kwargs):
        """Handles incoming transcript fragments from Deepgram."""
        try:
            result = kwargs.get('result')
            if not result:
                return
            
            # Get alternatives
            if hasattr(result, 'channel') and hasattr(result.channel, 'alternatives'):
                alternatives = result.channel.alternatives
            else:
                return
            
            if not alternatives or len(alternatives) == 0:
                return
            
            transcript = alternatives[0].transcript
            
            # Skip empty transcripts
            if not transcript or not transcript.strip():
                return
            
            # Log interim results for debugging
            if hasattr(result, 'is_final') and not result.is_final:
                logger.debug(f"DeepgramService -> Interim: '{transcript}'")
                return
            
            # Handle final transcripts
            if hasattr(result, 'is_final') and result.is_final:
                self.final_result += f" {transcript}"
                logger.info(f"DeepgramService -> Final fragment: '{transcript}'")
                
                # Check for speech_final
                if hasattr(result, 'speech_final') and result.speech_final:
                    self.speech_final = True
                    final_text = self.final_result.strip()
                    logger.info("=" * 80)
                    logger.info(f"🎤🎤🎤 SPEECH FINAL: '{final_text}'")
                    logger.info("=" * 80)
                    
                    # Trigger callback
                    asyncio.create_task(self._on_speech_end(final_text))
                    self.final_result = ""
                else:
                    self.speech_final = False
                    
        except Exception as e:
            logger.error(f"DeepgramService -> Error in _on_message: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_utterance_end(self, *args, **kwargs):
        """Fires when Deepgram detects the end of a spoken utterance."""
        logger.info("DeepgramService -> 🔔 Utterance End detected")
        
        # If we have a partial result and haven't seen speech_final, trigger callback
        if not self.speech_final and self.final_result.strip():
            final_text = self.final_result.strip()
            logger.info("=" * 80)
            logger.info(f"🎤🎤🎤 UTTERANCE END: '{final_text}'")
            logger.info("=" * 80)
            asyncio.create_task(self._on_speech_end(final_text))
            self.final_result = ""
    
    def _on_error(self, *args, **kwargs):
        """Handle errors"""
        error = kwargs.get('error')
        logger.error(f"DeepgramService -> ❌❌❌ ERROR: {error}")
    
    def _on_close(self, *args, **kwargs):
        """Called when connection closes"""
        logger.info("DeepgramService -> Connection closed")


class DeepgramManager:
    """
    Factory and manager for creating and handling multiple DeepgramService instances.
    Ensures each phone call gets its own isolated transcription service.
    """
    
    def __init__(self):
        self._connections: Dict[str, DeepgramService] = {}
        logger.info("DeepgramManager -> Manager initialized")
    
    def create_connection(
        self,
        call_sid: str,
        on_speech_end_callback: TranscriptCallback
    ) -> DeepgramService:
        """Creates a new DeepgramService instance for a specific call."""
        if call_sid in self._connections:
            logger.warning(f"DeepgramManager -> Connection for {call_sid} already exists. Overwriting.")
        
        logger.info(f"DeepgramManager -> Creating connection for call: {call_sid}")
        service = DeepgramService(on_speech_end_callback)
        self._connections[call_sid] = service
        logger.info(f"DeepgramManager -> ✓ Service created for {call_sid}")
        return service
    
    async def remove_connection(self, call_sid: str):
        """Closes and removes the DeepgramService instance for a specific call."""
        if call_sid in self._connections:
            logger.info(f"DeepgramManager -> Removing connection for call: {call_sid}")
            service = self._connections.pop(call_sid)
            await service.finish()
        else:
            logger.warning(f"DeepgramManager -> No connection found for {call_sid} to remove")
