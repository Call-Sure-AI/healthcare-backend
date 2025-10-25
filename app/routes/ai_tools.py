from datetime import date, datetime, timedelta
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from app.services.doctor_service import DoctorService
from app.services.appointment_service import AppointmentService
from app.models.leave import DoctorLeave
from app.utils.symptom_mapper import extract_specialization_from_text, filter_doctors_by_specialization
from app.schemas.appointment import AppointmentCreate
import re

AI_FUNCTIONS = [
    {
        "name": "get_available_doctors",
        "description": (
            "Get a list of available doctors filtered by patient's symptoms or specialization needs. "
            "This function will automatically detect if the patient mentioned symptoms (e.g., 'chest pain', "
            "'skin rash', 'child vaccination') and return relevant specialists. If no symptoms are mentioned "
            "or no specialists match, it returns up to 5 general doctors."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "user_context": {
                    "type": "string",
                    "description": "The patient's reason for visit, symptoms, or any context from the conversation"
                }
            },
            "required": []
        }
    },
    {
        "name": "get_doctor_schedule",
        "description": "Finds the next available DATES for a single, specific doctor. Use this ONLY when the user asks for a doctor's availability but has NOT provided a specific date.",
        "parameters": {
            "type": "object",
            "properties": {
                "doctor_id": {
                    "type": "string",
                    "description": "The exact doctor_id of the doctor (e.g., DOC2005)."
                }
            },
            "required": ["doctor_id"]
        }
    },
    {
        "name": "get_available_slots",
        "description": "Gets the available appointment TIME SLOTS for a doctor on ONE specific date. Use this ONLY after you have confirmed both the doctor and the exact date with the user.",
        "parameters": {
            "type": "object",
            "properties": {
                "doctor_id": {
                    "type": "string",
                    "description": "The exact doctor_id for the appointment."
                },
                "date": {
                    "type": "string",
                    "description": "The specific date for the appointment in YYYY-MM-DD format."
                }
            },
            "required": ["doctor_id", "date"]
        }
    },
    {
        "name": "get_appointment_details",
        "description": "Fetch the details of an existing scheduled appointment for a patient using their name and phone number. Use this if the user asks 'where is my appointment?' or 'what are my booking details?'.",
        "parameters": {
            "type": "object",
            "properties": {
                "patient_name": {
                    "type": "string", 
                    "description": "The full name of the patient."
                },
                "patient_phone": {
                    "type": "string", 
                    "description": "The patient's phone number."
                }
            },
            "required": ["patient_name", "patient_phone"]
        }
    },
    {
        "name": "book_appointment_in_hour_range",
        "description": "Book an appointment within a specified hour range (e.g., '2 PM', '10-11 AM'). The system will automatically find and book the first available 15-minute slot in that hour.",
        "parameters": {
            "type": "object",
            "properties": {
                "patient_name": {"type": "string"},
                "patient_phone": {"type": "string"},
                "doctor_id": {"type": "string"},
                "appointment_date": {"type": "string"},
                "time_range": {
                    "type": "string",
                    "description": "The desired hour for the appointment, e.g., '3 PM' or 'between 10 and 11 AM'."
                },
                "reason": {"type": "string"}
            },
            "required": ["patient_name", "patient_phone", "doctor_id", "appointment_date", "time_range"]
        }
    },
]


class AIToolsExecutor:
    """Executor for AI function calls"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def execute_function(self, function_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a function called by GPT-4"""
        try:
            print(f"Executing function: {function_name}")
            
            if function_name == "get_available_doctors":
                return self.get_available_doctors(**arguments)
            elif function_name == "get_available_slots":
                return self.get_available_slots(**arguments)
            elif function_name == "book_appointment":
                return self.book_appointment(**arguments)
            elif function_name == "get_doctor_schedule":
                return self.get_doctor_schedule(**arguments)
            elif function_name == "get_appointment_details":
                return self.get_appointment_details(**arguments)
            else:
                return {"success": False, "error": f"Unknown function: {function_name}"}
        except Exception as e:
            print(f"Function execution error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
    
    def get_available_doctors(self, user_context: str) -> Dict[str, Any]:
        """Get list of active doctors who are not on leave, filtered by symptoms/specialization"""
        try:
            from app.utils.symptom_mapper import extract_specialization_from_text, filter_doctors_by_specialization
            from collections import Counter
            
            print(f"\n{'='*80}")
            print(f"🔍 get_available_doctors called")
            print(f"   User context: '{user_context}'")
            print(f"   Context length: {len(user_context)} chars")
            print(f"{'='*80}\n")
            
            print("Fetching available doctors...")
            
            # ========== STEP 1: GET ALL ACTIVE DOCTORS ==========
            doctors = DoctorService.get_all_active_doctors(self.db)
            print(f"   Total ACTIVE doctors in DB: {len(doctors)}")
            
            # ========== STEP 2: GET DOCTORS ON LEAVE ==========
            today = date.today()
            doctors_on_leave = self.db.query(DoctorLeave.doctor_id).filter(
                DoctorLeave.start_date <= today,
                DoctorLeave.end_date >= today
            ).all()
            
            on_leave_ids = [leave.doctor_id for leave in doctors_on_leave]
            print(f"   Doctors on leave: {len(on_leave_ids)}")
            
            # ========== STEP 3: BUILD LIST OF AVAILABLE DOCTORS ==========
            active_doctors = []
            for doc in doctors:
                is_on_leave = doc.doctor_id in on_leave_ids
                if not is_on_leave:
                    active_doctors.append({
                        "doctor_id": doc.doctor_id,
                        "name": doc.name,
                        "degree": doc.degree,
                        "specialization": doc.specialization or "General Medicine"
                    })
            
            print(f"   Available doctors before filtering: {len(active_doctors)}")
            
            # ========== STEP 4: SHOW SPECIALIZATION DISTRIBUTION ==========
            if active_doctors:
                spec_dist = Counter(d["specialization"] for d in active_doctors)
                print(f"   📋 Specialization distribution:")
                for spec, count in spec_dist.most_common():
                    print(f"      - {spec}: {count}")
            
            # ========== STEP 5: DETECT SPECIALIZATION FROM USER CONTEXT ==========
            detected_specialization = None
            if user_context:
                print(f"\n🔍 Detecting specialization from: '{user_context}'")
                detected_specialization = extract_specialization_from_text(user_context)
                print(f"🎯 Detected: {detected_specialization or 'None'}")
            else:
                print(f"⚠️  No user context provided - cannot detect specialization")
            
            # ========== STEP 6: FILTER DOCTORS BY SPECIALIZATION ==========
            filtered_doctors = filter_doctors_by_specialization(
                active_doctors,
                detected_specialization
            )
            
            print(f"\n   🎯 Final result: {len(filtered_doctors)} doctors")
            for doc in filtered_doctors:
                print(f"      - {doc['name']} ({doc['specialization']})")
            print(f"\n{'='*80}\n")
            
            # ========== STEP 7: RETURN RESULT ==========
            if not filtered_doctors:
                return {
                    "success": False,
                    "message": "No doctors are currently available.",
                    "doctors": [],
                    "specialization_detected": detected_specialization
                }
            
            print(f"   Result success: True")
            
            return {
                "success": True,
                "count": len(filtered_doctors),
                "doctors": filtered_doctors,
                "specialization_detected": detected_specialization
            }
            
        except Exception as e:
            print(f"❌ Error in get_available_doctors: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e), "doctors": []}


    def get_appointment_details(self, patient_name: str, patient_phone: str) -> Dict[str, Any]:
        """Executor for fetching appointment details."""
        try:
            print(f"Searching for appointment for {patient_name} ({patient_phone})")
            
            details = AppointmentService.get_appointment_details(self.db, patient_name, patient_phone)
            
            if details:
                return {
                    "success": True,
                    "appointment": details
                }
            else:
                return {
                    "success": False,
                    "error": "I couldn't find any scheduled appointments for that name and phone number."
                }
        except Exception as e:
            print(f"Error in get_appointment_details: {e}")
            return {"success": False, "error": str(e)}

    def _parse_date(self, date_str: str) -> str:
        """Parse various date formats to YYYY-MM-DD"""
        
        date_str = date_str.lower().strip()
        today = datetime.now().date()
        
        # Handle relative dates
        if "tomorrow" in date_str:
            target_date = today + timedelta(days=1)
            return target_date.strftime("%Y-%m-%d")
        
        if "today" in date_str:
            return today.strftime("%Y-%m-%d")
        
        # Check if already in YYYY-MM-DD format
        if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
            return date_str
        
        # Month name mapping
        months = {
            'january': 1, 'jan': 1, 'february': 2, 'feb': 2, 'march': 3, 'mar': 3,
            'april': 4, 'apr': 4, 'may': 5, 'june': 6, 'jun': 6,
            'july': 7, 'jul': 7, 'august': 8, 'aug': 8, 'september': 9, 'sep': 9,
            'october': 10, 'oct': 10, 'november': 11, 'nov': 11, 'december': 12, 'dec': 12
        }
        
        # Extract month name if present
        month_num = None
        for month_name, num in months.items():
            if month_name in date_str:
                month_num = num
                break
        
        # Extract numbers
        numbers = re.findall(r'\d+', date_str)

        if month_num and len(numbers) == 1:
            # Format: "27th October" or "October 27"
            day = int(numbers[0])
            year = today.year
            
            # Smart year handling: if date is in the past, use next year
            try:
                parsed_date = datetime(year, month_num, day).date()
                if parsed_date < today:
                    year += 1
                    print(f"Date {day}/{month_num} is in past, using next year: {year}")
            except ValueError:
                # Invalid date (e.g., Feb 30)
                print(f"Invalid date {day}/{month_num}, keeping year {year}")
            
            result = f"{year:04d}-{month_num:02d}-{day:02d}"
            print(f"   → Parsed as: {result}")
            return result

        if month_num and len(numbers) >= 2:
            # Format: "20th October 2025" or "October 20, 2025"
            day = int(numbers[0])
            year = int(numbers[1]) if len(numbers[1]) == 4 else int(numbers[0])
            if year < 100:
                year += 2000
            return f"{year:04d}-{month_num:02d}-{day:02d}"
        
        if len(numbers) >= 3:
            # Format: "20 10 2025" (DD MM YYYY)
            day, month, year = int(numbers[0]), int(numbers[1]), int(numbers[2])
            if year < 100:
                year += 2000
            return f"{year:04d}-{month:02d}-{day:02d}"
        
        if len(numbers) == 2:
            # Format: "20 10" (DD MM), use current year
            day, month = int(numbers[0]), int(numbers[1])
            year = today.year
            return f"{year:04d}-{month:02d}-{day:02d}"
        
        # Fallback: return as-is
        return date_str

    def _find_doctor_id_by_name(self, doctor_name: str) -> str:
        """Find doctor ID by name (fuzzy matching)"""
        try:
            doctors = DoctorService.get_all_doctors(self.db)
            
            doctor_name_lower = doctor_name.lower().strip()
            
            # Remove common prefixes
            doctor_name_clean = doctor_name_lower.replace('dr.', '').replace('dr', '').replace('doctor', '').strip()
            
            print(f"🔍 Looking for doctor: '{doctor_name}' (cleaned: '{doctor_name_clean}')")
            
            # Try exact match first
            for doc in doctors:
                if doc.name.lower().strip() == doctor_name_clean:
                    print(f"   ✅ Exact match: {doc.name} ({doc.doctor_id})")
                    return doc.doctor_id
            
            # Try partial match
            for doc in doctors:
                if doctor_name_clean in doc.name.lower() or doc.name.lower() in doctor_name_clean:
                    print(f"   ✅ Partial match: {doc.name} ({doc.doctor_id})")
                    return doc.doctor_id
            
            # No match found
            print(f"No match found for '{doctor_name}'")
            return None
            
        except Exception as e:
            print(f"Error finding doctor: {e}")
            return None


    # Update get_available_slots to use the parser
    def get_available_slots(self, doctor_id: str, date: str) -> Dict[str, Any]:
        """Get available time slots for a doctor on a date"""
        try:
            print(f"Checking slots for doctor='{doctor_id}', date='{date}'")
            
            # Check if doctor_id looks like a name instead of an ID
            if not doctor_id.startswith('DOC'):
                print(f"'{doctor_id}' doesn't look like a doctor ID, attempting name lookup...")
                resolved_id = self._find_doctor_id_by_name(doctor_id)
                if resolved_id:
                    doctor_id = resolved_id
                    print(f"Resolved to: {doctor_id}")
                else:
                    return {
                        "success": False,
                        "error": f"Could not find doctor '{doctor_id}'. Please specify the doctor again.",
                        "slots": []
                    }
            
            # Parse and normalize the date
            formatted_date = self._parse_date(date)
            print(f"   Formatted date: {formatted_date}")
            
            # Validate date is not in the past
            try:
                date_obj = datetime.strptime(formatted_date, "%Y-%m-%d").date()
                today = datetime.now().date()
                if date_obj < today:
                    return {
                        "success": False,
                        "error": f"The date {formatted_date} is in the past. Please provide a future date.",
                        "slots": []
                    }
            except:
                pass
            
            # Get available slots
            result = AppointmentService.get_available_slots(
                self.db,
                doctor_id,
                formatted_date
            )
            
            print(f"API Response: {result}")
            
            if "available_slots" in result:
                slots = result["available_slots"]
                print(f"Found {len(slots)} slots")
                
                if not slots:
                    return {
                        "success": False,
                        "error": f"No slots available on {formatted_date}. Please try another date.",
                        "slots": []
                    }
                
                return {
                    "success": True,
                    "doctor_id": doctor_id,
                    "date": formatted_date,
                    "slots": slots,
                    "count": len(slots)
                }
            else:
                error = result.get("error", "No slots found")
                return {
                    "success": False,
                    "error": error,
                    "slots": []
                }
                
        except Exception as e:
            print(f"Error in get_available_slots: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": f"Unable to check availability: {str(e)}",
                "slots": []
            }

    def get_doctor_schedule(self, doctor_id: str) -> Dict[str, Any]:
        """Get the next available dates for a specific doctor."""
        try:
            print(f"Fetching schedule for doctor: {doctor_id}")
            from datetime import date
            
            # Resolve doctor ID from name if necessary
            if not doctor_id.startswith('DOC'):
                resolved_id = self._find_doctor_id_by_name(doctor_id)
                if not resolved_id:
                     return {"success": False, "error": f"Could not find a doctor named '{doctor_id}'."}
                doctor_id = resolved_id

            available_dates = DoctorService.get_doctor_schedule(self.db, doctor_id, date.today())
            
            if not available_dates:
                return {
                    "success": False,
                    "error": "This doctor has no upcoming availability. Please check another doctor."
                }
            
            return {
                "success": True,
                "doctor_id": doctor_id,
                "available_dates": available_dates
            }
        except Exception as e:
            print(f"Error in get_doctor_schedule: {e}")
            return {"success": False, "error": str(e)}

    def book_appointment(
        self,
        patient_name: str,
        patient_phone: str,
        doctor_id: str,
        appointment_date: str,
        appointment_time: str,
        reason: str = ""
    ) -> Dict[str, Any]:
        """Book an appointment"""
        try:
            
            print(f"📝 Booking appointment for {patient_name}")
            
            # Parse date if needed
            formatted_date = self._parse_date(appointment_date)
            
            # Create Pydantic model (not a dict!)
            appointment_data = AppointmentCreate(
                patient_name=patient_name.strip(),
                patient_phone=patient_phone.strip(),
                patient_email=None,
                doctor_id=doctor_id,
                appointment_date=formatted_date,
                appointment_time=appointment_time,
                notes=reason or "Booked via voice call",
                status="SCHEDULED"
            )
            
            # Now pass the Pydantic object
            appointment = AppointmentService.create_appointment(
                self.db,
                appointment_data
            )
            
            if appointment:
                print(f"Appointment booked: APT-{appointment.id}")
                return {
                    "success": True,
                    "appointment_id": appointment.id,
                    "confirmation_number": f"APT-{appointment.id}",
                    "patient_name": appointment.patient_name,
                    "doctor_id": appointment.doctor_id,
                    "date": str(appointment.appointment_date),
                    "time": appointment.appointment_time
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to create appointment"
                }
                
        except Exception as e:
            print(f"Error in book_appointment: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": f"Booking failed: {str(e)}"
            }
    def book_appointment_in_hour_range(
        self,
        patient_name: str,
        patient_phone: str,
        doctor_id: str,
        appointment_date: str,
        time_range: str, # e.g., "2 PM", "10-11 AM", "between 2 and 3 PM"
        reason: str = ""
    ) -> Dict[str, Any]:
        """
        Attempts to book the first available slot within a specified hour range.
        If the first attempt fails, it tries the next available slot in that hour.
        """
        try:

            print(f"Attempting to book for {patient_name} in time range: '{time_range}'")
            
            # 1. Parse the hour from the time_range string
            import re
            numbers = re.findall(r'\d+', time_range)
            if not numbers:
                return {"success": False, "error": "I couldn't understand the time. Please specify an hour, like '2 PM' or 'between 10 and 11 AM'."}
            
            hour = int(numbers[0])
            if "pm" in time_range.lower() and hour < 12:
                hour += 12
            
            # 2. Get all available slots for the given date to find ones in the target hour
            slots_result = self.get_available_slots(doctor_id, appointment_date)
            if not slots_result.get("success"):
                return {"success": False, "error": f"It seems there are no slots available on {appointment_date}."}

            available_slots = slots_result.get("slots", [])
            slots_in_hour = [s for s in available_slots if s.startswith(f"{hour:02d}:")]

            if not slots_in_hour:
                return {"success": False, "error": f"I'm sorry, but there are no available slots between {hour}:00 and {hour+1}:00. Please choose another time."}

            # 3. Iterate and try to book each slot in the hour range
            booked_appointment = None
            last_error = "No available slots found in the selected hour."

            for slot_to_try in sorted(slots_in_hour):
                print(f"  -> Trying to book slot: {slot_to_try}")
                try:
                    appointment_data = AppointmentCreate(
                        patient_name=patient_name.strip(),
                        patient_phone=patient_phone.strip(),
                        doctor_id=doctor_id,
                        appointment_date=appointment_date,
                        appointment_time=slot_to_try,
                        notes=reason or "Booked via voice call",
                        status="SCHEDULED"
                    )
                    
                    # Use the direct service call to attempt booking
                    appointment = AppointmentService.create_appointment(self.db, appointment_data)
                    
                    if appointment:
                        booked_appointment = appointment
                        break # Success! Exit the loop.

                except HTTPException as e:
                    # This exception is raised by create_appointment on failure (e.g., slot taken)
                    last_error = e.detail
                    print(f"  -> Slot {slot_to_try} failed to book: {e.detail}")
                    self.db.rollback() # Rollback the failed transaction
                    continue # Try the next slot

            # 4. Return result
            if booked_appointment:
                print(f"Appointment successfully booked: APT-{booked_appointment.id}")
                return {
                    "success": True,
                    "confirmation_number": f"APT-{booked_appointment.id}",
                    "patient_name": booked_appointment.patient_name,
                    "doctor_id": booked_appointment.doctor_id,
                    "date": str(booked_appointment.appointment_date),
                    "time": booked_appointment.appointment_time
                }
            else:
                print(f"Failed to book any slot in the {hour}:00 hour.")
                return {
                    "success": False,
                    "error": f"I tried all available slots between {hour}:00 and {hour+1}:00, but was unable to book. The last error was: {last_error}. Would you like to try a different hour?"
                }

        except Exception as e:
            print(f"Major error in book_appointment_in_hour_range: {e}")
            self.db.rollback()
            return {"success": False, "error": f"A system error occurred during booking: {str(e)}"}

def get_ai_functions() -> List[Dict[str, Any]]:
    """Get list of available functions for GPT-4"""
    return AI_FUNCTIONS
