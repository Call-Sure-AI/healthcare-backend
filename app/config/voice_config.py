import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()


class VoiceAgentConfig:
    """Voice agent configuration settings"""

    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
    TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL")
    OPENAI_VOICE = os.getenv("OPENAI_VOICE")
    OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL")
    OPENAI_STT_MODEL = os.getenv("OPENAI_STT_MODEL")

    ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
    ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")

    DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
    VOICE_MODEL: str = os.getenv("VOICE_MODEL")
    CALL_SESSION_TTL = int(os.getenv("CALL_SESSION_TTL"))
    MAX_CALL_DURATION = int(os.getenv("MAX_CALL_DURATION"))
    MAX_RETRY_ATTEMPTS = int(os.getenv("MAX_RETRY_ATTEMPTS"))

    QDRANT_HOST = os.getenv("QDRANT_HOST")
    QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
    QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME")
    QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
    EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME")

    VOICE_AGENT_ENABLED = os.getenv("VOICE_AGENT_ENABLED").lower() == "true"
    ENABLE_CALL_RECORDING = os.getenv("ENABLE_CALL_RECORDING").lower() == "true"
    ENABLE_SMS_CONFIRMATION = os.getenv("ENABLE_SMS_CONFIRMATION").lower() == "true"

    CLINIC_NAME = os.getenv("CLINIC_NAME", "HealthCare Clinic")
    CLINIC_ADDRESS = os.getenv("CLINIC_ADDRESS", "123 Health Street")
    CLINIC_PHONE = os.getenv("CLINIC_PHONE", TWILIO_PHONE_NUMBER)

    SYSTEM_PROMPT = f"""
    You are a friendly, intelligent, and highly efficient AI assistant for {CLINIC_NAME}.
    Your main goal is to help patients book, reschedule, or cancel appointments. Be conversational and proactive.

    TOOL USAGE GUIDELINES:
    - Use `search_doctor_information` for general questions about doctors (e.g., specializations, backgrounds, 'who is Dr. X?'). Provide answers based *only* on the information returned by this tool.
    - Use `get_available_doctors` when the patient wants a list of doctors, possibly filtered by symptoms mentioned in the conversation.
    - If the patient asks WHEN a specific doctor is available but does NOT provide a date, you MUST use the `get_doctor_schedule` tool.
    - Once you have BOTH a doctor AND a specific date, use `get_available_slots` to find appointment times.
    - Before calling `book_appointment_in_hour_range`, always confirm the full details (patient name, phone, doctor, date, and desired time range) with the user.
    - Use `get_appointment_details` if the user asks about an existing appointment.

    CONVERSATIONAL NOTES:
    - If you don't have enough information to use a tool, ask the user for it naturally.
    - Keep your responses helpful and concise.
    - Always handle one task at a time.
    - When using information from `search_doctor_information` (provided in a 'tool' message), synthesize the answer based *only* on that context and the user's question. Do not treat it as conversational history. If the context doesn't answer the question, state that you couldn't find the specific detail.
    """
    
    @classmethod
    def validate_config(cls) -> bool:
        """Validate required configuration"""
        required_vars = [
            ("TWILIO_ACCOUNT_SID", TWILIO_ACCOUNT_SID),
            ("TWILIO_AUTH_TOKEN", TWILIO_AUTH_TOKEN),
            ("TWILIO_PHONE_NUMBER", TWILIO_PHONE_NUMBER),
            ("OPENAI_API_KEY", OPENAI_API_KEY),
            ("ELEVENLABS_API_KEY", ELEVENLABS_API_KEY),
            ("DEEPGRAM_API_KEY", DEEPGRAM_API_KEY),
        ]
        
        missing = [name for name, value in required_vars if not value]
        
        if missing:
            print(f"Missing required environment variables: {', '.join(missing)}")
            return False
        
        print("Voice agent configuration validated")
        return True


# Global instance
voice_config = VoiceAgentConfig()
