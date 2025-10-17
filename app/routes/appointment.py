from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List
from app.config.database import get_db
from app.schemas.appointment import AppointmentCreate, AppointmentUpdate, AppointmentResponse
from app.services.appointment_service import AppointmentService

router = APIRouter(prefix="/appointments", tags=["Appointments"])

@router.post("/", response_model=AppointmentResponse, status_code=201)
def create_appointment(appointment: AppointmentCreate, db: Session = Depends(get_db)):
    """Book a new appointment"""
    return AppointmentService.create_appointment(db, appointment)

# NEW ENDPOINT - Check available slots
@router.get("/available-slots/{doctor_id}/{date}")
def get_available_slots(doctor_id: str, date: str, db: Session = Depends(get_db)):
    """Get available time slots for a doctor on a specific date"""
    return AppointmentService.get_available_slots(db, doctor_id, date)

@router.get("/{appointment_id}", response_model=AppointmentResponse)
def get_appointment(appointment_id: int, db: Session = Depends(get_db)):
    """Get appointment by ID"""
    return AppointmentService.get_appointment_by_id(db, appointment_id)

@router.get("/", response_model=List[AppointmentResponse])
def get_all_appointments(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Get all appointments with pagination"""
    return AppointmentService.get_all_appointments(db, skip, limit)

@router.get("/doctor/{doctor_id}", response_model=List[AppointmentResponse])
def get_doctor_appointments(doctor_id: str, db: Session = Depends(get_db)):
    """Get all appointments for a specific doctor"""
    return AppointmentService.get_appointments_by_doctor(db, doctor_id)

@router.get("/date/{appointment_date}", response_model=List[AppointmentResponse])
def get_appointments_by_date(appointment_date: str, db: Session = Depends(get_db)):
    """Get all appointments for a specific date"""
    return AppointmentService.get_appointments_by_date(db, appointment_date)

@router.put("/{appointment_id}", response_model=AppointmentResponse)
def update_appointment(
    appointment_id: int,
    appointment: AppointmentUpdate,
    db: Session = Depends(get_db)
):
    """Update appointment details"""
    return AppointmentService.update_appointment(db, appointment_id, appointment)

@router.patch("/{appointment_id}/cancel", response_model=AppointmentResponse)
def cancel_appointment(appointment_id: int, db: Session = Depends(get_db)):
    """Cancel an appointment"""
    return AppointmentService.cancel_appointment(db, appointment_id)

@router.delete("/{appointment_id}")
def delete_appointment(appointment_id: int, db: Session = Depends(get_db)):
    """Delete an appointment"""
    return AppointmentService.delete_appointment(db, appointment_id)

@router.get("/doctor-statistics/{doctor_id}/{appointment_date}")
def get_doctor_statistics(
    doctor_id: str,
    appointment_date: str,
    db: Session = Depends(get_db)
):
    """Get appointment statistics for a doctor on a specific date"""
    return AppointmentService.get_doctor_statistics(db, doctor_id, appointment_date)
