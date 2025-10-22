"""
Deepgram STT Service for real-time speech-to-text transcription.
Matches TypeScript implementation exactly.
"""
import asyncio
import base64
import logging
from typing import Callable, Awaitable, Dict
from deepgram import DeepgramClient
from app.config.voice_config import voice_config

logger = logging.getLogger(__name__)

# Type hint for the callback function
TranscriptCallback = Callable[[str], Awaitable[None]]


class DeepgramService:
    """Manages a single real-time transcription connection to Deepgram."""
    
    def __init__(self, on_speech_end_callback: TranscriptCallback):
        """Initialize Deepgram service."""
        self.dg_connection = None
        self.final_result = ""
        self.speech_final = False
        self._on_speech_end = on_speech_end_callback
        
        self.config = {
            'model': 'nova-2-phonecall',
            'encoding': 'mulaw',
            'sample_rate': 8000,
            'punctuate': True,
            'interim_results': True,
            'endpointing': 200,
            'utterance_end_ms': 1000
        }
        
        logger.info("DeepgramService -> Initializing...")
        self._initialize_connection()
    
    def _initialize_connection(self):
        """Initialize the Deepgram connection."""
        if not voice_config.DEEPGRAM_API_KEY:
            logger.error("DeepgramService -> DEEPGRAM_API_KEY not set")
            return
        
        try:
            logger.info("DeepgramService -> Creating client...")
            deepgram = DeepgramClient(voice_config.DEEPGRAM_API_KEY)
            self.dg_connection = deepgram.listen.live.v("1")
            logger.info("DeepgramService -> ✓ Client created")
        except Exception as e:
            logger.error(f"DeepgramService -> Failed to create client: {e}")
            import traceback
            traceback.print_exc()
    
    async def connect(self) -> bool:
        """Start the Deepgram connection."""
        if not self.dg_connection:
            logger.error("DeepgramService -> No connection to start")
            return False
        
        try:
            logger.info("DeepgramService -> Setting up event handlers...")
            
            # Setup event handlers
            self.dg_connection.on("Open", self._on_open)
            self.dg_connection.on("Transcript", self._on_transcript)
            self.dg_connection.on("Error", self._on_error)
            self.dg_connection.on("Close", self._on_close)
            
            logger.info("DeepgramService -> Starting connection...")
            
            # Start with options
            options = {
                'model': self.config['model'],
                'encoding': self.config['encoding'],
                'sample_rate': self.config['sample_rate'],
                'punctuate': self.config['punctuate'],
                'interim_results': self.config['interim_results'],
                'endpointing': self.config['endpointing'],
                'utterance_end_ms': str(self.config['utterance_end_ms'])
            }
            
            await self.dg_connection.start(options)
            logger.info("DeepgramService -> ✓✓✓ Connected successfully!")
            return True
            
        except Exception as e:
            logger.error(f"DeepgramService -> Connection error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _on_open(self, *args, **kwargs):
        """Called when connection opens"""
        logger.info("DeepgramService -> ✓✓✓ WEBSOCKET OPENED ✓✓✓")
    
    def _on_transcript(self, *args, **kwargs):
        """Handle incoming transcription events."""
        try:
            transcription = kwargs.get('result') or (args[0] if args else None)
            if not transcription:
                return
            
            # Get alternatives
            alternatives = None
            if hasattr(transcription, 'channel') and hasattr(transcription.channel, 'alternatives'):
                alternatives = transcription.channel.alternatives
            
            text = ''
            if alternatives and len(alternatives) > 0:
                text = alternatives[0].transcript or ''
            
            # Handle UtteranceEnd
            if hasattr(transcription, 'type') and transcription.type == 'UtteranceEnd':
                if not self.speech_final and self.final_result.strip():
                    logger.info(f"DeepgramService -> UtteranceEnd: '{self.final_result.strip()}'")
                    asyncio.create_task(self._on_speech_end(self.final_result.strip()))
                    self.final_result = ""
                return
            
            # Handle final transcripts
            is_final = getattr(transcription, 'is_final', False)
            
            if is_final and text.strip():
                self.final_result += f" {text}"
                logger.info(f"DeepgramService -> Final: '{text}'")
                
                # Check for speech_final
                speech_final = getattr(transcription, 'speech_final', False)
                
                if speech_final:
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
            else:
                # Interim result
                if text.strip():
                    logger.debug(f"DeepgramService -> Interim: '{text}'")
                    
        except Exception as e:
            logger.error(f"DeepgramService -> Error in transcript: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_error(self, *args, **kwargs):
        """Handle errors"""
        error = kwargs.get('error') or (args[0] if args else 'Unknown')
        logger.error(f"DeepgramService -> ❌ ERROR: {error}")
    
    def _on_close(self, *args, **kwargs):
        """Called when connection closes"""
        logger.info("DeepgramService -> Connection closed")
    
    async def send_audio(self, audio_chunk: bytes):
        """Send audio bytes to Deepgram."""
        if self.dg_connection:
            try:
                await self.dg_connection.send(audio_chunk)
            except Exception as e:
                logger.error(f"DeepgramService -> Error sending audio: {e}")
    
    def send(self, payload: str):
        """Send base64 encoded audio to Deepgram."""
        if self.dg_connection:
            try:
                # Decode base64 to bytes
                audio_bytes = base64.b64decode(payload)
                # Send to Deepgram
                asyncio.create_task(self.send_audio(audio_bytes))
            except Exception as e:
                logger.error(f"DeepgramService -> Error in send: {e}")
    
    async def close(self):
        """Close the Deepgram connection"""
        if self.dg_connection:
            try:
                await self.dg_connection.finish()
                self.dg_connection = None
                logger.info("DeepgramService -> Connection closed")
            except Exception as e:
                logger.error(f"DeepgramService -> Error closing: {e}")
    
    def is_ready(self) -> bool:
        """Check if connection is ready"""
        return self.dg_connection is not None


class DeepgramManager:
    """Manager for multiple DeepgramService instances."""
    
    def __init__(self):
        self._connections: Dict[str, DeepgramService] = {}
        logger.info("DeepgramManager -> Manager initialized")
    
    def create_connection(
        self,
        call_sid: str,
        on_speech_end_callback: TranscriptCallback  # CORRECT PARAMETER NAME
    ) -> DeepgramService:
        """Creates a new DeepgramService instance."""
        if call_sid in self._connections:
            logger.warning(f"DeepgramManager -> Overwriting: {call_sid}")
        
        logger.info(f"DeepgramManager -> Creating connection: {call_sid}")
        service = DeepgramService(on_speech_end_callback)
        self._connections[call_sid] = service
        logger.info(f"DeepgramManager -> ✓ Created for {call_sid}")
        return service
    
    async def remove_connection(self, call_sid: str):
        """Closes and removes the DeepgramService instance."""
        if call_sid in self._connections:
            logger.info(f"DeepgramManager -> Removing: {call_sid}")
            service = self._connections.pop(call_sid)
            await service.close()
        else:
            logger.warning(f"DeepgramManager -> Not found: {call_sid}")
