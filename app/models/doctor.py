from sqlalchemy import Column, Integer, String, JSON, Enum
from app.config.database import Base
import enum

class DoctorStatus(enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    DELETED = "deleted"

class Doctor(Base):
    __tablename__ = "doctors"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    degree = Column(String(100), nullable=False)
    doctor_id = Column(String(50), unique=True, nullable=False, index=True)
    shift_timings = Column(JSON, nullable=False)  # {"monday": ["09:00-12:00", "14:00-17:00"], ...}
    availability_dates = Column(JSON, nullable=False)  # ["2025-10-10", "2025-10-11", ...]
    status = Column(Enum(DoctorStatus), default=DoctorStatus.ACTIVE)
    
    def __repr__(self):
        return f"<Doctor {self.name} - {self.doctor_id}>"
