from pydantic import BaseModel, Field
from typing import Optional
from datetime import date, time
from enum import Enum

class LeaveType(str, Enum):
    full_day = "full_day"
    partial = "partial"

class LeaveBase(BaseModel):
    type: LeaveType = Field(..., description="full_day or partial")
    start_date: date
    end_date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    reason: Optional[str] = Field(None, max_length=300)

class LeaveCreate(LeaveBase):
    pass

class LeaveResponse(LeaveBase):
    id: int
    doctor_id: str

    class Config:
        from_attributes = True
