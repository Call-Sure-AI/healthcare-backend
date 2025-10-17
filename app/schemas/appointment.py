from pydantic import BaseModel, Field, EmailStr
from datetime import datetime
from typing import Optional
from app.models.appointment import AppointmentStatus

class AppointmentBase(BaseModel):
    patient_name: str = Field(..., min_length=1, max_length=100)
    patient_phone: str = Field(..., min_length=10, max_length=15)
    patient_email: Optional[EmailStr] = None
    doctor_id: str = Field(..., min_length=1, max_length=50)
    appointment_date: str = Field(..., description="Format: YYYY-MM-DD")
    appointment_time: str = Field(..., description="Format: HH:MM")
    notes: Optional[str] = Field(None, max_length=500)

class AppointmentCreate(AppointmentBase):
    pass

class AppointmentUpdate(BaseModel):
    appointment_date: Optional[str] = None
    appointment_time: Optional[str] = None
    status: Optional[AppointmentStatus] = None
    notes: Optional[str] = None

class AppointmentResponse(AppointmentBase):
    id: int
    status: AppointmentStatus
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True
