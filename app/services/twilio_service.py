from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather, Say
from typing import Optional
from app.config.voice_config import voice_config


class TwilioService:
    """Service for Twilio Voice operations"""
    
    def __init__(self):
        self.account_sid = voice_config.TWILIO_ACCOUNT_SID
        self.auth_token = voice_config.TWILIO_AUTH_TOKEN
        self.phone_number = voice_config.TWILIO_PHONE_NUMBER
        self.client = Client(self.account_sid, self.auth_token)
    
    def create_welcome_response(self, websocket_url: str) -> str:
        """
        Create initial TwiML response with WebSocket stream
        """
        response = VoiceResponse()

        response.start().stream(
            url=websocket_url,
            track="both_tracks"
        )

        response.say(
            f"Hello! Thank you for calling {voice_config.CLINIC_NAME}. "
            "I'm here to help you book an appointment. How may I assist you today?",
            voice="Polly.Aditi",  # Indian English voice
            language="en-IN"
        )

        response.pause(length=2)
        
        return str(response)
    
    def create_gather_response(self, text: str, action_url: str) -> str:
        """
        Create TwiML response with speech gathering
        """
        response = VoiceResponse()
        
        gather = Gather(
            input='speech',
            action=action_url,
            language='en-IN',
            speech_timeout='auto',
            speech_model='experimental_conversations'
        )
        
        gather.say(
            text,
            voice="Polly.Aditi",
            language="en-IN"
        )
        
        response.append(gather)

        response.say(
            "I didn't catch that. Could you please repeat?",
            voice="Polly.Aditi",
            language="en-IN"
        )
        response.redirect(action_url)
        
        return str(response)
    
    def create_say_response(self, text: str, hangup: bool = False) -> str:
        """
        Create simple say response
        """
        response = VoiceResponse()
        
        response.say(
            text,
            voice="Polly.Aditi",
            language="en-IN"
        )
        
        if hangup:
            response.hangup()
        
        return str(response)
    
    def send_sms(self, to_number: str, message: str) -> bool:
        """
        Send SMS confirmation
        """
        try:
            message = self.client.messages.create(
                body=message,
                from_=self.phone_number,
                to=to_number
            )
            print(f"✅ SMS sent: {message.sid}")
            return True
        except Exception as e:
            print(f"❌ SMS send error: {e}")
            return False
    
    def send_appointment_confirmation_sms(
        self,
        to_number: str,
        patient_name: str,
        doctor_name: str,
        date: str,
        time: str,
        appointment_id: int
    ) -> bool:
        """
        Send appointment confirmation SMS
        """
        message = f"""Hi {patient_name}!

Your appointment is confirmed:

Doctor: Dr. {doctor_name}
Date: {date}
Time: {time}
Confirmation: APT-{appointment_id}

Address: {voice_config.CLINIC_ADDRESS}

Reply CANCEL to cancel.

- {voice_config.CLINIC_NAME}"""
        
        return self.send_sms(to_number, message)
    
    def get_call_details(self, call_sid: str) -> Optional[dict]:
        """
        Get call details from Twilio
        """
        try:
            call = self.client.calls(call_sid).fetch()
            return {
                "sid": call.sid,
                "from": call.from_,
                "to": call.to,
                "status": call.status,
                "duration": call.duration,
                "start_time": call.start_time,
                "end_time": call.end_time
            }
        except Exception as e:
            print(f"Error fetching call details: {e}")
            return None
    
    def end_call(self, call_sid: str) -> bool:
        """
        End an active call
        """
        try:
            self.client.calls(call_sid).update(status='completed')
            return True
        except Exception as e:
            print(f"Error ending call: {e}")
            return False


# Global instance
twilio_service = TwilioService()
