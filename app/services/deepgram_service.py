import asyncio
from typing import Dict, Callable, Awaitable
from deepgram import DeepgramClient
from app.config.voice_config import voice_config

# Type hint for the callback function
TranscriptCallback = Callable[[str], Awaitable[None]]

class DeepgramService:
    """
    Manages a single, real-time transcription connection to Deepgram.
    An instance of this class should be created for each concurrent call.
    """
    def __init__(self, on_speech_end_callback: TranscriptCallback):
        self.client: DeepgramClient = DeepgramClient() 
        self.dg_connection = None
        self._on_speech_end = on_speech_end_callback
        self.final_transcript = ""

    async def connect(self):
        """Establishes the WebSocket connection to Deepgram."""
        try:
            self.dg_connection = self.client.listen.asynclive.v("1")

            self.dg_connection.on(LiveTranscriptionEvents.Open, self._on_open)
            self.dg_connection.on(LiveTranscriptionEvents.Transcript, self._on_message)
            self.dg_connection.on(LiveTranscriptionEvents.UtteranceEnd, self._on_utterance_end)
            self.dg_connection.on(LiveTranscriptionEvents.Error, self._on_error)
            self.dg_connection.on(LiveTranscriptionEvents.Close, self._on_close)

            options: LiveOptions = LiveOptions(
                model="nova-2-phonecall",
                language="en-IN",
                encoding="mulaw",
                sample_rate=8000,
                smart_format=True,
                interim_results=False,
                utterance_end_ms="1000", # How long to wait after speech ends
                vad_events=False, # UtteranceEnd is sufficient
            )

            await self.dg_connection.start(options)
            return True
        except Exception as e:
            print(f"Error connecting to Deepgram: {e}")
            return False

    async def send_audio(self, audio_chunk: bytes):
        """Forwards an audio chunk to Deepgram."""
        if self.dg_connection:
            await self.dg_connection.send(audio_chunk)

    async def finish(self):
        """Closes the Deepgram connection."""
        if self.dg_connection:
            await self.dg_connection.finish()
            self.dg_connection = None

    def _on_open(self, *args, **kwargs):
        print("Deepgram connection opened.")

    def _on_message(self, *args, **kwargs):
        """Handles incoming transcript fragments from Deepgram."""
        result = kwargs.get('result')
        transcript = result.channel.alternatives[0].transcript
        if transcript and result.is_final:
            self.final_transcript += transcript + " "

    def _on_utterance_end(self, *args, **kwargs):
        """Fires when Deepgram detects the end of a spoken utterance."""
        print("Deepgram Utterance End detected.")
        if self.final_transcript.strip():
            # Trigger the main processing with the complete utterance
            asyncio.create_task(self._on_speech_end(self.final_transcript.strip()))
            self.final_transcript = "" # Reset for the next utterance

    def _on_error(self, *args, **kwargs):
        error = kwargs.get('error')
        print(f"Deepgram error: {error}")

    def _on_close(self, *args, **kwargs):
        print("Deepgram connection closed.")


class DeepgramManager:
    """
    A factory and manager for creating and handling multiple DeepgramService instances.
    This ensures each phone call gets its own isolated transcription service.
    """
    def __init__(self):
        self._connections: Dict[str, DeepgramService] = {}

    def create_connection(self, call_sid: str, on_speech_end_callback: TranscriptCallback) -> DeepgramService:
        """Creates a new DeepgramService instance for a specific call."""
        if call_sid in self._connections:
            print(f"Warning: A Deepgram connection for {call_sid} already exists. Overwriting.")
        
        print(f"Creating Deepgram connection for call: {call_sid}")
        service = DeepgramService(on_speech_end_callback)
        self._connections[call_sid] = service
        return service

    async def remove_connection(self, call_sid: str):
        """Closes and removes the DeepgramService instance for a specific call."""
        if call_sid in self._connections:
            print(f"Removing Deepgram connection for call: {call_sid}")
            service = self._connections.pop(call_sid)
            await service.finish()
        else:
            print(f"Warning: No Deepgram connection found for {call_sid} to remove.")

deepgram_manager = DeepgramManager()