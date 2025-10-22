import asyncio
import base64
import logging
import os
from typing import Callable, Awaitable, Dict

logger = logging.getLogger(__name__)

TranscriptCallback = Callable[[str], Awaitable[None]]


class DeepgramService:
    """Manages real-time Deepgram transcription with SDK 5.1.0"""
    
    def __init__(self, on_speech_end_callback: TranscriptCallback):
        """Initialize Deepgram service."""
        self.dg_connection = None
        self.final_result = ""
        self.speech_final = False
        self._on_speech_end = on_speech_end_callback
        self.audio_sent_count = 0
        
        logger.info("=" * 80)
        logger.info("DeepgramService -> Initializing for SDK 5.1.0")
        logger.info("=" * 80)
        self._initialize_connection()
    
    def _initialize_connection(self):
        """Initialize Deepgram connection for SDK 5.1.0"""
        from app.config.voice_config import voice_config
        
        # Check API key
        api_key = getattr(voice_config, 'DEEPGRAM_API_KEY', None)
        if not api_key:
            logger.error("❌ DEEPGRAM_API_KEY not set")
            return
        
        logger.info(f"✓ API Key: {api_key[:10]}...{api_key[-4:]}")
        
        try:
            # Set environment variable (required for SDK 5.x)
            os.environ['DEEPGRAM_API_KEY'] = api_key
            
            # Import for SDK 5.x
            from deepgram import (
                DeepgramClient,
                DeepgramClientOptions,
                LiveTranscriptionEvents,
                LiveOptions,
            )
            
            logger.info("✓ Imported Deepgram SDK 5.x modules")
            
            # Create config (SDK 5.x uses api_key parameter)
            config = DeepgramClientOptions(
                api_key=api_key,
                verbose=logging.DEBUG  # Enable verbose logging
            )
            
            # Create client
            client = DeepgramClient("", config)
            logger.info("✓ DeepgramClient created")
            
            # Get asynclive connection (SDK 5.x)
            self.dg_connection = client.listen.asynclive.v("1")
            logger.info("✓ Got asynclive connection")
            
            # Store events enum for later use
            self.LiveTranscriptionEvents = LiveTranscriptionEvents
            
            logger.info("=" * 80)
            logger.info("✓✓✓ DEEPGRAM CLIENT READY")
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error("=" * 80)
            logger.error(f"❌ INITIALIZATION FAILED: {e}")
            logger.error("=" * 80)
            import traceback
            traceback.print_exc()
            self.dg_connection = None
    
    async def connect(self) -> bool:
        """Start Deepgram connection."""
        if not self.dg_connection:
            logger.error("❌ No connection - initialization failed")
            return False
        
        try:
            logger.info("=" * 80)
            logger.info("CONNECTING TO DEEPGRAM")
            logger.info("=" * 80)
            
            # Import LiveOptions
            from deepgram import LiveOptions
            
            # Register event handlers (SDK 5.x uses enum)
            logger.info("Registering event handlers...")
            self.dg_connection.on(self.LiveTranscriptionEvents.Open, self._on_open)
            self.dg_connection.on(self.LiveTranscriptionEvents.Transcript, self._on_transcript)
            self.dg_connection.on(self.LiveTranscriptionEvents.Error, self._on_error)
            self.dg_connection.on(self.LiveTranscriptionEvents.Close, self._on_close)
            logger.info("✓ Event handlers registered")
            
            # Create options (SDK 5.x)
            options = LiveOptions(
                model="nova-3",
                language="en-US",
                encoding="mulaw",
                sample_rate=8000,
                punctuate=True,
                interim_results=True,
                endpointing=300,
                utterance_end_ms=1200,
            )
            
            logger.info(f"Options: model={options.model}, encoding={options.encoding}")
            
            # Start connection
            logger.info("Starting connection...")
            start_result = await self.dg_connection.start(options)
            
            logger.info("=" * 80)
            logger.info(f"✓✓✓ CONNECTED: {start_result}")
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
        """Called when WebSocket opens"""
        logger.info("=" * 80)
        logger.info("🎤🎤🎤 WEBSOCKET OPENED - READY!")
        logger.info("=" * 80)
    
    def _on_transcript(self, *args, **kwargs):
        """Handle transcription events (SDK 5.x)"""
        try:
            # SDK 5.x passes result in kwargs
            result = kwargs.get('result')
            if not result:
                logger.debug("Transcript event with no result")
                return
            
            # Get transcript text
            text = ''
            if hasattr(result, 'channel'):
                channel = result.channel
                if hasattr(channel, 'alternatives') and len(channel.alternatives) > 0:
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
                
                # Check for speech_final
                speech_final = getattr(result, 'speech_final', False)
                
                if speech_final:
                    self.speech_final = True
                    final_text = self.final_result.strip()
                    
                    logger.info("=" * 80)
                    logger.info("🎤🎤🎤 SPEECH FINAL - USER SAID:")
                    logger.info(f"'{final_text}'")
                    logger.info("=" * 80)
                    
                    # Trigger callback
                    asyncio.create_task(self._on_speech_end(final_text))
                    self.final_result = ""
                    self.speech_final = False
            else:
                # Interim result
                logger.debug(f"💬 Interim: '{text}'")
                    
        except Exception as e:
            logger.error(f"❌ Error in transcript: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_error(self, *args, **kwargs):
        """Handle errors"""
        error = kwargs.get('error', args[0] if args else 'Unknown')
        logger.error("=" * 80)
        logger.error(f"❌❌❌ DEEPGRAM ERROR: {error}")
        logger.error("=" * 80)
    
    def _on_close(self, *args, **kwargs):
        """Connection closed"""
        logger.info(f"Connection closed (sent {self.audio_sent_count} chunks)")
    
    async def send_audio(self, audio_chunk: bytes):
        """Send audio to Deepgram"""
        if self.dg_connection:
            try:
                await self.dg_connection.send(audio_chunk)
                self.audio_sent_count += 1
                
                # Log every 100 chunks
                if self.audio_sent_count % 100 == 0:
                    logger.info(f"📡 Sent {self.audio_sent_count} audio chunks")
                    
            except Exception as e:
                if self.audio_sent_count < 5:  # Only log first few errors
                    logger.error(f"❌ Error sending audio: {e}")
    
    def send(self, payload: str):
        """Send base64 encoded audio"""
        if not self.dg_connection:
            if self.audio_sent_count == 0:
                logger.error("❌ Cannot send - not connected!")
            return
        
        try:
            audio_bytes = base64.b64decode(payload)
            asyncio.create_task(self.send_audio(audio_bytes))
        except Exception as e:
            logger.error(f"❌ Error decoding audio: {e}")
    
    async def close(self):
        """Close connection"""
        if self.dg_connection:
            try:
                logger.info(f"Closing connection (sent {self.audio_sent_count} chunks)")
                await self.dg_connection.finish()
                self.dg_connection = None
            except Exception as e:
                logger.error(f"Error closing: {e}")
    
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
        """Create new connection"""
        logger.info(f"Creating connection for: {call_sid}")
        service = DeepgramService(on_speech_end_callback)
        self._connections[call_sid] = service
        logger.info(f"✓ Service created")
        return service
    
    async def remove_connection(self, call_sid: str):
        """Remove connection"""
        if call_sid in self._connections:
            logger.info(f"Removing connection: {call_sid}")
            service = self._connections.pop(call_sid)
            await service.close()
