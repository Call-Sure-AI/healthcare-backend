# app/services/openai_service.py - ULTRA OPTIMIZED

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
        temperature: float = 0.5,  # ⚡ OPTIMIZED: Lower temp = faster
        stream: bool = False
    ):
        """
        ⚡ OPTIMIZED: Support both streaming and non-streaming
        """
        try:
            params = {
                "model": self.model,
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
        compress: bool = True  # ⚡ NEW: Compress long histories
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

            # ⚡ OPTIMIZED: Shorter, more focused system prompt
            enhanced_system_prompt = f"""{self.system_prompt}

Today: {day_of_week}, {current_date_str}
Year: {current_year}
Date format: YYYY-MM-DD
If date is past, use {current_year + 1}
"""
            
            messages.append({
                "role": "system",
                "content": enhanced_system_prompt
            })

        # ⚡ OPTIMIZED: Keep only last 10 messages if compress=True
        if compress and len(conversation_history) > 10:
            messages.extend(conversation_history[-10:])
        else:
            messages.extend(conversation_history)
        
        return messages
    
    async def chat_completion_streaming(
        self,
        messages: List[Dict[str, str]],
        functions: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.5
    ) -> AsyncGenerator[str, None]:
        """
        ⚡ NEW: Streaming chat completion that yields tokens as they arrive
        Returns: AsyncGenerator that yields text chunks
        """
        try:
            params = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "stream": True,  # ⚡ CRITICAL: Enable streaming
            }
            
            # Note: Streaming doesn't work with function calls
            # We'll handle this in voice_agent_service
            if functions:
                params["tools"] = [
                    {"type": "function", "function": func}
                    for func in available_functions
                ]
                params["tool_choice"] = "auto"
                # Disable streaming if functions present
                params["stream"] = False
                
                response = await self.client.chat.completions.create(**params)
                
                # Return non-streaming response
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
        ⚡ OPTIMIZED: Faster temperature + compression
        """
        try:
            messages = self.build_conversation_messages(
                conversation_history,
                compress=True  # ⚡ Enable compression
            )
            messages.append({"role": "user", "content": user_message})

            response = await self.chat_completion(
                messages=messages,
                functions=available_functions,
                temperature=0.5  # ⚡ OPTIMIZED: Lower = faster
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
        temperature: float = 0.5
    ) -> AsyncGenerator[str, None]:
        """
        ⚡ NEW: Generate streaming response (for use AFTER tool execution)
        No function calls - just pure text generation
        """
        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                stream=True  # ⚡ CRITICAL
            )
            
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                    
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            yield "I apologize, but I encountered an error."


# Global instance
openai_service = OpenAIService()
