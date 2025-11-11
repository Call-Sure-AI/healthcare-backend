# app/routes/ai_tools.py - AI-POWERED INTELLIGENT DOCTOR RECOMMENDATION

from datetime import date, datetime, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.services.doctor_service import DoctorService
from app.services.appointment_service import AppointmentService
from app.models.leave import DoctorLeave
from app.schemas.appointment import AppointmentCreate
from qdrant_client import QdrantClient, models
from app.config.voice_config import voice_config
import re
from fastapi import HTTPException
from collections import Counter
import traceback
import json
import openai
import os
from difflib import SequenceMatcher

try:
    qdrant_client = QdrantClient(host=voice_config.QDRANT_HOST, port=voice_config.QDRANT_PORT, api_key=voice_config.QDRANT_API_KEY, https=False)
    print(f"Connected to Qdrant at {voice_config.QDRANT_HOST}:{voice_config.QDRANT_PORT}")
except Exception as e:
    print(f"Failed to connect to Qdrant: {e}")
    qdrant_client = None

OPENAI_API_KEY = getattr(voice_config, "OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))
OPENAI_EMBEDDING_MODEL_NAME = getattr(voice_config, "EMBEDDING_MODEL_NAME", os.getenv("EMBEDDING_MODEL_NAME"))
openai.api_key = OPENAI_API_KEY

try:
    VECTOR_SIZE = 1536
    print(f"Loaded OpenAI embedding model: {OPENAI_EMBEDDING_MODEL_NAME}")
except Exception as e:
    print(f"Failed to set up OpenAI embedding model: {e}")
    VECTOR_SIZE = 0


def get_openai_embedding(query: str, model=OPENAI_EMBEDDING_MODEL_NAME) -> list:
    try:
        response = openai.embeddings.create(input=[query], model=model)
        return response.data[0].embedding
    except Exception as e:
        print(f"Error getting OpenAI embedding: {e}")
        return None


def get_ai_specialization_recommendations(symptom: str) -> List[str]:
    """
    ⚡ AI REASONING: Let GPT-4 determine which specializations can treat the symptom
    """
    try:
        print(f"\n🧠 AI Reasoning: Which specialists treat '{symptom}'?")
        
        prompt = f"""Given symptom/condition: "{symptom}"

List medical specializations that can treat this, in priority order (best first).

Return ONLY a JSON array of specialization names.
Example: ["Neurology", "General Medicine", "Psychiatry"]

Include General Medicine as fallback if applicable.
Max 4 specializations."""

        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=100
        )
        
        result = response.choices[0].message.content.strip()
        specializations = json.loads(result)
        
        print(f"✅ AI recommended: {specializations}")
        return specializations
        
    except Exception as e:
        print(f"❌ AI reasoning error: {e}")
        return ["General Medicine"]


def fuzzy_match_doctor_name(query: str, available_doctors: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    ⚡ Fuzzy match doctor names (handles STT errors like "Anu" → "Aarav")
    """
    if not query or not available_doctors:
        return None
    
    query_clean = query.lower().strip()
    query_clean = query_clean.replace('dr.', '').replace('dr', '').replace('doctor', '').strip()
    
    best_match = None
    best_score = 0.0
    
    for doctor in available_doctors:
        doctor_name = doctor["name"].lower().replace('dr.', '').replace('dr', '').strip()
        
        similarity = SequenceMatcher(None, query_clean, doctor_name).ratio()
        
        query_words = query_clean.split()
        doctor_words = doctor_name.split()
        
        for qword in query_words:
            if len(qword) < 3:
                continue
            for dword in doctor_words:
                word_sim = SequenceMatcher(None, qword, dword).ratio()
                if word_sim > similarity:
                    similarity = word_sim
        
        if similarity > best_score:
            best_score = similarity
            best_match = doctor
    
    if best_score > 0.6:
        print(f"✓ Fuzzy match: {best_match['name']} (score: {best_score:.2f})")
        return best_match
    
    return None


def search_doctor_information(query: str, top_k: int = 3) -> Dict[str, Any]:
    """
    ⚡ HYBRID: Fuzzy name matching + RAG semantic search
    """
    print(f"\n--- RAG Search: '{query}' ---")
    
    # STEP 1: Try fuzzy name matching first (for name-based queries)
    try:
        from app.config.database import SessionLocal
        db = SessionLocal()
        all_doctors = DoctorService.get_all_active_doctors(db)
        db.close()
        
        available_doctors = [
            {
                "doctor_id": doc.doctor_id,
                "name": doc.name,
                "degree": doc.degree,
                "specialization": doc.specialization or "General Medicine"
            }
            for doc in all_doctors
        ]
        
        fuzzy_match = fuzzy_match_doctor_name(query, available_doctors)
        if fuzzy_match:
            return {
                "success": True,
                "results": [fuzzy_match],
                "matched_via": "fuzzy_name"
            }
    except Exception as e:
        print(f"Fuzzy match error: {e}")
    
    # STEP 2: RAG semantic search (for expertise/symptom queries)
    if not qdrant_client:
        return {"success": False, "error": "Qdrant not available"}
    
    try:
        query_vector = get_openai_embedding(query)
        if not query_vector:
            return {"success": False, "error": "Embedding failed"}

        search_result = qdrant_client.search(
            collection_name=voice_config.QDRANT_COLLECTION_NAME,
            query_vector=query_vector,
            limit=top_k,
            with_payload=True
        )

        results = [hit.payload for hit in search_result]
        print(f"✓ RAG: {len(results)} results")
        return {"success": True, "results": results}
        
    except Exception as e:
        print(f"RAG error: {e}")
        traceback.print_exc()
        return {"success": False, "error": str(e)}


def enrich_doctors_with_rag(
    doctors: List[Dict[str, Any]],
    user_context: str
) -> List[Dict[str, Any]]:
    """
    ⚡ RAG ENRICHMENT: Add experience context (optional, ~100ms)
    """
    if not doctors or not user_context or not qdrant_client:
        return doctors
    
    print(f"\n⚡ RAG Enrichment for {len(doctors)} doctors")
    
    enriched = []
    for doctor in doctors:
        doctor_copy = doctor.copy()
        doctor_id = doctor.get("doctor_id")
        name = doctor.get("name", "")
        
        try:
            # Query RAG for doctor + symptom
            search_query = f"{name} {user_context}"
            rag_result = search_doctor_information(search_query, top_k=1)
            
            if rag_result.get("success") and rag_result.get("results"):
                result = rag_result["results"][0]
                
                if result.get("doctor_id") == doctor_id:
                    bio = result.get("bio", "")
                    expertise = result.get("expertise", "")
                    combined = f"{bio} {expertise}".lower()
                    
                    # Check if relevant to symptom
                    if any(word in combined for word in user_context.lower().split()):
                        doctor_copy["has_experience"] = True
                        print(f"  ✓ {name}: Has relevant experience")
        
        except Exception as e:
            print(f"  ✗ Enrichment error: {e}")
        
        enriched.append(doctor_copy)
    
    return enriched


def find_doctors_by_specializations(
    available_doctors: List[Dict[str, Any]],
    specializations: List[str],
    max_results: int = 3
) -> List[Dict[str, Any]]:
    """
    Find doctors matching AI-recommended specializations
    """
    print(f"\n🔍 Searching for: {specializations}")
    
    found_doctors = []
    
    for spec in specializations:
        matches = [
            doc for doc in available_doctors
            if spec.lower() in doc.get("specialization", "").lower()
        ]
        
        if matches:
            print(f"  ✅ Found {len(matches)} {spec} doctor(s)")
            for match in matches:
                if match not in found_doctors:
                    match["matched_specialization"] = spec
                    found_doctors.append(match)
                    if len(found_doctors) >= max_results:
                        return found_doctors
    
    if not found_doctors:
        print(f"  ⚠️ No exact match, using fallback")
        for doc in available_doctors[:max_results]:
            doc["matched_specialization"] = "available"
            found_doctors.append(doc)
    
    return found_doctors[:max_results]


AI_FUNCTIONS = [
    {
        "name": "search_doctor_information",
        "description": "Search for doctor by name (handles typos/STT errors like 'Anu Patel' → 'Aarav Patel') or get expertise info",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Doctor name or expertise query",
                },
                "top_k": {"type": "integer", "default": 3}
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_available_doctors",
        "description": "Get intelligent doctor recommendations. AI analyzes symptoms and recommends appropriate specialists with reasons.",
        "parameters": {
            "type": "object",
            "properties": {
                "user_context": {
                    "type": "string",
                    "description": "Patient's symptoms/condition (e.g., 'headache', 'fever')"
                }
            },
            "required": []
        }
    },
    {
        "name": "get_doctor_schedule",
        "description": "Get available dates for a specific doctor",
        "parameters": {
            "type": "object",
            "properties": {
                "doctor_id": {"type": "string", "description": "Doctor ID (e.g., DOC2011)"}
            },
            "required": ["doctor_id"]
        }
    },
    {
        "name": "get_available_slots",
        "description": "Get time slots for doctor on specific date",
        "parameters": {
            "type": "object",
            "properties": {
                "doctor_id": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"}
            },
            "required": ["doctor_id", "date"]
        }
    },
    {
        "name": "get_appointment_details",
        "description": "Get existing appointment details",
        "parameters": {
            "type": "object",
            "properties": {
                "patient_name": {"type": "string"},
                "patient_phone": {"type": "string"}
            },
            "required": ["patient_name", "patient_phone"]
        }
    },
    {
        "name": "book_appointment_in_hour_range",
        "description": "Book appointment in specific hour",
        "parameters": {
            "type": "object",
            "properties": {
                "patient_name": {"type": "string"},
                "patient_phone": {"type": "string"},
                "doctor_id": {"type": "string"},
                "appointment_date": {"type": "string"},
                "time_range": {"type": "string", "description": "e.g., '3 PM'"},
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
        self.functions = {
            "get_available_doctors": self.get_available_doctors,
            "get_available_slots": self.get_available_slots,
            "book_appointment_in_hour_range": self.book_appointment_in_hour_range,
            "get_doctor_schedule": self.get_doctor_schedule,
            "get_appointment_details": self.get_appointment_details,
            "search_doctor_information": search_doctor_information
        }
    
    def execute_function(self, function_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        try:
            print(f"\n--- Executing: {function_name} ---")
            print(f"Arguments: {arguments}")

            if function_name in self.functions:
                func_to_call = self.functions[function_name]
                is_method = hasattr(func_to_call, '__self__') and func_to_call.__self__ is self

                if is_method:
                    result = func_to_call(**arguments)
                else:
                    result = func_to_call(**arguments)

                print(f"--- {function_name} complete ---")
                
                if isinstance(result, dict) and 'success' in result:
                    return result
                elif isinstance(result, dict):
                    result['success'] = True
                    return result
                else:
                    return {"success": True, "result": result}
            else:
                return {"success": False, "error": f"Unknown function: {function_name}"}
                
        except Exception as e:
            print(f"Error in {function_name}: {e}")
            traceback.print_exc()
            return {"success": False, "error": str(e)}

    def get_available_doctors(self, user_context: str = "") -> Dict[str, Any]:
        """
        ⚡ AI-POWERED: Intelligent doctor recommendations
        """
        try:            
            print(f"\n{'='*80}")
            print(f"🧠 AI-POWERED DOCTOR RECOMMENDATION")
            print(f"User context: '{user_context}'")
            print(f"{'='*80}\n")
            
            # Get active doctors
            doctors = DoctorService.get_all_active_doctors(self.db)
            today = date.today()
            doctors_on_leave = self.db.query(DoctorLeave.doctor_id).filter(
                DoctorLeave.start_date <= today,
                DoctorLeave.end_date >= today
            ).all()
            
            on_leave_ids = [leave.doctor_id for leave in doctors_on_leave]

            active_doctors = []
            for doc in doctors:
                if doc.doctor_id not in on_leave_ids:
                    active_doctors.append({
                        "doctor_id": doc.doctor_id,
                        "name": doc.name,
                        "degree": doc.degree,
                        "specialization": doc.specialization or "General Medicine"
                    })
            
            print(f"📋 {len(active_doctors)} doctors available")

            if not active_doctors:
                return {
                    "success": False,
                    "message": "No doctors available",
                    "doctors": []
                }
            
            # ⚡ STEP 1: AI determines best specializations
            if user_context:
                specializations = get_ai_specialization_recommendations(user_context)
            else:
                specializations = ["General Medicine"]
            
            # ⚡ STEP 2: Find matching doctors
            recommended_doctors = find_doctors_by_specializations(
                active_doctors,
                specializations,
                max_results=3
            )
            
            # ⚡ STEP 3: RAG enrichment (optional, ~100ms)
            if user_context:
                recommended_doctors = enrich_doctors_with_rag(
                    recommended_doctors,
                    user_context
                )
            
            # Add recommendation reasons
            for doc in recommended_doctors:
                spec = doc.get("matched_specialization", "available")
                has_exp = doc.get("has_experience", False)
                
                if has_exp:
                    doc["recommendation_reason"] = f"{spec}, experienced with {user_context}"
                elif spec != "available":
                    doc["recommendation_reason"] = f"{spec} specialist"
                else:
                    doc["recommendation_reason"] = f"available {doc.get('specialization', 'doctor')}"
            
            print(f"\n✅ Top {len(recommended_doctors)} doctors:")
            for doc in recommended_doctors:
                print(f"  - {doc['name']}: {doc.get('recommendation_reason', 'available')}")
            print(f"\n{'='*80}\n")

            return {
                "success": True,
                "count": len(recommended_doctors),
                "doctors": recommended_doctors,
                "ai_recommended_specializations": specializations
            }
            
        except Exception as e:
            print(f"Error: {e}")
            traceback.print_exc()
            return {"success": False, "error": str(e), "doctors": []}

    def get_appointment_details(self, patient_name: str, patient_phone: str) -> Dict[str, Any]:
        """Fetch appointment details"""
        try:
            print(f"Searching appointment: {patient_name} ({patient_phone})")
            
            details = AppointmentService.get_appointment_details(self.db, patient_name, patient_phone)
            
            if details:
                return {"success": True, "appointment": details}
            else:
                return {"success": False, "error": "No appointments found"}
        except Exception as e:
            print(f"Error: {e}")
            return {"success": False, "error": str(e)}

    def _parse_date(self, date_str: str) -> str:
        """Parse date to YYYY-MM-DD"""
        date_str = date_str.lower().strip()
        today = datetime.now().date()

        if "tomorrow" in date_str:
            return (today + timedelta(days=1)).strftime("%Y-%m-%d")
        if "today" in date_str:
            return today.strftime("%Y-%m-%d")
        if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
            return date_str

        months = {
            'january': 1, 'jan': 1, 'february': 2, 'feb': 2, 'march': 3, 'mar': 3,
            'april': 4, 'apr': 4, 'may': 5, 'june': 6, 'jun': 6,
            'july': 7, 'jul': 7, 'august': 8, 'aug': 8, 'september': 9, 'sep': 9,
            'october': 10, 'oct': 10, 'november': 11, 'nov': 11, 'december': 12, 'dec': 12
        }

        month_num = None
        for month_name, num in months.items():
            if month_name in date_str:
                month_num = num
                break

        numbers = re.findall(r'\d+', date_str)

        if month_num and len(numbers) == 1:
            day = int(numbers[0])
            year = today.year
            try:
                parsed_date = datetime(year, month_num, day).date()
                if parsed_date < today:
                    year += 1
            except ValueError:
                pass
            return f"{year:04d}-{month_num:02d}-{day:02d}"

        if month_num and len(numbers) >= 2:
            day = int(numbers[0])
            year = int(numbers[1]) if len(numbers[1]) == 4 else int(numbers[0])
            if year < 100:
                year += 2000
            return f"{year:04d}-{month_num:02d}-{day:02d}"
        
        if len(numbers) >= 3:
            day, month, year = int(numbers[0]), int(numbers[1]), int(numbers[2])
            if year < 100:
                year += 2000
            return f"{year:04d}-{month:02d}-{day:02d}"
        
        if len(numbers) == 2:
            day, month = int(numbers[0]), int(numbers[1])
            year = today.year
            return f"{year:04d}-{month:02d}-{day:02d}"
        
        return date_str

    def _find_doctor_id_by_name(self, doctor_name: str) -> str:
        """Find doctor by name (fuzzy)"""
        try:
            doctors = DoctorService.get_all_doctors(self.db)
            doctor_name_clean = doctor_name.lower().replace('dr.', '').replace('dr', '').replace('doctor', '').strip()
            
            for doc in doctors:
                if doc.name.lower().strip() == doctor_name_clean:
                    return doc.doctor_id

            for doc in doctors:
                if doctor_name_clean in doc.name.lower() or doc.name.lower() in doctor_name_clean:
                    return doc.doctor_id
            
            return None
        except Exception as e:
            print(f"Error: {e}")
            return None

    def get_available_slots(self, doctor_id: str, date: str) -> Dict[str, Any]:
        """Get time slots"""
        try:
            if not doctor_id.startswith('DOC'):
                resolved_id = self._find_doctor_id_by_name(doctor_id)
                if resolved_id:
                    doctor_id = resolved_id
                else:
                    return {"success": False, "error": f"Doctor '{doctor_id}' not found", "slots": []}
            
            formatted_date = self._parse_date(date)
            
            date_obj = datetime.strptime(formatted_date, "%Y-%m-%d").date()
            if date_obj < datetime.now().date():
                return {"success": False, "error": f"Date {formatted_date} is in past", "slots": []}
            
            result = AppointmentService.get_available_slots(self.db, doctor_id, formatted_date)
            
            if "available_slots" in result:
                slots = result["available_slots"]
                if not slots:
                    return {"success": False, "error": f"No slots on {formatted_date}", "slots": []}
                return {"success": True, "doctor_id": doctor_id, "date": formatted_date, "slots": slots, "count": len(slots)}
            else:
                return {"success": False, "error": result.get("error", "No slots"), "slots": []}
                
        except Exception as e:
            print(f"Error: {e}")
            traceback.print_exc()
            return {"success": False, "error": str(e), "slots": []}

    def get_doctor_schedule(self, doctor_id: str) -> Dict[str, Any]:
        """Get available dates"""
        try:
            if not doctor_id.startswith('DOC'):
                resolved_id = self._find_doctor_id_by_name(doctor_id)
                if not resolved_id:
                    return {"success": False, "error": f"Doctor '{doctor_id}' not found"}
                doctor_id = resolved_id

            available_dates = DoctorService.get_doctor_schedule(self.db, doctor_id, date.today())
            
            if not available_dates:
                return {"success": False, "error": "No upcoming availability"}
            
            return {"success": True, "doctor_id": doctor_id, "available_dates": available_dates}
        except Exception as e:
            print(f"Error: {e}")
            return {"success": False, "error": str(e)}

    def book_appointment_in_hour_range(
        self,
        patient_name: str,
        patient_phone: str,
        doctor_id: str,
        appointment_date: str,
        time_range: str,
        reason: str = ""
    ) -> Dict[str, Any]:
        """Book in hour range"""
        try:
            numbers = re.findall(r'\d+', time_range)
            if not numbers:
                return {"success": False, "error": "Could not parse time"}
            
            hour = int(numbers[0])
            if "pm" in time_range.lower() and hour < 12:
                hour += 12
            elif "am" in time_range.lower() and hour == 12:
                hour = 0
            
            slots_result = self.get_available_slots(doctor_id, appointment_date)
            if not slots_result.get("success"):
                return {"success": False, "error": slots_result.get("error")}
            
            available_slots = slots_result.get("slots", [])
            slots_in_hour = [s for s in available_slots if s.startswith(f"{hour:02d}:")]
            
            if not slots_in_hour:
                return {"success": False, "error": f"No slots between {hour}:00-{hour+1}:00"}
            
            for slot in sorted(slots_in_hour):
                try:
                    appointment_data = AppointmentCreate(
                        patient_name=patient_name.strip(),
                        patient_phone=patient_phone.strip(),
                        doctor_id=doctor_id,
                        appointment_date=appointment_date,
                        appointment_time=slot,
                        notes=reason or "Booked via voice",
                        status="SCHEDULED"
                    )
                    
                    appointment = AppointmentService.create_appointment(self.db, appointment_data)
                    if appointment:
                        doctor = DoctorService.get_doctor_by_id(self.db, doctor_id)
                        return {
                            "success": True,
                            "appointment": {
                                "id": appointment.id,
                                "confirmation_number": f"APT-{appointment.id}",
                                "patient_name": appointment.patient_name,
                                "doctor_id": appointment.doctor_id,
                                "doctor_name": doctor.name if doctor else "Unknown",
                                "appointment_date": str(appointment.appointment_date),
                                "appointment_time": appointment.appointment_time
                            }
                        }
                except Exception as e:
                    self.db.rollback()
                    continue
            
            return {"success": False, "error": f"All slots in hour {hour} unavailable"}
            
        except Exception as e:
            print(f"Error: {e}")
            traceback.print_exc()
            self.db.rollback()
            return {"success": False, "error": str(e)}


def get_ai_functions() -> List[Dict[str, Any]]:
    return AI_FUNCTIONS
