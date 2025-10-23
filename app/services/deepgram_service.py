"""
Deepgram STT Service - Direct WebSocket Implementation
Works with any Deepgram SDK version
"""
import asyncio
import base64
import json
import logging
import os
from typing import Callable, Awaitable, Dict
import websockets

logger = logging.getLogger(__name__)

TranscriptCallback = Callable[[str], Awaitable[None]]


class DeepgramService:
    """Direct WebSocket connection to Deepgram API"""
    
    def __init__(self, on_speech_end_callback: TranscriptCallback):
        """Initialize Deepgram service."""
        self.dg_connection = None
        self.final_result = ""
        self.speech_final = False
        self._on_speech_end = on_speech_end_callback
        self.audio_sent_count = 0
        self._connection_task = None
        self.api_key = None
        
        logger.info("=" * 80)
        logger.info("DeepgramService -> Initializing Direct WebSocket")
        logger.info("=" * 80)
        self._initialize_connection()
    
    def _initialize_connection(self):
        """Initialize Deepgram configuration"""
        from app.config.voice_config import voice_config
        
        self.api_key = getattr(voice_config, 'DEEPGRAM_API_KEY', None)
        if not self.api_key:
            logger.error("❌ DEEPGRAM_API_KEY not set")
            return
        
        logger.info(f"✓ API Key: {self.api_key[:10]}...{self.api_key[-4:]}")
        self.initialized = True
        
        logger.info("=" * 80)
        logger.info("✓✓✓ DEEPGRAM INITIALIZED")
        logger.info("=" * 80)
    
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
        """Maintain WebSocket connection to Deepgram"""
        try:
            # Build WebSocket URL with query parameters
            params = {
                'model': 'nova-2-phonecall',
                'encoding': 'mulaw',
                'sample_rate': '8000',
                'punctuate': 'true',
                'interim_results': 'true',
                'endpointing': '300',
                'utterance_end_ms': '1200',
                'language': 'en'
            }
            
            query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
            ws_url = f"wss://api.deepgram.com/v1/listen?{query_string}"
            
            logger.info(f"Connecting to: {ws_url[:80]}...")
            
            # Connect with authorization header
            headers = {
                'Authorization': f'Token {self.api_key}'
            }
            
            async with websockets.connect(ws_url, extra_headers=headers) as websocket:
                logger.info("✓ WebSocket connected")
                
                self.dg_connection = websocket
                
                logger.info("=" * 80)
                logger.info("🎤🎤🎤 DEEPGRAM WEBSOCKET OPENED!")
                logger.info("=" * 80)
                
                # Listen for messages
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        await self._handle_message(data)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON: {message[:100]}")
                    except Exception as e:
                        logger.error(f"Message handling error: {e}")
                        
        except Exception as e:
            logger.error(f"❌ Connection error: {e}")
            import traceback
            traceback.print_exc()
            self.dg_connection = None
    
    async def _handle_message(self, data: dict):
        """Handle incoming Deepgram message"""
        try:
            # Check message type
            msg_type = data.get('type')
            
            if msg_type == 'Results':
                # Extract transcript
                channel = data.get('channel', {})
                alternatives = channel.get('alternatives', [])
                
                if not alternatives:
                    return
                
                transcript = alternatives[0].get('transcript', '')
                
                if not transcript.strip():
                    return
                
                # Check if final
                is_final = data.get('is_final', False)
                
                if is_final:
                    self.final_result += f" {transcript}"
                    
                    logger.info("─" * 80)
                    logger.info(f"📝 FINAL: '{transcript}'")
                    logger.info(f"📝 TOTAL: '{self.final_result.strip()}'")
                    logger.info("─" * 80)
                    
                    # Check speech_final
                    speech_final = data.get('speech_final', False)
                    
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
                    logger.debug(f"💬 Interim: '{transcript}'")
                    
            elif msg_type == 'UtteranceEnd':
                if self.final_result.strip():
                    final_text = self.final_result.strip()
                    
                    logger.info("=" * 80)
                    logger.info("🎤 UTTERANCE END!")
                    logger.info(f"USER SAID: '{final_text}'")
                    logger.info("=" * 80)
                    
                    asyncio.create_task(self._on_speech_end(final_text))
                    self.final_result = ""
                    
        except Exception as e:
            logger.error(f"❌ Message handling error: {e}")
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
                await self.dg_connection.close()
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
