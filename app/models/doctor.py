from sqlalchemy import Column, Integer, String, JSON, Enum as SQLEnum
from app.config.database import Base
import enum

class DoctorStatus(enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DELETED = "DELETED"

class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    degree = Column(String(100), nullable=False)
    doctor_id = Column(String(50), unique=True, nullable=False, index=True)
    shift_timings = Column(JSON, nullable=False)
    availability_dates = Column(JSON, nullable=False)
    status = Column(SQLEnum(DoctorStatus), default=DoctorStatus.ACTIVE)
    specialization = Column(String(100), default="General Medicine")
