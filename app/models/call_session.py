from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Boolean, func
from app.config.database import Base


class CallSession(Base):
    __tablename__ = "call_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    call_sid = Column(String(100), unique=True, index=True, nullable=False)
    from_number = Column(String(20), nullable=False)
    to_number = Column(String(20), nullable=False)

    patient_name = Column(String(100))
    patient_phone = Column(String(20))

    status = Column(String(50), default="initiated")  # initiated, in_progress, completed, failed

    conversation_history = Column(JSON, default=list)
    current_step = Column(String(50), default="greeting")

    selected_doctor_id = Column(String(50))
    selected_date = Column(String(20))
    selected_time = Column(String(20))
    reason = Column(Text)
    appointment_id = Column(Integer)

    duration_seconds = Column(Integer, default=0)
    started_at = Column(DateTime, server_default=func.now())
    ended_at = Column(DateTime)
    error_message = Column(Text)

    is_booking_confirmed = Column(Boolean, default=False)
    sms_sent = Column(Boolean, default=False)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    def to_dict(self):
        """Convert model to dictionary"""
        return {
            "id": self.id,
            "call_sid": self.call_sid,
            "from_number": self.from_number,
            "patient_name": self.patient_name,
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "is_booking_confirmed": self.is_booking_confirmed,
            "appointment_id": self.appointment_id,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
