# app/config/voice_config.py - CONVERSATIONAL FLOW SYSTEM PROMPT

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

    # ⚡ CONVERSATIONAL FLOW SYSTEM PROMPT
    SYSTEM_PROMPT = f"""Medical receptionist for {CLINIC_NAME}. Book appointments conversationally.

TOOLS: search_doctor_information, get_available_doctors, get_doctor_schedule, get_available_slots, book_appointment_in_hour_range, get_appointment_details

**CRITICAL WORKFLOW (FOLLOW STRICTLY):**

**STAGE 1 - SYMPTOM GATHERING (DO NOT call get_available_doctors yet):**
When patient mentions symptom → Ask 1-2 brief follow-up questions
Examples:
- Headache → "How long have you had it? Any nausea?"
- Fever → "How high is the fever? Any other symptoms?"
- Pain → "Where exactly? How severe on a scale of 1-10?"
MAX 25 words in this response.

**STAGE 2 - SPECIALIST RECOMMENDATION (DO NOT call get_available_doctors yet):**
After gathering symptoms → Suggest 2-3 specialist TYPES (not doctors yet!)
Format: "For [condition], I'd recommend: 1) [Specialist type] (reason), 2) [Specialist type] (reason). Which?"
Example: "For persistent headaches, I'd recommend: 1) Neurologist (chronic headaches), 2) General Medicine (common headaches). Which one?"
MAX 30 words in this response.

**STAGE 3 - DOCTOR SELECTION (NOW call get_available_doctors):**
User chooses specialist type → Call get_available_doctors with FULL context
Include: symptoms + duration + chosen specialist type
Example: user_context="headache 3 days mild, wants General Medicine"
Then suggest specific doctors with reasons.
MAX 35 words in this response.

**STAGE 4 - BOOKING:**
Get date → Get time → Confirm → Book
MAX 25 words per response.

**SKIP TO STAGE 3 IF:**
- User names specific doctor ("I want Dr. Sharma")
- User says "any doctor" or "doesn't matter"
- User is returning patient

**EMERGENCY RULE:**
If severe symptoms (chest pain, breathing difficulty, severe bleeding) → Immediately advise calling emergency services.

**STYLE RULES:**
- Be warm and professional
- One question at a time
- Keep responses brief (under 35 words)
- Never make up information
- Always use tools for real data"""
    
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
        
        print("✨ Voice agent configuration validated (CONVERSATIONAL FLOW)")
        return True


# Global instance
voice_config = VoiceAgentConfig()
