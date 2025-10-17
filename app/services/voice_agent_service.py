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
            print(f"💬 Processing speech: '{user_text}'")
            
            session = redis_service.get_session(call_sid)
            if not session:
                return {"success": False, "error": "Session not found"}
            
            redis_service.append_to_conversation(call_sid, "user", user_text)

            user_lower = user_text.lower()
            available_doctors = session.get("available_doctors", [])

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
                            print(f"Auto-detected doctor: {doctor['name']} ({doctor['doctor_id']})")
                            break

            conversation_history = session.get("conversation_history", [])
            
            ai_functions = get_ai_functions()
            result = await openai_service.process_user_input(
                user_message=user_text,
                conversation_history=conversation_history,
                available_functions=ai_functions
            )

            if result.get("function_call"):
                return await self._handle_function_call(call_sid, result, session)

            response_text = result.get("response", "I'm sorry, could you please repeat that?")

            redis_service.append_to_conversation(call_sid, "assistant", response_text)
            
            return {
                "success": True,
                "response": response_text,
                "function_called": False
            }
            
        except Exception as e:
            print(f"Error processing speech: {e}")
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
                if not doctors:
                    return "I'm sorry, no doctors are currently available. Would you like me to help you with something else?"
                
                # Format doctor list
                if len(doctors) == 1:
                    doc = doctors[0]
                    return f"We have Dr. {doc['name']} ({doc['degree']}) available. Would you like to book an appointment with Dr. {doc['name']}?"
                elif len(doctors) == 2:
                    return f"We have Dr. {doctors[0]['name']} and Dr. {doctors[1]['name']} available. Which doctor would you prefer?"
                else:
                    doctor_names = ", ".join([f"Dr. {doc['name']}" for doc in doctors[:-1]])
                    last_doctor = f"Dr. {doctors[-1]['name']}"
                    return f"We have {doctor_names}, and {last_doctor} available. Which doctor would you like to see?"
            else:
                return "I'm having trouble fetching the doctor list at the moment. Could you try again?"
        
        elif function_name == "get_available_slots":
            if result.get("success"):
                slots = result.get("slots", [])
                if not slots:
                    return f"I'm sorry, there are no available slots on that date. Would you like to try a different date?"
                
                # Format slot list
                if len(slots) <= 3:
                    slot_text = " or ".join(slots)
                    return f"I have appointments available at {slot_text}. Which time works best for you?"
                else:
                    first_slots = ", ".join(slots[:3])
                    return f"I have several slots available including {first_slots}. What time would you prefer?"
            else:
                error = result.get("error", "Unable to check availability")
                return f"I'm having trouble checking availability. {error}. Could you try a different date?"
        
        elif function_name == "book_appointment":
            if result.get("success"):
                confirmation = result.get("confirmation_number", "")
                date = result.get("date", "")
                time = result.get("time", "")
                return f"Perfect! I've successfully booked your appointment for {date} at {time}. Your confirmation number is {confirmation}. Is there anything else I can help you with?"
            else:
                error = result.get("error", "")
                return f"I'm sorry, I wasn't able to complete the booking. {error}. Would you like to try again?"
        
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
            
            print(f"   Arguments: {arguments}")

            if function_name in ["get_available_slots", "book_appointment"]:
                doctor_id = arguments.get("doctor_id", "")
                
                # Get available doctors from session
                available_doctors = session.get("available_doctors", [])
                
                print(f"Resolving doctor_id: '{doctor_id}'")
                print(f"Available doctors in session: {len(available_doctors)}")
                
                # Strategy 1: Check if already a valid DOC ID
                if doctor_id and doctor_id.startswith("DOC"):
                    # Verify it exists in available doctors
                    valid = any(d["doctor_id"] == doctor_id for d in available_doctors)
                    if valid:
                        print(f"Valid doctor_id: {doctor_id}")
                    else:
                        print(f"doctor_id {doctor_id} not in available doctors, will resolve...")
                        doctor_id = None
                
                # Strategy 2: Resolve from name/index if needed
                if not doctor_id or not doctor_id.startswith("DOC"):
                    # First check pre-selected doctor
                    selected_doctor_id = session.get("selected_doctor_id")
                    if selected_doctor_id:
                        arguments["doctor_id"] = selected_doctor_id
                        print(f"Using pre-selected doctor: {selected_doctor_id}")
                    elif available_doctors:
                        # Try to resolve from available doctors
                        resolved_id = self._resolve_doctor_id(doctor_id, available_doctors)
                        if resolved_id:
                            arguments["doctor_id"] = resolved_id
                            print(f"Resolved to: {resolved_id}")
                        else:
                            # Default to first available
                            arguments["doctor_id"] = available_doctors[0]["doctor_id"]
                            print(f"Defaulting to first doctor: {available_doctors[0]['doctor_id']}")
                    else:
                        print(f"No available doctors in session!")
            
            # Execute the function
            function_result = self.ai_tools.execute_function(
                function_name,
                arguments
            )
            
            print(f"   Result success: {function_result.get('success', False)}")
            
            # Store doctor list in session after get_available_doctors
            if function_name == "get_available_doctors" and function_result.get("success"):
                doctors = function_result.get("doctors", [])
                if doctors:
                    redis_service.update_session(call_sid, {
                        "available_doctors": doctors
                    })
                    print(f"Stored {len(doctors)} doctors in session")
            
            # Store selected doctor after successful get_available_slots
            if function_name == "get_available_slots" and function_result.get("success"):
                doctor_id = arguments.get("doctor_id")
                if doctor_id:
                    redis_service.update_session(call_sid, {
                        "selected_doctor_id": doctor_id
                    })
                    print(f"Stored selected doctor: {doctor_id}")
            
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
            print(f"Error handling function call: {e}")
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
            print(f"❌ Error generating AI response: {e}")
            return "Let me help you with that."""

    
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
