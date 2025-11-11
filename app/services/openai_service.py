# app/services/openai_service.py - GPT-5 NANO + MINI OPTIMIZED

import openai
import json
from typing import Optional, List, Dict, Any, AsyncGenerator
from app.config.voice_config import voice_config
from datetime import datetime
from openai import AsyncOpenAI
import logging

logger = logging.getLogger("openai")
openai.api_key = voice_config.OPENAI_API_KEY


class OpenAIService:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=voice_config.OPENAI_API_KEY)
        
        # ⚡ DUAL MODEL STRATEGY
        self.fast_model = "gpt-5-nano"      # For simple queries (ULTRA FAST)
        self.smart_model = "gpt-5-mini"     # For tool calls (FAST + Smart)
        
        self.voice = voice_config.OPENAI_VOICE
        self.system_prompt = voice_config.SYSTEM_PROMPT
        
        logger.info(f"✨ OpenAI initialized: Fast={self.fast_model}, Smart={self.smart_model}")
    
    async def transcribe_audio(self, audio_file) -> Optional[str]:
        try:
            response = openai.audio.transcriptions.create(
                model=voice_config.OPENAI_STT_MODEL,
                file=audio_file,
                language="en"
            )
            return response.text
        except Exception as e:
            logger.error(f"Whisper transcription error: {e}")
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
            logger.error(f"TTS generation error: {e}")
            return None
    
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        functions: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.3,  # ⚡ OPTIMIZED: Lower = faster
        stream: bool = False,
        use_fast_model: bool = False  # ⚡ NEW: Choose model
    ):
        """
        ⚡ OPTIMIZED: Support both streaming and non-streaming + model selection
        """
        try:
            # ⚡ Choose model based on complexity
            model = self.fast_model if use_fast_model else self.smart_model
            
            params = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "stream": stream,
            }
            
            if functions:
                params["tools"] = [
                    {"type": "function", "function": func}
                    for func in functions
                ]
                params["tool_choice"] = "auto"
            
            response = await self.client.chat.completions.create(**params)
            return response
            
        except Exception as e:
            logger.error(f"Chat completion error: {e}")
            return None
    
    def build_conversation_messages(
        self,
        conversation_history: List[Dict[str, str]],
        include_system: bool = True,
        compress: bool = True  # ⚡ Compress long histories
    ) -> List[Dict[str, str]]:
        """
        ⚡ OPTIMIZED: Compress conversation history for faster responses
        """
        messages = []
        
        if include_system:
            current_date = datetime.now()
            current_date_str = current_date.strftime("%B %d, %Y")
            current_year = current_date.year
            day_of_week = current_date.strftime("%A")

            # ⚡ OPTIMIZED: Minimal system prompt
            enhanced_system_prompt = f"""{self.system_prompt}

Today: {day_of_week}, {current_date_str}
Year: {current_year}
Date format: YYYY-MM-DD"""
            
            messages.append({
                "role": "system",
                "content": enhanced_system_prompt
            })

        # ⚡ OPTIMIZED: Keep only last 8 messages if compress=True
        if compress and len(conversation_history) > 8:
            messages.extend(conversation_history[-8:])
        else:
            messages.extend(conversation_history)
        
        return messages
    
    async def chat_completion_streaming(
        self,
        messages: List[Dict[str, str]],
        functions: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.3,
        use_fast_model: bool = False
    ) -> AsyncGenerator[str, None]:
        """
        ⚡ OPTIMIZED: Streaming chat completion
        """
        try:
            model = self.fast_model if use_fast_model else self.smart_model
            
            params = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "stream": True,
            }
            
            # Note: Streaming doesn't work well with function calls
            if functions:
                params["tools"] = [
                    {"type": "function", "function": func}
                    for func in functions
                ]
                params["tool_choice"] = "auto"
                params["stream"] = False
                
                response = await self.client.chat.completions.create(**params)
                
                choice = response.choices[0]
                message = choice.message
                
                if choice.finish_reason == "tool_calls" and message.tool_calls:
                    yield json.dumps({
                        "type": "function_call",
                        "data": {
                            "name": message.tool_calls[0].function.name,
                            "arguments": json.loads(message.tool_calls[0].function.arguments),
                            "id": message.tool_calls[0].id
                        }
                    })
                else:
                    yield message.content
                return
            
            # ⚡ STREAMING MODE
            stream = await self.client.chat.completions.create(**params)
            
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                    
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            yield "I apologize, but I encountered an error."
    
    async def process_user_input(
        self,
        user_message: str,
        conversation_history: List[Dict[str, str]],
        available_functions: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        ⚡ OPTIMIZED: Use gpt-5-mini for tool detection
        """
        try:
            messages = self.build_conversation_messages(
                conversation_history,
                compress=True
            )
            messages.append({"role": "user", "content": user_message})

            # ⚡ Use smart model if functions available, else use fast model
            use_fast = (available_functions is None or len(available_functions) == 0)
            
            response = await self.chat_completion(
                messages=messages,
                functions=available_functions,
                temperature=0.3,
                use_fast_model=use_fast
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
            logger.error(f"Error processing user input: {e}")
            return {
                "response": "I apologize, but I encountered an error. Could you please try again?",
                "function_call": None,
                "finish_reason": "error"
            }

    async def generate_response_streaming(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        use_fast_model: bool = False  # ⚡ Allow model selection
    ) -> AsyncGenerator[str, None]:
        """
        ⚡ OPTIMIZED: Generate streaming response (for use AFTER tool execution)
        """
        try:
            model = self.fast_model if use_fast_model else self.smart_model
            
            stream = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                stream=True
            )
            
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                    
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            yield "I apologize, but I encountered an error."


# Global instance
openai_service = OpenAIService()
