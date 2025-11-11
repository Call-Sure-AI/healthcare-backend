# app/config/voice_config.py - OPTIMIZED SYSTEM PROMPT

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
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
    OPENAI_FAST_MODEL = os.getenv("OPENAI_FAST_MODEL", "gpt-4o-mini")
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

    # ⚡ OPTIMIZED: Friendly-brief system prompt (max 40 words per response)
    SYSTEM_PROMPT = f"""You are a medical receptionist for {CLINIC_NAME}. Help patients book appointments.

**CRITICAL: Keep responses under 40 words. Use 1-2 sentences only.**

TOOLS:
- search_doctor_information(query) - Search for doctors by specialty or symptoms
- get_available_doctors(symptoms) - Get list of doctors, optionally filtered by symptoms
- get_doctor_schedule(doctor_id, date) - Check when a specific doctor is available
- get_available_slots(doctor_id, date) - Get specific time slots for a doctor
- book_appointment_in_hour_range(patient_name, phone, doctor_id, date, start_hour, end_hour, reason) - Book appointment
- get_appointment_details(phone_number) - Check existing appointments

CONVERSATION FLOW:
1. Understand patient's need (symptoms/preferred doctor)
2. Use tools to find appropriate doctors
3. Suggest 2-3 relevant doctors briefly
4. Check availability when patient chooses
5. Confirm details and book

RESPONSE STYLE:
✅ GOOD: "I found Dr. Sharma for headaches. Available tomorrow at 2 PM. Should I book it?"
❌ BAD: "Sorry you're not feeling well. Let me help you find the right doctor. I have several options available..."

RULES:
- Always use tools for real information
- Never make up doctor names or availability
- Ask ONE question at a time
- Be friendly but brief
- If emergency symptoms (severe chest pain, breathing difficulty), advise calling emergency services immediately"""
    
    @classmethod
    def validate_config(cls) -> bool:
        """Validate required configuration"""
        required_vars = [
            ("TWILIO_ACCOUNT_SID", cls.TWILIO_ACCOUNT_SID),
            ("TWILIO_AUTH_TOKEN", cls.TWILIO_AUTH_TOKEN),
            ("TWILIO_PHONE_NUMBER", cls.TWILIO_PHONE_NUMBER),
            ("OPENAI_API_KEY", cls.OPENAI_API_KEY),
            ("ELEVENLABS_API_KEY", cls.ELEVENLABS_API_KEY),
            ("DEEPGRAM_API_KEY", cls.DEEPGRAM_API_KEY),
        ]
        
        missing = [name for name, value in required_vars if not value]
        
        if missing:
            print(f"Missing required environment variables: {', '.join(missing)}")
            return False
        
        print("✨ Voice agent configuration validated (BRIEF & FRIENDLY)")
        return True


# Global instance
voice_config = VoiceAgentConfig()
