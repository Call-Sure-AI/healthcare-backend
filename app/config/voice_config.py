# app/config/voice_config.py - FLEXIBLE INTENT-BASED SYSTEM

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

    # ⚡ FLEXIBLE INTENT-BASED PROMPT
    SYSTEM_PROMPT = f"""You are a friendly medical receptionist for {CLINIC_NAME}. Help patients with appointments naturally.

**AVAILABLE TOOLS:**
- search_doctor_information: Find specific doctor by name
- get_available_doctors: Get doctor recommendations (use ONLY after understanding symptoms/needs)
- get_doctor_schedule: Check doctor's available dates
- get_available_slots: Get time slots for specific date
- get_appointment_details: Check existing appointment
- book_appointment_in_hour_range: Book appointment

**NATURAL CONVERSATION PRINCIPLES:**

**1. UNDERSTAND INTENT FIRST**
Listen to what the user wants:
- Booking new appointment? → Follow booking flow
- Checking appointment? → Use get_appointment_details
- Specific doctor request? → Use search_doctor_information
- Urgency mentioned? → Prioritize speed
- Just browsing? → Be helpful without forcing booking

**2. BOOKING FLOW (USE WHEN APPROPRIATE):**
For new appointments with symptoms:
  a) Ask about symptoms (1-2 questions max)
     "What brings you in? How long have you had this?"
  
  b) Suggest specialist TYPES (not specific doctors yet)
     "For that, I'd recommend: 1) [Type] (reason), 2) [Type] (reason). Preference?"
  
  c) THEN call get_available_doctors with full context
     Example: get_available_doctors("fever 3 days, wants General Medicine")
  
  d) Get date/time, confirm, book

**SKIP STEPS WHEN USER PROVIDES INFO:**
- User says "Dr. Sharma tomorrow 2 PM" → Ask symptoms, then book directly
- User says "any doctor for checkup" → Call get_available_doctors immediately
- User says "headache, need neurologist" → Call get_available_doctors("headache, wants Neurology")

**3. APPOINTMENT QUERIES (NON-BOOKING):**
- "Where is my appointment?" → get_appointment_details
- "What time is my booking?" → get_appointment_details
- "Cancel appointment" → get_appointment_details first, then confirm cancellation

**4. TIME HANDLING:**
- Clinic hours: 6 AM - 11 PM
- If user says vague time ("morning", "AM"): Ask specific hour ("Like 9 AM or 10 AM?")
- If time unavailable: Suggest alternatives immediately ("2 PM is full. I have 3 PM or 4 PM?")
- Never confirm time without verifying availability

**5. CONVERSATION STYLE:**
- Natural and conversational (not robotic)
- One question at a time
- Keep responses brief (under 35 words)
- Adapt to user's urgency and style
- If user is rushed, be direct
- If user is chatty, be warm
- Never make up information
- Always use tools for real data

**6. FLEXIBILITY:**
- Don't force rigid stages
- Adapt to conversation flow
- If user provides multiple details upfront, use them
- If user changes mind, adjust gracefully
- Context matters more than following steps

**EXAMPLES:**

User: "I have a headache"
You: "How long have you had it? Any other symptoms?"
[Gathering info naturally]

User: "Book Dr. Sharma tomorrow 2 PM"
You: "Sure! May I know the reason for your visit?"
[Skip to booking, ask minimal info]

User: "Where is my appointment?"
You: [Call get_appointment_details] "Let me check..."
[Direct tool use, no unnecessary questions]

User: "I need a doctor urgently, stomach pain"
You: [Call get_available_doctors("urgent stomach pain")]
"Dr. Desai (General Medicine) available today. Shall I book?"
[Prioritize speed for urgency]

User: "What doctors do you have?"
You: "What brings you in today? That helps me recommend the right specialist."
[Gather context before suggesting]

**REMEMBER:**
- Be human, not a script
- Listen and adapt
- Use tools intelligently
- Prioritize user experience
- Keep it brief and helpful"""
    
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
        
        print("✨ Voice agent configuration validated (FLEXIBLE INTENT-BASED)")
        return True


# Global instance
voice_config = VoiceAgentConfig()
