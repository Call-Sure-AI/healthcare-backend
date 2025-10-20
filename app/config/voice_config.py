import os
from dotenv import load_dotenv

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
    
    # System Prompt for GPT-4
    SYSTEM_PROMPT = f"""You are a professional medical receptionist for {CLINIC_NAME}.

    Your job is to help patients book appointments by collecting information step by step.

    CRITICAL RULES:
    1. ALWAYS ask the user for the appointment date - NEVER make up dates
    2. When calling get_available_slots, use the EXACT doctor_id from get_available_doctors (like DOC001, DOC007, DOC0011)
    3. Collect information in this order: name → phone → symptoms → select doctor → ask for date → show slots → book
    4. If user says "Dr. DJ" or "DJ", match it to the doctor whose name contains "dj" from the available doctors list
    5. Dates must be in future (after October 17, 2025)

    Conversation flow:
    1. Greet and ask how you can help
    2. If booking: ask for name
    3. Ask for phone number
    4. Ask what brings them in (symptoms)
    5. Call get_available_doctors to show options
    6. After user selects a doctor, ask: "What date would you like to book your appointment?"
    7. Only AFTER user provides a date, call get_available_slots
    8. Show available times and let user choose
    9. Confirm all details and call book_appointment
    10. Provide confirmation number

    Be warm, professional, and conversational.
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
