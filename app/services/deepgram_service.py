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
        logger.info("DeepgramService -> Initializing SDK 5.1.0")
        logger.info("=" * 80)
        self._initialize_connection()
    
    def _initialize_connection(self):
        """Initialize Deepgram for SDK 5.1.0"""
        from app.config.voice_config import voice_config
        
        # Get API key
        api_key = getattr(voice_config, 'DEEPGRAM_API_KEY', None)
        if not api_key:
            logger.error("❌ DEEPGRAM_API_KEY not set")
            return
        
        logger.info(f"✓ API Key: {api_key[:10]}...{api_key[-4:]}")
        
        try:
            # Set environment variable (SDK 5.x reads from here)
            os.environ['DEEPGRAM_API_KEY'] = api_key
            logger.info("✓ Environment variable set")
            
            # Import only what's available in SDK 5.1.0
            from deepgram import DeepgramClient, LiveOptions
            
            logger.info("✓ Imported DeepgramClient and LiveOptions")
            
            # Create client (reads API key from environment)
            client = DeepgramClient()
            logger.info("✓ DeepgramClient created")
            
            # Get asynclive connection
            self.dg_connection = client.listen.asynclive.v("1")
            logger.info("✓ Got asynclive connection")
            
            logger.info("=" * 80)
            logger.info("✓✓✓ DEEPGRAM INITIALIZED SUCCESSFULLY")
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error("=" * 80)
            logger.error(f"❌ INITIALIZATION FAILED: {e}")
            logger.error("=" * 80)
            import traceback
            traceback.print_exc()
            self.dg_connection = None
    
    async def connect(self) -> bool:
        """Start Deepgram connection"""
        if not self.dg_connection:
            logger.error("❌ No connection object - init failed")
            return False
        
        try:
            logger.info("=" * 80)
            logger.info("STARTING DEEPGRAM CONNECTION")
            logger.info("=" * 80)
            
            from deepgram import LiveOptions
            
            # Register event handlers using STRING names (SDK 5.1.0)
            logger.info("Registering event handlers...")
            self.dg_connection.on("Open", self._on_open)
            self.dg_connection.on("Transcript", self._on_transcript)
            self.dg_connection.on("Error", self._on_error)
            self.dg_connection.on("Close", self._on_close)
            logger.info("✓ Event handlers registered")
            
            # Create options
            options = LiveOptions(
                model="nova-2-phonecall",
                language="en-US",
                encoding="mulaw",
                sample_rate=8000,
                punctuate=True,
                interim_results=True,
                endpointing=300,
                utterance_end_ms=1200,
            )
            
            logger.info(f"✓ Options created: {options.model}, {options.encoding}, {options.sample_rate}Hz")
            
            # Start connection
            logger.info("Calling start()...")
            result = await self.dg_connection.start(options)
            
            logger.info("=" * 80)
            logger.info(f"✓✓✓ CONNECTION STARTED: {result}")
            logger.info("=" * 80)
            return True
            
        except Exception as e:
            logger.error("=" * 80)
            logger.error(f"❌❌❌ CONNECTION FAILED: {e}")
            logger.error("=" * 80)
            import traceback
            traceback.print_exc()
            return False
    
    def _on_open(self, *args, **kwargs):
        """WebSocket opened"""
        logger.info("=" * 80)
        logger.info("🎤🎤🎤 DEEPGRAM WEBSOCKET OPENED!")
        logger.info("🎤🎤🎤 READY TO TRANSCRIBE AUDIO!")
        logger.info("=" * 80)
    
    def _on_transcript(self, *args, **kwargs):
        """Handle incoming transcription events"""
        try:
            # Get result from kwargs
            result = kwargs.get('result')
            if not result:
                logger.debug("Transcript event with no result")
                return
            
            # Extract transcript text
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
                # Accumulate final text
                self.final_result += f" {text}"
                
                logger.info("─" * 80)
                logger.info(f"📝 FINAL CHUNK: '{text}'")
                logger.info(f"📝 ACCUMULATED SO FAR: '{self.final_result.strip()}'")
                logger.info("─" * 80)
                
                # Check for speech_final
                speech_final = getattr(result, 'speech_final', False)
                
                if speech_final:
                    final_text = self.final_result.strip()
                    
                    logger.info("=" * 80)
                    logger.info("🎤🎤🎤 SPEECH FINAL!")
                    logger.info(f"USER SAID: '{final_text}'")
                    logger.info("=" * 80)
                    
                    # Trigger callback to process user speech
                    asyncio.create_task(self._on_speech_end(final_text))
                    
                    # Reset for next utterance
                    self.final_result = ""
                    self.speech_final = False
            else:
                # Interim result (not final yet)
                logger.debug(f"💬 Interim: '{text}'")
                    
        except Exception as e:
            logger.error(f"❌ Error in _on_transcript: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_error(self, *args, **kwargs):
        """Handle Deepgram errors"""
        error = kwargs.get('error') or (args[0] if args else 'Unknown error')
        logger.error("=" * 80)
        logger.error(f"❌❌❌ DEEPGRAM ERROR: {error}")
        logger.error("=" * 80)
    
    def _on_close(self, *args, **kwargs):
        """Connection closed"""
        logger.info(f"Deepgram connection closed (sent {self.audio_sent_count} audio chunks)")
    
    async def send_audio(self, audio_chunk: bytes):
        """Send audio bytes to Deepgram"""
        if self.dg_connection:
            try:
                await self.dg_connection.send(audio_chunk)
                self.audio_sent_count += 1
                
                # Log every 100 chunks
                if self.audio_sent_count % 100 == 0:
                    logger.info(f"📡 Sent {self.audio_sent_count} audio chunks to Deepgram")
                    
            except Exception as e:
                if self.audio_sent_count < 3:  # Only log first few errors
                    logger.error(f"❌ Error sending audio: {e}")
    
    def send(self, payload: str):
        """Send base64 encoded audio"""
        if not self.dg_connection:
            if self.audio_sent_count == 0:
                logger.error("❌ Cannot send audio - Deepgram not connected!")
            return
        
        try:
            # Decode base64 to bytes
            audio_bytes = base64.b64decode(payload)
            # Send asynchronously
            asyncio.create_task(self.send_audio(audio_bytes))
        except Exception as e:
            logger.error(f"❌ Error decoding audio: {e}")
    
    async def close(self):
        """Close Deepgram connection"""
        if self.dg_connection:
            try:
                logger.info(f"Closing Deepgram connection (sent {self.audio_sent_count} chunks total)")
                await self.dg_connection.finish()
                self.dg_connection = None
                logger.info("✓ Deepgram connection closed")
            except Exception as e:
                logger.error(f"Error closing connection: {e}")
    
    def is_ready(self) -> bool:
        """Check if connection is ready to send audio"""
        return self.dg_connection is not None


class DeepgramManager:
    """Manager for multiple Deepgram connections (one per call)"""
    
    def __init__(self):
        self._connections: Dict[str, DeepgramService] = {}
        logger.info("DeepgramManager initialized")
    
    def create_connection(
        self,
        call_sid: str,
        on_speech_end_callback: TranscriptCallback
    ) -> DeepgramService:
        """Create new Deepgram connection for a call"""
        logger.info(f"Creating connection: {call_sid}")
        service = DeepgramService(on_speech_end_callback)
        self._connections[call_sid] = service
        logger.info(f"✓ Service created for {call_sid}")
        return service
    
    async def remove_connection(self, call_sid: str):
        """Remove and close Deepgram connection"""
        if call_sid in self._connections:
            logger.info(f"Removing connection: {call_sid}")
            service = self._connections.pop(call_sid)
            await service.close()
            logger.info(f"✓ Connection removed: {call_sid}")
        else:
            logger.warning(f"No connection found to remove: {call_sid}")