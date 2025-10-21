from datetime import date, datetime
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from app.services.doctor_service import DoctorService
from app.services.appointment_service import AppointmentService
from app.models.leave import DoctorLeave

AI_FUNCTIONS = [
    {
        "name": "get_available_doctors",
        "description": "Get a list of all active doctors. Use this when the user wants to know which doctors are available.",
        "parameters": {
            "type": "object",
            "properties": {},
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
        "name": "book_appointment",
        "description": "Books the final appointment after all details (patient name, phone, doctor, date, and time) have been collected and confirmed.",
        "parameters": {
            "type": "object",
            "properties": {
                "patient_name": {"type": "string"},
                "patient_phone": {"type": "string"},
                "doctor_id": {"type": "string"},
                "appointment_date": {"type": "string"},
                "appointment_time": {"type": "string"},
                "reason": {"type": "string"}
            },
            "required": ["patient_name", "patient_phone", "doctor_id", "appointment_date", "appointment_time"]
        }
    }
]


class AIToolsExecutor:
    """Executor for AI function calls"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def execute_function(self, function_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a function called by GPT-4"""
        try:
            print(f"🔧 Executing function: {function_name}")
            
            if function_name == "get_available_doctors":
                return self.get_available_doctors()
            elif function_name == "get_available_slots":
                return self.get_available_slots(**arguments)
            elif function_name == "book_appointment":
                return self.book_appointment(**arguments)
            elif function_name == "get_doctor_schedule":
                return self.get_doctor_schedule(**arguments)
            else:
                return {"success": False, "error": f"Unknown function: {function_name}"}
        except Exception as e:
            print(f"Function execution error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
    
    def get_available_doctors(self) -> Dict[str, Any]:
        """Get list of active doctors who are not on leave"""
        try:
            print("📋 Fetching available doctors...")
            
            # Get all ACTIVE doctors only
            doctors = DoctorService.get_all_active_doctors(self.db)
            print(f"   Total ACTIVE doctors in DB: {len(doctors)}")
            
            # Get today's date
            today = date.today()
            
            # Get doctors who are on leave today
            doctors_on_leave = self.db.query(DoctorLeave.doctor_id).filter(
                DoctorLeave.start_date <= today,
                DoctorLeave.end_date >= today
            ).all()
            
            on_leave_ids = [leave.doctor_id for leave in doctors_on_leave]
            print(f"   Doctors on leave: {len(on_leave_ids)}")
            
            # Filter active doctors not on leave
            active_doctors = []
            for doc in doctors:
                is_on_leave = doc.doctor_id in on_leave_ids
                
                print(f"   - {doc.doctor_id}: {doc.name}, status={doc.status}, on_leave={is_on_leave}")
                
                if not is_on_leave:
                    active_doctors.append({
                        "doctor_id": doc.doctor_id,
                        "name": doc.name,
                        "degree": doc.degree,
                        "specialization": "General Medicine"
                    })
            
            print(f"✅ Available doctors: {len(active_doctors)}")
            
            if not active_doctors:
                return {
                    "success": False,
                    "message": "No doctors are currently available.",
                    "doctors": []
                }
            
            return {
                "success": True,
                "count": len(active_doctors),
                "doctors": active_doctors
            }
            
        except Exception as e:
            print(f"Error in get_available_doctors: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e), "doctors": []}


    def _parse_date(self, date_str: str) -> str:
        """Parse various date formats to YYYY-MM-DD"""
        import re
        from datetime import datetime, timedelta
        
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
            print(f"   ❌ No match found for '{doctor_name}'")
            return None
            
        except Exception as e:
            print(f"❌ Error finding doctor: {e}")
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
            print(f"🗓️  Fetching schedule for doctor: {doctor_id}")
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
            from app.schemas.appointment import AppointmentCreate  # Import schema
            
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
                print(f"✅ Appointment booked: APT-{appointment.id}")
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
            print(f"❌ Error in book_appointment: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": f"Booking failed: {str(e)}"
            }


def get_ai_functions() -> List[Dict[str, Any]]:
    """Get list of available functions for GPT-4"""
    return AI_FUNCTIONS
