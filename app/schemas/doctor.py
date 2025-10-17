from pydantic import BaseModel, Field
from typing import Dict, List
from app.models.doctor import DoctorStatus

class DoctorBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    degree: str = Field(..., min_length=1, max_length=100)
    doctor_id: str = Field(..., min_length=1, max_length=50)
    shift_timings: Dict[str, List[str]] = Field(..., description="Day-wise shift timings")
    availability_dates: List[str] = Field(..., description="List of available dates")
    status: DoctorStatus

class DoctorCreate(DoctorBase):
    pass

class DoctorUpdate(BaseModel):
    name: str | None = None
    degree: str | None = None
    shift_timings: Dict[str, List[str]] | None = None
    availability_dates: List[str] | None = None

class DoctorResponse(DoctorBase):
    id: int
    
    class Config:
        from_attributes = True
