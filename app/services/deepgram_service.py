"""
Deepgram STT Service for SDK 5.1.0
Based on official GitHub documentation
"""
import asyncio
import base64
import logging
import os
from typing import Callable, Awaitable, Dict

logger = logging.getLogger(__name__)

TranscriptCallback = Callable[[str], Awaitable[None]]


class DeepgramService:
    """Deepgram service using SDK 5.1.0 official pattern"""
    
    def __init__(self, on_speech_end_callback: TranscriptCallback):
        """Initialize Deepgram service."""
        self.dg_connection = None
        self.final_result = ""
        self.speech_final = False
        self._on_speech_end = on_speech_end_callback
        self.audio_sent_count = 0
        self._connection_task = None
        
        logger.info("=" * 80)
        logger.info("DeepgramService -> Initializing SDK 5.1.0")
        logger.info("=" * 80)
        self._initialize_connection()
    
    def _initialize_connection(self):
        """Initialize Deepgram for SDK 5.1.0"""
        from app.config.voice_config import voice_config
        
        api_key = getattr(voice_config, 'DEEPGRAM_API_KEY', None)
        if not api_key:
            logger.error("❌ DEEPGRAM_API_KEY not set")
            return
        
        logger.info(f"✓ API Key: {api_key[:10]}...{api_key[-4:]}")
        
        try:
            os.environ['DEEPGRAM_API_KEY'] = api_key
            logger.info("✓ Environment variable set")
            
            # Import SDK 5.x components
            from deepgram import AsyncDeepgramClient, EventType
            
            logger.info("✓ Imported AsyncDeepgramClient and EventType")
            
            self.client = AsyncDeepgramClient()
            self.EventType = EventType
            logger.info("✓ AsyncDeepgramClient created")
            
            self.initialized = True
            
            logger.info("=" * 80)
            logger.info("✓✓✓ DEEPGRAM INITIALIZED")
            logger.info("=" * 80)
            
        except ImportError as e:
            logger.error(f"❌ Import failed: {e}. EventType may not exist in this SDK version")
            # Try without EventType
            try:
                from deepgram import AsyncDeepgramClient
                self.client = AsyncDeepgramClient()
                self.EventType = None
                self.initialized = True
                logger.info("✓ Initialized without EventType (using strings)")
            except Exception as e2:
                logger.error(f"❌ Failed completely: {e2}")
                self.initialized = False
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
            
            self._connection_task = asyncio.create_task(self._maintain_connection())
            
            # Wait for connection
            await asyncio.sleep(2)
            
            if self.dg_connection:
                logger.info("=" * 80)
                logger.info("✓✓✓ CONNECTED AND READY!")
                logger.info("=" * 80)
                return True
            else:
                logger.error("Connection not established")
                return False
        
        except Exception as e:
            logger.error("=" * 80)
            logger.error(f"❌ CONNECTION FAILED: {e}")
            logger.error("=" * 80)
            import traceback
            traceback.print_exc()
            return False
    
    async def _maintain_connection(self):
        """Maintain connection - Official SDK 5.x pattern from GitHub"""
        try:
            logger.info("Creating v2 connection (official pattern)...")
            
            # Official SDK 5.x pattern from GitHub README
            async with self.client.listen.v2.connect(
                model="nova-2-phonecall",
                encoding="mulaw",
                sample_rate=16000  # Changed from 8000 to 16000
            ) as connection:
                
                logger.info("✓ Connection context entered")
                
                self.dg_connection = connection
                
                # Define async callback
                async def on_message(message):
                    await self._on_message(message)
                
                # Register event handlers
                logger.info("Registering handlers...")
                if self.EventType:
                    # Use EventType enum if available
                    connection.on(self.EventType.OPEN, lambda: logger.info("🎤 WebSocket opened"))
                    connection.on(self.EventType.MESSAGE, on_message)
                    connection.on(self.EventType.ERROR, lambda error: logger.error(f"❌ Error: {error}"))
                    connection.on(self.EventType.CLOSE, lambda: logger.info("Connection closed"))
                else:
                    # Fallback to strings
                    connection.on("Open", lambda: logger.info("🎤 WebSocket opened"))
                    connection.on("Message", on_message)
                    connection.on("Error", lambda error: logger.error(f"❌ Error: {error}"))
                    connection.on("Close", lambda: logger.info("Connection closed"))
                
                logger.info("✓ Handlers registered")
                
                # Start listening - THIS IS REQUIRED
                logger.info("Starting listening...")
                await connection.start_listening()
                logger.info("✓ Listening started")
                
                logger.info("=" * 80)
                logger.info("🎤🎤🎤 DEEPGRAM READY!")
                logger.info("=" * 80)
                
                # Keep connection alive
                while self.dg_connection:
                    await asyncio.sleep(0.1)
                    
        except Exception as e:
            logger.error(f"❌ Connection error: {e}")
            import traceback
            traceback.print_exc()
            self.dg_connection = None
    
    async def _on_message(self, message):
        """Handle incoming message"""
        try:
            # Check message type
            if hasattr(message, 'type') and message.type != 'Results':
                return
            
            # Get result
            result = message if hasattr(message, 'channel') else getattr(message, 'result', None)
            if not result:
                return
            
            # Extract transcript
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
            logger.error(f"❌ Message error: {e}")
            import traceback
            traceback.print_exc()
    
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
                
                if self._connection_task:
                    self._connection_task.cancel()
                    
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
