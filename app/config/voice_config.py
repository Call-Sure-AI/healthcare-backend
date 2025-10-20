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

    CALL_SESSION_TTL = int(os.getenv("CALL_SESSION_TTL"))
    MAX_CALL_DURATION = int(os.getenv("MAX_CALL_DURATION"))
    MAX_RETRY_ATTEMPTS = int(os.getenv("MAX_RETRY_ATTEMPTS"))
    
    # Feature Flags
    VOICE_AGENT_ENABLED = os.getenv("VOICE_AGENT_ENABLED").lower() == "true"
    ENABLE_CALL_RECORDING = os.getenv("ENABLE_CALL_RECORDING").lower() == "true"
    ENABLE_SMS_CONFIRMATION = os.getenv("ENABLE_SMS_CONFIRMATION").lower() == "true"
    
    # Clinic Information
    CLINIC_NAME = os.getenv("CLINIC_NAME", "HealthCare Clinic")
    CLINIC_ADDRESS = os.getenv("CLINIC_ADDRESS", "123 Health Street")
    CLINIC_PHONE = os.getenv("CLINIC_PHONE", TWILIO_PHONE_NUMBER)

    SYSTEM_PROMPT = f"""
    You are a friendly, intelligent, and highly efficient AI assistant for {CLINIC_NAME}.
    Your main goal is to help patients book, reschedule, or cancel appointments. Be conversational and proactive.

    TOOL USAGE GUIDELINES:
    - Use `get_available_doctors` when the patient wants to know which doctors are available but hasn't specified one.
    - If the patient asks WHEN a specific doctor is available but does NOT provide a date, you MUST use the `get_doctor_schedule` tool to find their next available dates.
    - Once you have BOTH a doctor AND a specific date from the patient, use `get_available_slots` to find appointment times.
    - Before calling `book_appointment`, always confirm the full details (patient name, doctor, date, and time) with the user.

    CONVERSATIONAL NOTES:
    - If you don't have enough information to use a tool, ask the user for it naturally.
    - Keep your responses helpful and concise.
    - Always handle one task at a time.
    """

    
    @classmethod
    def validate_config(cls) -> bool:
        """Validate required configuration"""
        required_vars = [
            ("TWILIO_ACCOUNT_SID", cls.TWILIO_ACCOUNT_SID),
            ("TWILIO_AUTH_TOKEN", cls.TWILIO_AUTH_TOKEN),
            ("TWILIO_PHONE_NUMBER", cls.TWILIO_PHONE_NUMBER),
            ("OPENAI_API_KEY", cls.OPENAI_API_KEY),
        ]
        
        missing = [name for name, value in required_vars if not value]
        
        if missing:
            print(f"Missing required environment variables: {', '.join(missing)}")
            return False
        
        print("Voice agent configuration validated")
        return True


# Global instance
voice_config = VoiceAgentConfig()
