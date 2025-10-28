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

logger = logging.getLogger(__name__)

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
            
            print(f"Call initiated: {call_sid}")
            return {"success": True, "call_sid": call_sid}
            
        except Exception as e:
            print(f"Error initiating call: {e}")
            return {"success": False, "error": str(e)}
            
    
    async def process_user_speech(self, call_sid: str, user_text: str) -> Dict[str, Any]:
        start_time = time.time()
        logger.info(f"\n{'='*80}")
        logger.info(f"Processing speech for Call SID: {call_sid}")
        logger.info(f"User input: '{user_text}'")

        try:
            redis_service.append_to_conversation(call_sid, "user", user_text)

            session = redis_service.get_session(call_sid)
            if not session:
                logger.error(f"No session found for {call_sid}")
                return {
                    "success": False,
                    "error": "Session not found",
                    "response": "I seem to have lost our connection. Could you please start over?"
                }
            conversation_history = session.get("conversation_history", [])
            logger.info(f"Current conversation length: {len(conversation_history)} messages")

            logger.info("--- RAG Step 1: Requesting Tool Call or Direct Response ---")
            ai_functions_schema = get_ai_functions()
            first_llm_response = await openai_service.process_user_input(
                user_message=user_text,
                conversation_history=conversation_history,
                available_functions=ai_functions_schema,
            )

            if not first_llm_response:
                 logger.error("First LLM call failed.")
                 return {
                    "success": False, "error": "LLM interaction failed",
                    "response": "I'm having trouble understanding right now. Please try again."
                 }

            if first_llm_response.get("function_call"):
                function_call = first_llm_response.get("function_call", {})
                function_name = function_call.get("name")
                function_args = function_call.get("arguments", {})
                tool_call_id = function_call.get("id")

                logger.info(f"LLM decided to call tool: {function_name}")
                logger.debug(f"Tool Call ID: {tool_call_id}")
                logger.debug(f"Arguments: {function_args}")

                tool_call_assistant_message = {
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
                }
                redis_service.append_to_conversation(call_sid, "assistant", tool_call_assistant_message)

                function_result_data = self.ai_tools.execute_function(
                    function_name,
                    function_args
                )
                logger.info(f"Tool '{function_name}' executed. Success: {function_result_data.get('success', 'N/A')}")

                tool_result_message = {
                    "tool_call_id": tool_call_id,
                    "role": "tool",
                    "name": function_name,
                    "content": json.dumps(function_result_data),
                }
                redis_service.append_to_conversation(call_sid, "tool", tool_result_message)

                logger.info(f"--- RAG Step 2: Generating Response using result of '{function_name}' ---")
                session = redis_service.get_session(call_sid)
                updated_history = session.get("conversation_history", [])

                final_llm_response_obj = await openai_service.chat_completion(
                    messages=openai_service.build_conversation_messages(updated_history, include_system=True),
                )

                if final_llm_response_obj and final_llm_response_obj.choices:
                    final_response_text = final_llm_response_obj.choices[0].message.content
                    logger.info(f"Final Response (after tool call): '{final_response_text[:100]}...'")
                    redis_service.append_to_conversation(call_sid, "assistant", final_response_text)
                    success = True
                else:
                    logger.error("Second LLM call (after tool execution) failed.")
                    final_response_text = self._generate_fallback_response(function_name, function_result_data)
                    redis_service.append_to_conversation(call_sid, "assistant", final_response_text)
                    success = False

                duration = time.time() - start_time
                logger.info(f"Processing complete (Tool Call Path). Duration: {duration:.2f}s")
                logger.info(f"{'='*80}\n")

                return {
                    "success": success,
                    "response": final_response_text,
                    "function_called": True,
                    "function_name": function_name,
                    "function_result": function_result_data
                }

            else:
                response_text = first_llm_response.get("response")
                if not response_text:
                     logger.error("First LLM call returned no response text and no tool call.")
                     response_text = "I'm sorry, I didn't quite understand. Could you rephrase?"

                logger.info(f"Direct AI Response (No Tool Call): '{response_text[:100]}...'")
                redis_service.append_to_conversation(call_sid, "assistant", response_text)
                duration = time.time() - start_time
                logger.info(f"Processing complete (Direct Response Path). Duration: {duration:.2f}s")
                logger.info(f"{'='*80}\n")
                return {
                    "success": True,
                    "response": response_text,
                    "function_called": False
                }

        except Exception as e:
            logger.error(f"!!! Critical error in process_user_speech for {call_sid}: {e}", exc_info=True)
            traceback.print_exc()
            fallback_response = "I apologize, I encountered an unexpected issue. Please try again later."
            try:
                redis_service.append_to_conversation(call_sid, "assistant", fallback_response + f" (System Error: {e})")
            except:
                pass
            return {
                "success": False,
                "error": str(e),
                "response": fallback_response
            }

    def _generate_fallback_response(self, function_name: str, result: Dict[str, Any]) -> str:
        """Generates a simple text response if the second LLM call fails after a tool call."""
        logger.warning(f"Generating fallback response for failed generation after tool '{function_name}'")
        if result.get("success"):
            # minimal useful response based on the successful tool call
            if function_name == "get_available_doctors":
                count = result.get("count", 0)
                return f"I found {count} doctor(s) matching your request. Could you specify who you'd like?" if count else "I couldn't find any matching doctors right now."
            elif function_name == "get_available_slots":
                 count = result.get("count", 0)
                 return f"I found {count} available time slots for that date. Which time would work?" if count else "No slots seem to be available on that date."
            elif function_name == "book_appointment_in_hour_range":
                # Booking succeeded, but generation failed
                appt = result.get("appointment", {})
                return f"Okay, the appointment for {appt.get('patient_name')} is booked for {appt.get('appointment_date')} at {appt.get('appointment_time')}. Confirmation {appt.get('confirmation_number')}."
            elif function_name == "search_doctor_information":
                count = len(result.get("results", []))
                return f"I found {count} piece(s) of information related to your query. How can I help further?" if count else "I couldn't find specific details for that."
            else:
                return "I've processed your request. Is there anything else?"
        else:
            # Tool call failed
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
                    print(f"   🎯 Exact name match: {doctor['name']}")
                    return doctor["doctor_id"]

            for doctor in available_doctors:
                doctor_name_lower = doctor["name"].lower()
                doctor_name_parts = doctor_name_lower.replace('dr.', '').replace('dr', '').split()
                input_parts = input_clean.split()

                for input_part in input_parts:
                    if len(input_part) > 2:
                        for name_part in doctor_name_parts:
                            if input_part in name_part or name_part in input_part:
                                print(f"Partial match: {doctor['name']} (matched '{input_part}')")
                                return doctor["doctor_id"]
            
            print(f"No match found for '{input_id}'")
            return None
            
        except Exception as e:
            print(f"Error resolving doctor ID: {e}")
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
                print(f"Warning: Could not parse slot '{slot}'")
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
            
            print(f"Call ended: {call_sid}")
            return {"success": True}
            
        except Exception as e:
            print(f"Error ending call: {e}")
            return {"success": False, "error": str(e)}
    
    async def _send_confirmation_sms(self, session: Dict[str, Any]):
        try:
            phone = session.get("patient_phone")
            if not phone:
                return

            is_valid, formatted_phone = validate_phone_number(phone)
            if not is_valid:
                print(f"Invalid phone number: {phone}")
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
            
            print(f"Confirmation SMS sent to {formatted_phone}")
            
        except Exception as e:
            print(f"Error sending SMS: {e}")

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
