import asyncio
import base64
import logging
import os
from typing import Callable, Awaitable, Dict

logger = logging.getLogger(__name__)

TranscriptCallback = Callable[[str], Awaitable[None]]


class DeepgramService:
    """Deepgram service using stable SDK 3.7.2"""
    
    def __init__(self, on_speech_end_callback: TranscriptCallback):
        """Initialize Deepgram service."""
        self.dg_connection = None
        self.final_result = ""
        self.speech_final = False
        self._on_speech_end = on_speech_end_callback
        self.audio_sent_count = 0
        
        logger.info("=" * 80)
        logger.info("DeepgramService -> Initializing SDK 3.7.2")
        logger.info("=" * 80)
        self._initialize_connection()
    
    def _initialize_connection(self):
        """Initialize Deepgram for SDK 3.7.2"""
        from app.config.voice_config import voice_config
        
        api_key = getattr(voice_config, 'DEEPGRAM_API_KEY', None)
        if not api_key:
            logger.error("❌ DEEPGRAM_API_KEY not set")
            return
        
        logger.info(f"✓ API Key: {api_key[:10]}...{api_key[-4:]}")
        
        try:
            # SDK 3.x imports
            from deepgram import DeepgramClient, DeepgramClientOptions, LiveTranscriptionEvents, LiveOptions
            
            logger.info("✓ Imported SDK 3.x components")
            
            # Create config
            config = DeepgramClientOptions(api_key=api_key)
            self.client = DeepgramClient("", config)
            self.LiveTranscriptionEvents = LiveTranscriptionEvents
            self.LiveOptions = LiveOptions
            
            logger.info("✓ DeepgramClient created")
            
            self.initialized = True
            
            logger.info("=" * 80)
            logger.info("✓✓✓ DEEPGRAM INITIALIZED")
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error("=" * 80)
            logger.error(f"❌ FAILED: {e}")
            logger.error("=" * 80)
            import traceback
            traceback.print_exc()
            self.initialized = False
    
    async def connect(self) -> bool:
        """Start Deepgram connection"""
        if not hasattr(self, 'initialized') or not self.initialized:
            logger.error("❌ Client not initialized")
            return False
        
        try:
            logger.info("=" * 80)
            logger.info("CONNECTING TO DEEPGRAM")
            logger.info("=" * 80)
            
            # Get connection
            self.dg_connection = self.client.listen.asynclive.v("1")
            
            # Register handlers
            logger.info("Registering handlers...")
            self.dg_connection.on(self.LiveTranscriptionEvents.Open, self._on_open)
            self.dg_connection.on(self.LiveTranscriptionEvents.Transcript, self._on_transcript)
            self.dg_connection.on(self.LiveTranscriptionEvents.Error, self._on_error)
            self.dg_connection.on(self.LiveTranscriptionEvents.Close, self._on_close)
            logger.info("✓ Handlers registered")
            
            # Create options
            options = self.LiveOptions(
                model="nova-2-phonecall",
                encoding="mulaw",
                sample_rate=8000,
                punctuate=True,
                interim_results=True,
                endpointing=300,
                utterance_end_ms=1200
            )
            
            logger.info(f"✓ Options: {options.model}, {options.encoding}, {options.sample_rate}Hz")
            
            # Start connection
            logger.info("Starting connection...")
            await self.dg_connection.start(options)
            
            logger.info("=" * 80)
            logger.info("✓✓✓ CONNECTED!")
            logger.info("=" * 80)
            return True
            
        except Exception as e:
            logger.error("=" * 80)
            logger.error(f"❌ CONNECTION FAILED: {e}")
            logger.error("=" * 80)
            import traceback
            traceback.print_exc()
            return False
    
    def _on_open(self, *args, **kwargs):
        """WebSocket opened"""
        logger.info("=" * 80)
        logger.info("🎤🎤🎤 WEBSOCKET OPENED!")
        logger.info("=" * 80)
    
    def _on_transcript(self, *args, **kwargs):
        """Handle transcription"""
        try:
            result = kwargs.get('result') or (args[0] if args else None)
            if not result:
                return
            
            # Extract text
            text = ''
            if hasattr(result, 'channel'):
                channel = result.channel
                if hasattr(channel, 'alternatives') and channel.alternatives:
                    text = channel.alternatives[0].transcript or ''
            
            if not text.strip():
                return
            
            # Check if final
            is_final = getattr(result, 'is_final', False)
            
            if is_final:
                self.final_result += f" {text}"
                
                logger.info("─" * 80)
                logger.info(f"📝 FINAL: '{text}'")
                logger.info(f"📝 TOTAL: '{self.final_result.strip()}'")
                logger.info("─" * 80)
                
                # Check speech_final
                speech_final = getattr(result, 'speech_final', False)
                
                if speech_final:
                    final_text = self.final_result.strip()
                    
                    logger.info("=" * 80)
                    logger.info("🎤🎤🎤 SPEECH FINAL!")
                    logger.info(f"USER SAID: '{final_text}'")
                    logger.info("=" * 80)
                    
                    # Trigger callback
                    asyncio.create_task(self._on_speech_end(final_text))
                    
                    self.final_result = ""
            else:
                logger.debug(f"💬 Interim: '{text}'")
                    
        except Exception as e:
            logger.error(f"❌ Transcript error: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_error(self, *args, **kwargs):
        """Handle errors"""
        error = kwargs.get('error') or (args[0] if args else 'Unknown')
        logger.error("=" * 80)
        logger.error(f"❌❌❌ ERROR: {error}")
        logger.error("=" * 80)
    
    def _on_close(self, *args, **kwargs):
        """Connection closed"""
        logger.info(f"Connection closed ({self.audio_sent_count} chunks)")
    
    async def send_audio(self, audio_chunk: bytes):
        """Send audio to Deepgram"""
        if self.dg_connection:
            try:
                await self.dg_connection.send(audio_chunk)
                self.audio_sent_count += 1
                
                if self.audio_sent_count % 100 == 0:
                    logger.info(f"📡 Sent {self.audio_sent_count} chunks")
                    
            except Exception as e:
                if self.audio_sent_count < 3:
                    logger.error(f"❌ Send error: {e}")
    
    def send(self, payload: str):
        """Send base64 audio"""
        if not self.dg_connection:
            if self.audio_sent_count == 0:
                logger.error("❌ Not connected!")
            return
        
        try:
            audio_bytes = base64.b64decode(payload)
            asyncio.create_task(self.send_audio(audio_bytes))
        except Exception as e:
            logger.error(f"❌ Decode error: {e}")
    
    async def close(self):
        """Close connection"""
        if self.dg_connection:
            try:
                logger.info(f"Closing ({self.audio_sent_count} chunks)")
                await self.dg_connection.finish()
                self.dg_connection = None
            except Exception as e:
                logger.error(f"Close error: {e}")
    
    def is_ready(self) -> bool:
        """Check if ready"""
        return self.dg_connection is not None


class DeepgramManager:
    """Manager for Deepgram connections"""
    
    def __init__(self):
        self._connections: Dict[str, DeepgramService] = {}
        logger.info("DeepgramManager initialized")
    
    def create_connection(
        self,
        call_sid: str,
        on_speech_end_callback: TranscriptCallback
    ) -> DeepgramService:
        """Create connection"""
        logger.info(f"Creating connection: {call_sid}")
        service = DeepgramService(on_speech_end_callback)
        self._connections[call_sid] = service
        return service
    
    async def remove_connection(self, call_sid: str):
        """Remove connection"""
        if call_sid in self._connections:
            logger.info(f"Removing: {call_sid}")
            service = self._connections.pop(call_sid)
            await service.close()
