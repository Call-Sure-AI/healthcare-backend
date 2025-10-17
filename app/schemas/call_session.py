from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class ConversationMessage(BaseModel):
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: datetime


class CallSessionBase(BaseModel):
    call_sid: str
    from_number: str
    to_number: str


class CallSessionCreate(CallSessionBase):
    pass


class CallSessionUpdate(BaseModel):
    patient_name: Optional[str] = None
    patient_phone: Optional[str] = None
    status: Optional[str] = None
    current_step: Optional[str] = None
    conversation_history: Optional[List[Dict[str, Any]]] = None
    selected_doctor_id: Optional[str] = None
    selected_date: Optional[str] = None
    selected_time: Optional[str] = None
    reason: Optional[str] = None
    appointment_id: Optional[int] = None
    duration_seconds: Optional[int] = None
    is_booking_confirmed: Optional[bool] = None
    error_message: Optional[str] = None


class CallSessionResponse(CallSessionBase):
    id: int
    patient_name: Optional[str]
    status: str
    current_step: str
    is_booking_confirmed: bool
    appointment_id: Optional[int]
    duration_seconds: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class CallSessionDetail(CallSessionResponse):
    conversation_history: List[Dict[str, Any]]
    selected_doctor_id: Optional[str]
    selected_date: Optional[str]
    selected_time: Optional[str]
    reason: Optional[str]
    error_message: Optional[str]
    sms_sent: bool
    
    class Config:
        from_attributes = True
