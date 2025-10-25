import openai
import json
from typing import Optional, List, Dict, Any
from app.config.voice_config import voice_config
from datetime import datetime

openai.api_key = voice_config.OPENAI_API_KEY


class OpenAIService:
    def __init__(self):
        self.model = voice_config.OPENAI_MODEL
        self.voice = voice_config.OPENAI_VOICE
        self.system_prompt = voice_config.SYSTEM_PROMPT
    
    async def transcribe_audio(self, audio_file) -> Optional[str]:
        try:
            response = openai.audio.transcriptions.create(
                model=voice_config.OPENAI_STT_MODEL,
                file=audio_file,
                language="en"
            )
            return response.text
        except Exception as e:
            print(f"Whisper transcription error: {e}")
            return None
    
    async def generate_speech(self, text: str) -> Optional[bytes]:
        try:
            response = openai.audio.speech.create(
                model=voice_config.OPENAI_TTS_MODEL,
                voice=self.voice,
                input=text,
                speed=1.0
            )
            return response.content
        except Exception as e:
            print(f"TTS generation error: {e}")
            return None
    
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        functions: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7
    ) -> Optional[Dict[str, Any]]:
        try:
            params = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
            }
            
            if functions:
                params["tools"] = [
                    {"type": "function", "function": func}
                    for func in functions
                ]
                params["tool_choice"] = "auto"
            
            response = openai.chat.completions.create(**params)
            return response
        except Exception as e:
            print(f"Chat completion error: {e}")
            return None
    
    def build_conversation_messages(
        self,
        conversation_history: List[Dict[str, str]],
        include_system: bool = True
    ) -> List[Dict[str, str]]:
        messages = []
        
        if include_system:
            current_date = datetime.now()
            current_date_str = current_date.strftime("%B %d, %Y")
            current_year = current_date.year
            day_of_week = current_date.strftime("%A")

            enhanced_system_prompt = f"""{self.system_prompt}

    IMPORTANT DATE INFORMATION:
    - Today is {day_of_week}, {current_date_str}
    - Current year: {current_year}
    - When users mention dates without a year (e.g., "October 29" or "29th October"), assume they mean {current_year}
    - If a date would be in the past (e.g., user says "October 20" but today is October 25), assume they mean {current_year + 1}
    - ALWAYS format dates as YYYY-MM-DD in function calls
    - Example: User says "October 29" → Use "{current_year}-10-29" in the date field
    - Example: User says "29th October" → Use "{current_year}-10-29" in the date field

    Remember: You are helping patients book medical appointments. Be professional, warm, and verify all details before confirming bookings.
    """
            
            messages.append({
                "role": "system",
                "content": enhanced_system_prompt
            })

        messages.extend(conversation_history)
        
        return messages
    
    async def process_user_input(
        self,
        user_message: str,
        conversation_history: List[Dict[str, str]],
        available_functions: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        try:
            messages = self.build_conversation_messages(conversation_history)
            messages.append({"role": "user", "content": user_message})

            response = await self.chat_completion(
                messages=messages,
                functions=available_functions
            )
            
            if not response:
                return {
                    "response": "I'm sorry, I'm having trouble processing that. Could you please repeat?",
                    "function_call": None,
                    "finish_reason": "error"
                }
            
            choice = response.choices[0]
            message = choice.message
            
            result = {
                "finish_reason": choice.finish_reason,
                "function_call": None,
                "response": None
            }

            if choice.finish_reason == "tool_calls" and message.tool_calls:
                tool_call = message.tool_calls[0]
                result["function_call"] = {
                    "name": tool_call.function.name,
                    "arguments": json.loads(tool_call.function.arguments),
                    "id": tool_call.id
                }
            else:
                result["response"] = message.content
            
            return result
            
        except Exception as e:
            print(f"Error processing user input: {e}")
            return {
                "response": "I apologize, but I encountered an error. Could you please try again?",
                "function_call": None,
                "finish_reason": "error"
            }


# Open AI Global instance
openai_service = OpenAIService()
