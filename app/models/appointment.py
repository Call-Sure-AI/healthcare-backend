from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.config.database import Base

class AppointmentStatus(enum.Enum):
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"

class Appointment(Base):
    __tablename__ = "appointments"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    patient_name = Column(String(100), nullable=False)
    patient_phone = Column(String(15), nullable=False)
    patient_email = Column(String(100))
    doctor_id = Column(String(50), ForeignKey("doctors.doctor_id"), nullable=False)
    appointment_date = Column(String(20), nullable=False)  # Format: YYYY-MM-DD
    appointment_time = Column(String(20), nullable=False)  # Format: HH:MM
    status = Column(Enum(AppointmentStatus), default=AppointmentStatus.SCHEDULED)
    notes = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<Appointment {self.patient_name} with {self.doctor_id} on {self.appointment_date}>"
