"""
Deepgram STT Service for real-time speech-to-text transcription.
Matches the TypeScript DeepgramService implementation exactly.
"""
import asyncio
import base64
import logging
from typing import Callable, Awaitable, Optional, Dict, Any
from deepgram import DeepgramClient
from app.config.voice_config import voice_config

logger = logging.getLogger(__name__)

# Type hint for the callback function
TranscriptCallback = Callable[[str], Awaitable[None]]


class DeepgramService:
    """
    Manages a single real-time transcription connection to Deepgram.
    Emits 'transcription' event when speech is complete.
    """
    
    def __init__(self, on_transcription_callback: TranscriptCallback):
        """
        Initialize Deepgram service and connection.
        
        Args:
            on_transcription_callback: Async function called when transcription is complete
        """
        self.dg_connection = None
        self.final_result = ""
        self.speech_final = False  # Track if we've seen speech_final=true
        self._on_transcription = on_transcription_callback
        
        # Configuration matching TypeScript
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
        """Initialize the Deepgram connection (called in constructor)"""
        # Check API key
        if not voice_config.DEEPGRAM_API_KEY:
            logger.error("DeepgramService -> DEEPGRAM_API_KEY is not set")
            return
        
        try:
            # Create client
            logger.info("DeepgramService -> Creating Deepgram client...")
            deepgram = DeepgramClient(voice_config.DEEPGRAM_API_KEY)
            
            # Create live transcription connection
            self.dg_connection = deepgram.listen.live.v("1")
            
            logger.info("DeepgramService -> Deepgram client created successfully")
            
        except Exception as e:
            logger.error(f"DeepgramService -> Failed to create Deepgram client: {e}")
            import traceback
            traceback.print_exc()
            return
    
    async def connect(self) -> bool:
        """
        Start the Deepgram connection with configuration and setup event handlers.
        """
        if not self.dg_connection:
            logger.error("DeepgramService -> No connection to start")
            return False
        
        try:
            logger.info("DeepgramService -> Setting up event handlers...")
            
            # Setup event handlers BEFORE starting connection
            self.dg_connection.on("Open", self._on_open)
            self.dg_connection.on("Transcript", self._on_transcript)
            self.dg_connection.on("Error", self._on_error)
            self.dg_connection.on("Metadata", self._on_metadata)
            self.dg_connection.on("Close", self._on_close)
            
            logger.info("DeepgramService -> Starting connection with options...")
            
            # Start connection with options
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
            
            logger.info("DeepgramService -> ✓✓✓ Connection started successfully")
            return True
            
        except Exception as e:
            logger.error(f"DeepgramService -> Connection error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _on_open(self, *args, **kwargs):
        """Called when Deepgram WebSocket connection opens"""
        logger.info("DeepgramService -> ✓✓✓ Deepgram WebSocket connection OPENED ✓✓✓")
    
    def _on_transcript(self, *args, **kwargs):
        """
        Handle incoming transcription events from Deepgram.
        Matches TypeScript logic exactly.
        """
        try:
            # Get the transcription event
            transcription_event = kwargs.get('result') or (args[0] if args else None)
            
            if not transcription_event:
                return
            
            # Get alternatives
            alternatives = None
            if hasattr(transcription_event, 'channel') and hasattr(transcription_event.channel, 'alternatives'):
                alternatives = transcription_event.channel.alternatives
            
            text = ''
            if alternatives and len(alternatives) > 0:
                text = alternatives[0].transcript or ''
            
            # Handle UtteranceEnd event
            if hasattr(transcription_event, 'type') and transcription_event.type == 'UtteranceEnd':
                if not self.speech_final:
                    logger.warning(f"DeepgramService -> UtteranceEnd received before speechFinal, emit: '{self.final_result}'")
                    if self.final_result.strip():
                        asyncio.create_task(self._on_transcription(self.final_result.strip()))
                        self.final_result = ""
                    return
                else:
                    logger.info("DeepgramService -> Speech was already final when UtteranceEnd received")
                    return
            
            # Handle final transcriptions
            is_final = getattr(transcription_event, 'is_final', False)
            
            if is_final and text.strip():
                self.final_result += f" {text}"
                logger.info(f"DeepgramService -> Final chunk: '{text}'")
                
                # Check for speech_final
                speech_final = getattr(transcription_event, 'speech_final', False)
                
                if speech_final:
                    self.speech_final = True
                    final_text = self.final_result.strip()
                    logger.info("=" * 80)
                    logger.info(f"🎤🎤🎤 SPEECH FINAL: '{final_text}'")
                    logger.info("=" * 80)
                    
                    # Emit transcription
                    asyncio.create_task(self._on_transcription(final_text))
                    self.final_result = ""
                else:
                    # Reset speech_final to allow subsequent utteranceEnd messages
                    self.speech_final = False
            else:
                # Interim result (not final)
                if text.strip():
                    logger.debug(f"DeepgramService -> Interim: '{text}'")
                    
        except Exception as e:
            logger.error(f"DeepgramService -> Error in _on_transcript: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_error(self, *args, **kwargs):
        """Handle Deepgram errors"""
        error = kwargs.get('error') or (args[0] if args else 'Unknown error')
        logger.error(f"DeepgramService -> ❌ Deepgram error: {error}")
    
    def _on_metadata(self, *args, **kwargs):
        """Handle Deepgram metadata"""
        metadata = kwargs.get('metadata') or (args[0] if args else None)
        logger.debug(f"DeepgramService -> Metadata: {metadata}")
    
    def _on_close(self, *args, **kwargs):
        """Called when Deepgram connection closes"""
        logger.info("DeepgramService -> Deepgram connection closed")
    
    async def send_audio(self, audio_chunk: bytes):
        """
        Send audio payload to Deepgram.
        
        Args:
            audio_chunk: Raw audio bytes (mulaw/8000)
        """
        if self.dg_connection:
            try:
                # Check if connection is ready (equivalent to getReadyState() === 1)
                await self.dg_connection.send(audio_chunk)
            except Exception as e:
                logger.error(f"DeepgramService -> Error sending audio: {e}")
    
    def send(self, payload: str):
        """
        Send base64 encoded audio payload to Deepgram (synchronous version).
        
        Args:
            payload: Base64 encoded mulaw/8000 audio
        """
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
                logger.error(f"DeepgramService -> Error closing connection: {e}")
    
    def is_ready(self) -> bool:
        """Check if the connection is ready"""
        return self.dg_connection is not None


class DeepgramManager:
    """
    Factory and manager for creating and handling multiple DeepgramService instances.
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
            await service.close()
        else:
            logger.warning(f"DeepgramManager -> No connection found for {call_sid} to remove")
