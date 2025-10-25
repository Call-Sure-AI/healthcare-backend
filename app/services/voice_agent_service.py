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

logger = logging.getLogger(__name__)

class VoiceAgentService:
    """Main service for handling voice agent conversations"""
    
    def __init__(self, db: Session):
        self.db = db
        self.ai_tools = AIToolsExecutor(db)
    
    async def initiate_call(self, call_sid: str, from_number: str, to_number: str) -> Dict[str, Any]:
        """Initialize a new call session"""
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
        """Process user speech and generate AI response"""
        try:
            import time
            logger.info(f"\n{'='*80}")
            logger.info(f"💬 Processing speech: '{user_text}'")
            logger.info(f"   Call SID: {call_sid}")
            start_time = time.time()

            # ============ CRITICAL: Add user message to history FIRST ============
            redis_service.append_to_conversation(call_sid, "user", user_text)
            logger.info(f"✓ Added user message to conversation history")
            
            # Get updated session (now includes the user message)
            session = redis_service.get_session(call_sid)
            if not session:
                logger.error(f"❌ No session found for {call_sid}")
                return {
                    "success": False,
                    "error": "Session not found",
                    "response": "I'm sorry, I lost track of our conversation. Could you start again?"
                }

            # ============ AUTO-DETECT DOCTOR FROM PREVIOUS CONTEXT ============
            user_lower = user_text.lower()
            available_doctors = session.get("available_doctors", [])
            
            doctor_detected = False  # ← Track if we detected a doctor

            if available_doctors:
                for doctor in available_doctors:
                    doctor_name = doctor["name"].lower()
                    name_parts = doctor_name.replace('dr.', '').replace('dr', '').split()

                    for part in name_parts:
                        if len(part) > 2 and part in user_lower:
                            redis_service.update_session(call_sid, {
                                "selected_doctor_id": doctor["doctor_id"],
                                "selected_doctor_name": doctor["name"]
                            })
                            logger.info(f"Auto detected doctor: {doctor['name']} ({doctor['doctor_id']})")
                            doctor_detected = True
                            break
                    
                    if doctor_detected:
                        break
            
            # ============ CRITICAL: Refresh session if doctor was detected ============
            if doctor_detected:
                session = redis_service.get_session(call_sid)
                logger.info(f"✓ Refreshed session after auto-detection")

            # ============ GET CONVERSATION HISTORY AND CALL OPENAI ============
            conversation_history = session.get("conversation_history", [])
            logger.info(f"📋 Conversation history: {len(conversation_history)} messages")
            
            ai_functions = get_ai_functions()
            result = await openai_service.process_user_input(
                user_message=user_text,
                conversation_history=conversation_history,
                available_functions=ai_functions,
            )

            # ============ HANDLE FUNCTION CALLS ============
            if result.get("function_call"):
                logger.info(f"🔧 Function call detected: {result.get('function_call', {}).get('name')}")
                
                # ============ CRITICAL: Get fresh session before function call ============
                session = redis_service.get_session(call_sid)
                
                function_result = await self._handle_function_call(call_sid, result, session)
                
                duration = time.time() - start_time
                logger.info(f"✓ Function call processing complete ({duration:.2f}s)")
                logger.info(f"{'='*80}\n")
                
                return function_result

            # ============ HANDLE REGULAR RESPONSE ============
            response_text = result.get("response", "I'm sorry, could you please repeat that?")
            logger.info(f"💬 AI Response: '{response_text[:100]}...'")

            # Add assistant response to conversation
            redis_service.append_to_conversation(call_sid, "assistant", response_text)

            duration = time.time() - start_time
            logger.info(f"✓ Speech processing complete ({duration:.2f}s)")
            logger.info(f"{'='*80}\n")

            return {
                "success": True,
                "response": response_text,
                "function_called": False
            }
            
        except Exception as e:
            logger.error(f"❌ Error processing speech: {e}")
            logger.error(f"   User text was: '{user_text}'")
            import traceback
            traceback.print_exc()
            
            return {
                "success": False,
                "error": str(e),
                "response": "I apologize, but I'm having trouble processing that. Could you please try again?"
            }

    
    def _resolve_doctor_id(self, input_id: str, available_doctors: List[Dict]) -> str:
        """
        Resolve doctor ID from various inputs:
        - Number like "1" -> first doctor
        - Name like "Amit Kumar" -> match doctor name
        - Partial name -> fuzzy match
        """
        try:
            if not input_id or not available_doctors:
                return None
                
            input_str = str(input_id).lower().strip()
            
            # Try to parse as index (1, 2, 3...)
            try:
                index = int(input_str) - 1
                if 0 <= index < len(available_doctors):
                    return available_doctors[index]["doctor_id"]
            except ValueError:
                pass
            
            # Remove common prefixes
            input_clean = input_str.replace('dr.', '').replace('dr', '').replace('doctor', '').strip()
            
            # Try exact name match first
            for doctor in available_doctors:
                doctor_name_lower = doctor["name"].lower()
                if doctor_name_lower == input_clean or doctor_name_lower.replace('dr.', '').replace('dr', '').strip() == input_clean:
                    print(f"   🎯 Exact name match: {doctor['name']}")
                    return doctor["doctor_id"]
            
            # Try partial name match (any word matches)
            for doctor in available_doctors:
                doctor_name_lower = doctor["name"].lower()
                doctor_name_parts = doctor_name_lower.replace('dr.', '').replace('dr', '').split()
                input_parts = input_clean.split()
                
                # Check if any significant word matches
                for input_part in input_parts:
                    if len(input_part) > 2:  # Ignore short words like "dr"
                        for name_part in doctor_name_parts:
                            if input_part in name_part or name_part in input_part:
                                print(f"   🎯 Partial match: {doctor['name']} (matched '{input_part}')")
                                return doctor["doctor_id"]
            
            print(f"No match found for '{input_id}'")
            return None
            
        except Exception as e:
            print(f"Error resolving doctor ID: {e}")
            return None


    def _generate_response_from_function_result(
        self,
        function_name: str,
        result: Dict[str, Any]
    ) -> str:
        """Generate natural language response from function result"""
        
        if function_name == "get_available_doctors":
            if result.get("success"):
                doctors = result.get("doctors", [])
                specialization = result.get("specialization_detected")
                
                if not doctors:
                    return "I'm sorry, no doctors are currently available. Would you like me to help you with something else?"
                
                # Build response based on specialization detection
                prefix = ""
                if specialization:
                    prefix = f"Based on your symptoms, I found {len(doctors)} {specialization} specialist{'s' if len(doctors) > 1 else ''}. "
                    
                # Format doctor list (max 5)
                if len(doctors) == 1:
                    doc = doctors[0]
                    degree = doc.get("degree", "")
                    spec = doc.get("specialization", "General Medicine")
                
                    return f"{prefix}We have {doc['name']}, {degree}, specializing in {spec}. Would you like to book an appointment?"
            
                
                elif len(doctors) == 2:
                    desc1 = f"{doc1['name']}, {doc1.get('degree', '')}, {doc1.get('specialization', 'General Medicine')}"
                    desc2 = f"{doc2['name']}, {doc2.get('degree', '')}, {doc2.get('specialization', 'General Medicine')}"
                
                    return f"{prefix}We have {desc1} and {desc2} available. Which doctor would you prefer?"
            
                
                elif len(doctors) <= 5:
                    doctor_descriptions = []
                    for doc in doctors[:-1]:
                        degree = doc.get("degree", "")
                        spec = doc.get("specialization", "General Medicine")
                        doctor_descriptions.append(f"{doc['name']}, {degree}, specializing in {spec}")
                    
                    # Last doctor
                    last_doc = doctors[-1]
                    last_degree = last_doc.get("degree", "")
                    last_spec = last_doc.get("specialization", "General Medicine")
                    last_desc = f"{last_doc['name']}, {last_degree}, specializing in {last_spec}"
                    
                    doctors_text = ", ".join(doctor_descriptions) + f", and {last_desc}"
                    
                    return f"{prefix}We have {doctors_text} available. Which doctor would you like to see?"
                            
                else:
                    # Should not happen due to filtering, but just in case
                    return f"{prefix}We have {len(doctors)} doctors available. Could you tell me which doctor you'd prefer?"
            else:
                return "I'm having trouble fetching the doctor list at the moment. Could you try again?"
        
        elif function_name == "get_available_slots":
            if result.get("success"):
                slots = result.get("slots", [])
                if not slots:
                    return f"I'm sorry, there are no available slots on that date. Would you like to try a different date?"
                
                # Format slot list
                hourly_slots = self._group_slots_by_hour(slots)
                if not hourly_slots:
                     return "I couldn't find any specific time slots. Would you like to pick another date?"

                hour_ranges = []
                for hour, hour_slots in hourly_slots.items():
                    # Format hour for am/pm
                    period = "AM" if hour < 12 else "PM"
                    display_hour = hour if hour <= 12 else hour - 12
                    display_hour = 12 if display_hour == 0 else display_hour # Handle midnight/noon
                    
                    next_hour = display_hour + 1
                    next_period = period
                    if display_hour == 11:
                        next_period = "PM" if period == "AM" else "AM"
                    if display_hour == 12:
                        next_hour = 1
                    
                    hour_ranges.append(f"between {display_hour} and {next_hour} {next_period}")

                if len(hour_ranges) == 1:
                    return f"I have appointments available {hour_ranges[0]}. Is that time suitable for you?"
                else:
                    ranges_text = ", ".join(hour_ranges[:-1]) + f", and {hour_ranges[-1]}"
                    return f"We have appointments available at several times, including {ranges_text}. Which time frame would you prefer?"
            else:
                error = result.get("error", "Unable to check availability")
                return f"I'm having trouble checking availability. {error}. Could you try a different date?"
        
        elif function_name == "book_appointment_in_hour_range":
            if result.get("success"):
                appointment = result.get("appointment", {})
                doctor_name = appointment.get("doctor_name", "the doctor")
                date = appointment.get("appointment_date", "")
                time = appointment.get("appointment_time", "")
                confirmation = appointment.get("confirmation_number", "")
                
                # Format date nicely
                try:
                    date_obj = datetime.strptime(date, "%Y-%m-%d")
                    formatted_date = date_obj.strftime("%B %d, %Y")  # "October 29, 2025"
                except:
                    formatted_date = date
                
                return f"Perfect! Your appointment with {doctor_name} is confirmed for {formatted_date} at {time}. Your confirmation number is {confirmation}. You'll receive an SMS confirmation shortly. Is there anything else I can help you with?"
            
            else:
                # Parse the error and provide helpful response
                error_msg = result.get("error", "")
                
                if "no available slot" in error_msg.lower() or "no slots" in error_msg.lower():
                    return f"I'm sorry, there are no available slots in that time range. {error_msg} Would you like to try a different time?"
                elif "doctor" in error_msg.lower() and "not found" in error_msg.lower():
                    return "I'm sorry, I couldn't find that doctor. Could you please choose from the available doctors I mentioned?"
                elif "past" in error_msg.lower():
                    return "I'm sorry, that date is in the past. Could you provide a future date?"
                elif "understand" in error_msg.lower() and "time" in error_msg.lower():
                    return f"{error_msg} You can say something like '2 PM' or 'between 10 and 11 AM'."
                else:
                    return f"I'm sorry, I couldn't book that appointment. {error_msg} Would you like to try a different time?"

        elif function_name == "get_doctor_schedule":
            if result.get("success"):
                dates = result.get("available_dates", [])
                if not dates:
                    return "I'm sorry, but that doctor does not seem to have any upcoming availability."
                
                # Format date list nicely
                formatted_dates = [datetime.strptime(d, "%Y-%m-%d").strftime("%B %dth") for d in dates]

                if len(formatted_dates) == 1:
                    return f"That doctor is next available on {formatted_dates[0]}. Would you like to check available times for that day?"
                else:
                    dates_text = ", ".join(formatted_dates[:-1]) + f", and {formatted_dates[-1]}"
                    return f"That doctor has availability on {dates_text}. Which date would you like to book for?"

            else:
                return "I'm sorry, I couldn't retrieve that doctor's schedule at the moment."
                
        elif function_name == "get_appointment_details":
            if result.get("success"):
                details = result.get("appointment", {})
                return (
                    f"Okay, I found your appointment. You are scheduled to see Dr. {details.get('doctor_name')} "
                    f"on {details.get('appointment_date')} at {details.get('appointment_time')}. "
                    f"Your confirmation number is {details.get('confirmation_number')}. Is there anything else?"
                )
            else:
                return result.get("error", "I couldn't find an appointment for you.")        
        else:
            return "Let me help you with that."

    async def _handle_function_call(
        self,
        call_sid: str,
        result: Dict[str, Any],
        session: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle function call from GPT-4"""
        try:
            function_call = result.get("function_call", {})
            function_name = function_call.get("name")
            
            print(f"Function called: {function_name}")
            
            # Get arguments - handle both string and dict formats
            arguments = function_call.get("arguments", {})
            if isinstance(arguments, str):
                import json
                arguments = json.loads(arguments)
            
            print(f"Arguments: {arguments}")

            # ============ FIX 1: ADD USER CONTEXT BEFORE EXECUTION ============
            if function_name == "get_available_doctors":
                # Get conversation history to extract symptoms/context
                conversation_history = session.get("conversation_history", [])
                
                # Build context from ALL user messages in this conversation
                user_messages = []
                for msg in conversation_history:
                    if msg.get("role") == "user":
                        user_messages.append(msg.get("content", ""))
                
                # Combine all user messages
                user_context = " ".join(user_messages).strip()
                
                # OVERRIDE whatever OpenAI sent - use our extracted context
                arguments["user_context"] = user_context
                
                print(f"📋 User context for doctor filtering: '{user_context}'")
                print(f"   (Extracted from {len(user_messages)} user messages)")

            if function_name in ["get_available_slots", "book_appointment_in_hour_range", "get_doctor_schedule"]:
                doctor_id = arguments.get("doctor_id", "")
                
                # Get available doctors and pre-selected doctor from session
                available_doctors = session.get("available_doctors", [])
                pre_selected_doctor = session.get("selected_doctor_id")  # ← From auto-detection!
                
                print(f"Resolving doctor_id: '{doctor_id}'")
                print(f"Available doctors in session: {len(available_doctors)}")
                if pre_selected_doctor:
                    print(f"✓ Pre-selected doctor from auto-detection: {pre_selected_doctor}")
                
                # ============ CRITICAL: Check pre-selected doctor FIRST ============
                if pre_selected_doctor:
                    # Auto-detection already found the doctor - use it immediately!
                    arguments["doctor_id"] = pre_selected_doctor
                    print(f"✓ Using auto-detected doctor: {pre_selected_doctor}")
                
                # ============ ONLY if no pre-selected doctor, validate OpenAI's ID ============
                elif doctor_id and doctor_id.startswith("DOC") and available_doctors:
                    # Verify it exists in available doctors
                    valid = any(d["doctor_id"] == doctor_id for d in available_doctors)
                    if valid:
                        print(f"✓ Valid doctor_id: {doctor_id}")
                    else:
                        print(f"⚠ doctor_id {doctor_id} not in available doctors, will resolve...")
                        # Try to resolve from available doctors
                        resolved_id = self._resolve_doctor_id(doctor_id, available_doctors)
                        if resolved_id:
                            arguments["doctor_id"] = resolved_id
                            print(f"✓ Resolved to: {resolved_id}")
                        else:
                            # Could not resolve - use first available if only one
                            if len(available_doctors) == 1:
                                arguments["doctor_id"] = available_doctors[0]["doctor_id"]
                                print(f"⚠ Using only available doctor: {available_doctors[0]['doctor_id']}")
                            else:
                                print("❌ Could not resolve doctor. Asking for clarification.")
                                clarification_text = "I'm sorry, I couldn't identify that doctor. Could you please tell me which doctor you'd like to see from the available list?"
                                
                                redis_service.append_to_conversation(call_sid, "assistant", clarification_text)
                                return {
                                    "success": True,
                                    "response": clarification_text,
                                    "function_called": False,
                                }
                
                # ============ Try to resolve from name or use first available ============
                elif available_doctors:
                    if len(available_doctors) == 1:
                        # Only one doctor available - use it!
                        arguments["doctor_id"] = available_doctors[0]["doctor_id"]
                        print(f"✓ Using only available doctor: {available_doctors[0]['doctor_id']}")
                    elif doctor_id:
                        # Try to resolve from available doctors
                        resolved_id = self._resolve_doctor_id(doctor_id, available_doctors)
                        if resolved_id:
                            arguments["doctor_id"] = resolved_id
                            print(f"✓ Resolved from name/number: {resolved_id}")
                        else:
                            # Use first available as fallback
                            arguments["doctor_id"] = available_doctors[0]["doctor_id"]
                            print(f"⚠ Using first available doctor: {available_doctors[0]['doctor_id']}")
                    else:
                        # No doctor specified - use first available
                        arguments["doctor_id"] = available_doctors[0]["doctor_id"]
                        print(f"⚠ No doctor specified, using first available: {available_doctors[0]['doctor_id']}")
                else:
                    print(f"❌ No available doctors in session!")
                    clarification_text = "I'm sorry, I don't have the doctor information. Could you please tell me which doctor you'd like to see?"
                    
                    redis_service.append_to_conversation(call_sid, "assistant", clarification_text)
                    return {
                        "success": True,
                        "response": clarification_text,
                        "function_called": False,
                    }
            
            # ============ EXECUTE FUNCTION (ONLY ONCE!) ============
            print(f"🔧 Executing function: {function_name}")
            function_result = self.ai_tools.execute_function(
                function_name,
                arguments
            )
            
            print(f"   ✓ Result success: {function_result.get('success', False)}")
            
            # ============ FIX 2: STORE DOCTORS IN SESSION ============
            if function_name == "get_available_doctors" and function_result.get("success"):
                doctors = function_result.get("doctors", [])
                if doctors:
                    redis_service.update_session(call_sid, {
                        "available_doctors": doctors
                    })
                    print(f"✓ Stored {len(doctors)} doctors in session")
                    
                    # Log the doctors for debugging
                    for doc in doctors:
                        print(f"   - {doc['name']} ({doc['specialization']})")
            # ============ END FIX 2 ============
            
            # Store selected doctor after successful get_available_slots
            if function_name == "get_available_slots" and function_result.get("success"):
                doctor_id = arguments.get("doctor_id")
                if doctor_id:
                    redis_service.update_session(call_sid, {
                        "selected_doctor_id": doctor_id
                    })
                    print(f"✓ Stored selected doctor: {doctor_id}")
            
            # Generate natural language response
            response_text = self._generate_response_from_function_result(
                function_name,
                function_result
            )
            
            # Add to conversation
            redis_service.append_to_conversation(call_sid, "assistant", response_text)
            
            return {
                "success": True,
                "response": response_text,
                "function_called": True,
                "function_name": function_name,
                "function_result": function_result
            }
            
        except Exception as e:
            print(f"❌ Error handling function call: {e}")
            import traceback
            traceback.print_exc()
            
            return {
                "success": False,
                "error": str(e),
                "response": "I apologize, I'm having trouble processing that. Could you please try again?"
            }

    async def _update_session_from_function(
        self,
        call_sid: str,
        function_name: str,
        arguments: Dict[str, Any],
        result: Dict[str, Any]
    ):
        """Update session based on function execution"""
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
    
    """async def _generate_ai_response_with_context(
        self,
        call_sid: str,
        function_result: Dict[str, Any],
        function_name: str
    ) -> str:
        try:
            # Get session
            session = redis_service.get_session(call_sid)
            conversation_history = session.get("conversation_history", [])
            
            # Create context message for GPT
            if function_name == "get_available_doctors":
                if function_result.get("success"):
                    doctors = function_result.get("doctors", [])
                    
                    # ==================== UPDATE THIS SECTION ====================
                    # Format doctor list with IDs explicitly
                    doctor_descriptions = []
                    for i, doc in enumerate(doctors, 1):
                        doctor_descriptions.append(
                            f"{i}. Dr. {doc['name']} ({doc['degree']}) - ID: {doc['doctor_id']}"
                        )
                    
                    context = (
                        f"Available doctors:\n" + "\n".join(doctor_descriptions) +
                        f"\n\nIMPORTANT: When calling get_available_slots, use the exact doctor_id "
                        f"from this list (like {doctors[0]['doctor_id']}), NOT the number."
                    )
                    # ==================== END UPDATE ====================
                else:
                    context = "No doctors are currently available."
            
            elif function_name == "get_available_slots":
                if function_result.get("success"):
                    slots = function_result.get("slots", [])
                    context = f"Available time slots: {', '.join(slots[:10])}"
                else:
                    context = function_result.get("error", "No slots available")
            
            elif function_name == "book_appointment":
                if function_result.get("success"):
                    confirmation = function_result.get("confirmation_number")
                    context = f"Appointment successfully booked! Confirmation: {confirmation}"
                else:
                    context = f"Booking failed: {function_result.get('error')}"
            
            else:
                context = str(function_result)
            
            # Generate natural response using GPT
           prompt = 
           f
           #Based on this information:
    #{context}

   # Generate a natural, conversational response to the user. Be warm and helpful.
            
            response = await openai_service.generate_simple_response(
                prompt,
                conversation_history[-3:] if len(conversation_history) > 3 else conversation_history
            )
            
            return response
            
        except Exception as e:
            print(f"Error generating AI response: {e}")
            return "Let me help you with that."""

    def _group_slots_by_hour(self, slots: List[str]) -> Dict[int, List[str]]:
        """Groups a list of time slots (HH:MM) by hour."""
        hourly_slots = defaultdict(list)
        for slot in slots:
            try:
                hour = int(slot.split(':')[0])
                hourly_slots[hour].append(slot)
            except (ValueError, IndexError):
                print(f"Warning: Could not parse slot '{slot}'")
        return dict(sorted(hourly_slots.items()))

    async def end_call(self, call_sid: str) -> Dict[str, Any]:
        """End call and cleanup"""
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
        """Extract doctor selection from user speech"""
        user_lower = user_text.lower()
        
        # Check for ordinal selection (first, second, third)
        ordinals = {
            'first': 0, '1st': 0, 'one': 0,
            'second': 1, '2nd': 1, 'two': 1,
            'third': 2, '3rd': 2, 'three': 2
        }
        
        for word, index in ordinals.items():
            if word in user_lower and index < len(available_doctors):
                return available_doctors[index]["doctor_id"]
        
        # Check for doctor name match
        for doctor in available_doctors:
            name_parts = doctor["name"].lower().split()
            for part in name_parts:
                if len(part) > 2 and part in user_lower:
                    return doctor["doctor_id"]
        
        return None
