import openai
import json
from typing import Optional, List, Dict, Any
from app.config.voice_config import voice_config


openai.api_key = voice_config.OPENAI_API_KEY


class OpenAIService:
    """Service for OpenAI API interactions"""
    
    def __init__(self):
        self.model = voice_config.OPENAI_MODEL
        self.voice = voice_config.OPENAI_VOICE
        self.system_prompt = voice_config.SYSTEM_PROMPT
    
    async def transcribe_audio(self, audio_file) -> Optional[str]:
        """
        Transcribe audio using Whisper API
        """
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
        """
        Generate speech using OpenAI TTS
        """
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
        """
        Get chat completion from GPT-4
        """
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
        """
        Build messages array for GPT-4
        """
        messages = []
        
        if include_system:
            messages.append({
                "role": "system",
                "content": self.system_prompt
            })

        messages.extend(conversation_history)
        
        return messages
    
    async def process_user_input(
        self,
        user_message: str,
        conversation_history: List[Dict[str, str]],
        available_functions: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Process user input and generate response
        Returns: {
            "response": "text response",
            "function_call": {...} or None,
            "finish_reason": "stop" | "tool_calls"
        }
        """
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


# Global instance
openai_service = OpenAIService()
