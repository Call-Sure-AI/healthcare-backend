# app/services/voice_agent_service.py

from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from datetime import datetime
from app.services.redis_service import redis_service
from app.services.doctor_service import DoctorService
from app.services.openai_service import openai_service
from app.services.twilio_service import twilio_service
from app.routes.ai_tools import AIToolsExecutor, get_ai_functions
from app.utils.validators import validate_phone_number, parse_patient_name
from app.models.call_session import CallSession
from app.config.voice_config import voice_config
from collections import defaultdict
import logging
from datetime import datetime
import traceback
import json
import time

logger = logging.getLogger("agent")

class VoiceAgentService:
    def __init__(self, db: Session):
        self.db = db
        self.ai_tools = AIToolsExecutor(db)
    
    async def initiate_call(self, call_sid: str, from_number: str, to_number: str) -> Dict[str, Any]:
        try:
            session_data = {
                "call_sid": call_sid,
                "from_number": from_number,
                "to_number": to_number,
                "status": "initiated",
                "current_step": "greeting",
                "conversation_history": [],
                "patient_name": None,
                "patient_phone": None,
                "selected_doctor_id": None,
                "selected_date": None,
                "selected_time": None,
                "reason": None,
                "appointment_id": None
            }
            
            redis_service.create_session(call_sid, session_data)

            db_session = CallSession(
                call_sid=call_sid,
                from_number=from_number,
                to_number=to_number,
                status="in_progress"
            )
            self.db.add(db_session)
            self.db.commit()
            
            logger.debug(f"Call initiated: {call_sid}")
            return {"success": True, "call_sid": call_sid}
            
        except Exception as e:
            logger.error(f"Error initiating call: {e}")
            return {"success": False, "error": str(e)}

    async def process_user_speech(
        self, 
        call_sid: str, 
        user_text: str,
        metrics: 'LatencyMetrics' = None
    ) -> Dict[str, Any]:

        try:
            redis_service.append_to_conversation(call_sid, "user", user_text)
            session = redis_service.get_session(call_sid)
            
            if not session:
                return {"success": False, "response": "Session not found."}
            
            conversation_history = session.get("conversation_history", [])
            ai_functions_schema = get_ai_functions()
            
            if metrics:
                metrics.llm_request_start = time.time()
            
            first_response = await openai_service.process_user_input(
                user_message=user_text,
                conversation_history=conversation_history,
                available_functions=ai_functions_schema,
            )
            
            if metrics:
                metrics.llm_first_response = time.time()
                llm_ms = (metrics.llm_first_response - metrics.llm_request_start) * 1000
                logger.info(f"   LLM: {llm_ms:.0f}ms")
            
            if not first_response:
                return {"success": False, "response": "I'm having trouble understanding."}

            # Handle function call
            if first_response.get("function_call"):
                function_call = first_response["function_call"]
                function_name = function_call["name"]
                function_args = function_call["arguments"]
                tool_call_id = function_call["id"]

                logger.info(f"   🔧 Tool: {function_name}")
                
                if metrics:
                    metrics.tool_name = function_name
                    metrics.tool_execution_start = time.time()
                
                # ⚡ FIX: Store the tool call message properly
                # Store the assistant message with tool_calls in the conversation
                session = redis_service.get_session(call_sid)
                if session:
                    conversation_history = session.get("conversation_history", [])
                    
                    # Add assistant message with tool call
                    conversation_history.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": tool_call_id,
                            "type": "function",
                            "function": {
                                "name": function_name,
                                "arguments": json.dumps(function_args)
                            }
                        }]
                    })
                    
                    redis_service.update_session(call_sid, {"conversation_history": conversation_history})
                
                # Execute function
                function_result = self.ai_tools.execute_function(function_name, function_args)
                
                if metrics:
                    metrics.tool_execution_end = time.time()
                    tool_ms = (metrics.tool_execution_end - metrics.tool_execution_start) * 1000
                    logger.info(f"   Tool exec: {tool_ms:.0f}ms")
                
                # ⚡ FIX: Store the tool result properly
                session = redis_service.get_session(call_sid)
                if session:
                    conversation_history = session.get("conversation_history", [])
                    
                    # Add tool result message
                    conversation_history.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": function_name,
                        "content": json.dumps(function_result)
                    })
                    
                    redis_service.update_session(call_sid, {"conversation_history": conversation_history})
                
                # Second LLM call with updated history
                session = redis_service.get_session(call_sid)
                updated_history = session.get("conversation_history", [])
                
                if metrics:
                    metrics.llm2_request_start = time.time()
                
                final_response = await openai_service.chat_completion(
                    messages=openai_service.build_conversation_messages(updated_history, include_system=True),
                )
                
                if metrics:
                    metrics.llm2_complete = time.time()
                    llm2_ms = (metrics.llm2_complete - metrics.llm2_request_start) * 1000
                    logger.info(f"   LLM2: {llm2_ms:.0f}ms")
                
                if final_response and final_response.choices:
                    response_text = final_response.choices[0].message.content
                    redis_service.append_to_conversation(call_sid, "assistant", response_text)
                    success = True
                else:
                    response_text = self._generate_fallback_response(function_name, function_result)
                    redis_service.append_to_conversation(call_sid, "assistant", response_text)
                    success = False
                
                if metrics:
                    metrics.llm_complete = time.time()
                
                return {
                    "success": success,
                    "response": response_text,
                    "function_called": True,
                    "function_name": function_name,
                    "function_result": function_result
                }
            
            else:
                # Direct response
                response_text = first_response.get("response") or "I'm sorry, I didn't quite understand."
                redis_service.append_to_conversation(call_sid, "assistant", response_text)
                
                if metrics:
                    metrics.llm_complete = time.time()
                
                return {
                    "success": True,
                    "response": response_text,
                    "function_called": False
                }

        except Exception as e:
            logger.error(f"❌ Error: {e}", exc_info=True)
            fallback = "I apologize, I encountered an error."
            
            try:
                redis_service.append_to_conversation(call_sid, "assistant", fallback)
            except:
                pass
            
            return {"success": False, "error": str(e), "response": fallback}

    def _generate_fallback_response(self, function_name: str, result: Dict[str, Any]) -> str:
        """Generates a simple text response if the second LLM call fails after a tool call."""
        logger.warning(f"Generating fallback response for failed generation after tool '{function_name}'")
        if result.get("success"):
            if function_name == "get_available_doctors":
                count = result.get("count", 0)
                return f"I found {count} doctor(s) matching your request. Could you specify who you'd like?" if count else "I couldn't find any matching doctors right now."
            elif function_name == "get_available_slots":
                 count = result.get("count", 0)
                 return f"I found {count} available time slots for that date. Which time would work?" if count else "No slots seem to be available on that date."
            elif function_name == "book_appointment_in_hour_range":
                appt = result.get("appointment", {})
                return f"Okay, the appointment for {appt.get('patient_name')} is booked for {appt.get('appointment_date')} at {appt.get('appointment_time')}. Confirmation {appt.get('confirmation_number')}."
            elif function_name == "search_doctor_information":
                count = len(result.get("results", []))
                return f"I found {count} piece(s) of information related to your query. How can I help further?" if count else "I couldn't find specific details for that."
            else:
                return "I've processed your request. Is there anything else?"
        else:
            error = result.get("error", "there was an issue")
            return f"I encountered a problem trying to {function_name.replace('_', ' ')}: {error}. Please try again."
    
    def _resolve_doctor_id(self, input_id: str, available_doctors: List[Dict]) -> str:
        try:
            if not input_id or not available_doctors:
                return None
                
            input_str = str(input_id).lower().strip()

            try:
                index = int(input_str) - 1
                if 0 <= index < len(available_doctors):
                    return available_doctors[index]["doctor_id"]
            except ValueError:
                pass

            input_clean = input_str.replace('dr.', '').replace('dr', '').replace('doctor', '').strip()

            for doctor in available_doctors:
                doctor_name_lower = doctor["name"].lower()
                if doctor_name_lower == input_clean or doctor_name_lower.replace('dr.', '').replace('dr', '').strip() == input_clean:
                    logger.debug(f"Exact name match: {doctor['name']}")
                    return doctor["doctor_id"]

            for doctor in available_doctors:
                doctor_name_lower = doctor["name"].lower()
                doctor_name_parts = doctor_name_lower.replace('dr.', '').replace('dr', '').split()
                input_parts = input_clean.split()

                for input_part in input_parts:
                    if len(input_part) > 2:
                        for name_part in doctor_name_parts:
                            if input_part in name_part or name_part in input_part:
                                logger.debug(f"Partial match: {doctor['name']}")
                                return doctor["doctor_id"]
            
            logger.debug(f"No match found for '{input_id}'")
            return None
            
        except Exception as e:
            logger.error(f"Error resolving doctor ID: {e}")
            return None

    async def _update_session_from_function(
        self,
        call_sid: str,
        function_name: str,
        arguments: Dict[str, Any],
        result: Dict[str, Any]
    ):
        updates = {}
        
        if function_name == "book_appointment" and result.get("success"):
            updates.update({
                "patient_name": arguments.get("patient_name"),
                "patient_phone": arguments.get("patient_phone"),
                "selected_doctor_id": arguments.get("doctor_id"),
                "selected_date": arguments.get("appointment_date"),
                "selected_time": arguments.get("appointment_time"),
                "reason": arguments.get("reason", ""),
                "appointment_id": result.get("appointment_id"),
                "status": "completed",
                "current_step": "confirmed"
            })
        
        if updates:
            redis_service.update_session(call_sid, updates)

    def _group_slots_by_hour(self, slots: List[str]) -> Dict[int, List[str]]:
        hourly_slots = defaultdict(list)
        for slot in slots:
            try:
                hour = int(slot.split(':')[0])
                hourly_slots[hour].append(slot)
            except (ValueError, IndexError):
                logger.warning(f"Could not parse slot '{slot}'")
        return dict(sorted(hourly_slots.items()))

    async def end_call(self, call_sid: str) -> Dict[str, Any]:
        try:
            session = redis_service.get_session(call_sid)

            db_session = self.db.query(CallSession).filter(
                CallSession.call_sid == call_sid
            ).first()
            
            if db_session and session:
                db_session.status = session.get("status", "completed")
                db_session.patient_name = session.get("patient_name")
                db_session.patient_phone = session.get("patient_phone")
                db_session.appointment_id = session.get("appointment_id")
                db_session.conversation_history = session.get("conversation_history", [])
                db_session.ended_at = datetime.now()
                db_session.is_booking_confirmed = session.get("appointment_id") is not None
                
                self.db.commit()

            if session and session.get("appointment_id") and voice_config.ENABLE_SMS_CONFIRMATION:
                await self._send_confirmation_sms(session)

            redis_service.delete_session(call_sid)
            
            logger.debug(f"Call ended: {call_sid}")
            return {"success": True}
            
        except Exception as e:
            logger.error(f"Error ending call: {e}")
            return {"success": False, "error": str(e)}
    
    async def _send_confirmation_sms(self, session: Dict[str, Any]):
        try:
            phone = session.get("patient_phone")
            if not phone:
                return

            is_valid, formatted_phone = validate_phone_number(phone)
            if not is_valid:
                logger.warning(f"Invalid phone number: {phone}")
                return

            appointment_id = session.get("appointment_id")
            patient_name = session.get("patient_name", "Patient")
            doctor_id = session.get("selected_doctor_id", "")
            date = session.get("selected_date", "")
            time = session.get("selected_time", "")

            doctor = DoctorService.get_doctor_by_id(self.db, doctor_id)
            doctor_name = doctor.name if doctor else "Doctor"

            twilio_service.send_appointment_confirmation_sms(
                to_number=formatted_phone,
                patient_name=patient_name,
                doctor_name=doctor_name,
                date=date,
                time=time,
                appointment_id=appointment_id
            )
            
            logger.info(f"Confirmation SMS sent to {formatted_phone}")
            
        except Exception as e:
            logger.error(f"Error sending SMS: {e}")

    def _extract_doctor_from_speech(self, user_text: str, available_doctors: List[Dict]) -> str:
        user_lower = user_text.lower()

        ordinals = {
            'first': 0, '1st': 0, 'one': 0,
            'second': 1, '2nd': 1, 'two': 1,
            'third': 2, '3rd': 2, 'three': 2
        }
        
        for word, index in ordinals.items():
            if word in user_lower and index < len(available_doctors):
                return available_doctors[index]["doctor_id"]

        for doctor in available_doctors:
            name_parts = doctor["name"].lower().split()
            for part in name_parts:
                if len(part) > 2 and part in user_lower:
                    return doctor["doctor_id"]
        
        return None
