from sqlalchemy import Column, Integer, String, Date, Time, Enum, DateTime, ForeignKey, func
import enum
from app.config.database import Base
from sqlalchemy import Enum as SAEnum

class LeaveType(enum.Enum):
    FULL_DAY = "full_day"
    PARTIAL = "partial"

class DoctorLeave(Base):
    __tablename__ = "doctor_leaves"

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(String(50), ForeignKey("doctors.doctor_id", ondelete="CASCADE"), index=True, nullable=False)
    type = Column(
        SAEnum(
            LeaveType, 
            name="leavetype",
            values_callable=lambda e: [m.value for m in e]
        ),
        nullable=False
    )   
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    reason = Column(String(300), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
