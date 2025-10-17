from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from typing import List
from app.config.database import get_db
from app.schemas.doctor import DoctorCreate, DoctorUpdate, DoctorResponse
from app.services.doctor_service import DoctorService

router = APIRouter(prefix="/doctors", tags=["Doctors"])

@router.post(
    "/",
    response_model=DoctorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new doctor",
    description="Register a new doctor with their details, shift timings, and availability dates",
    response_description="Returns the created doctor details",
    responses={
        201: {
            "description": "Doctor created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "id": 1,
                        "name": "Dr. Sarah Johnson",
                        "degree": "MBBS, MD (Cardiology)",
                        "doctor_id": "DOC001",
                        "shift_timings": {
                            "monday": ["09:00-12:00", "14:00-17:00"],
                            "tuesday": ["09:00-12:00"]
                        },
                        "availability_dates": ["2025-10-13", "2025-10-14"]
                    }
                }
            }
        },
        400: {
            "description": "Invalid request or doctor ID already exists",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Doctor with ID DOC001 already exists"
                    }
                }
            }
        }
    }
)
def create_doctor(doctor: DoctorCreate, db: Session = Depends(get_db)):
    """
    Create a new doctor with the following information:
    
    - **name**: Full name of the doctor
    - **degree**: Academic qualifications
    - **doctor_id**: Unique identifier for the doctor
    - **shift_timings**: JSON object with day-wise shift timings
    - **availability_dates**: List of dates when doctor is available
    """
    return DoctorService.create_doctor(db, doctor)

@router.get(
    "/{doctor_id}",
    response_model=DoctorResponse,
    summary="Get doctor by ID",
    description="Retrieve detailed information about a specific doctor",
    responses={
        200: {"description": "Doctor details retrieved successfully"},
        404: {"description": "Doctor not found"}
    }
)
def get_doctor(doctor_id: str, db: Session = Depends(get_db)):
    """Get specific doctor by their unique doctor_id"""
    return DoctorService.get_doctor_by_id(db, doctor_id)

@router.get(
    "/",
    response_model=List[DoctorResponse],
    summary="Get all doctors",
    description="Retrieve a paginated list of all registered doctors",
    responses={
        200: {"description": "List of doctors retrieved successfully"}
    }
)
def get_all_doctors(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=100, description="Maximum number of records to return"),
    db: Session = Depends(get_db)
):
    """
    Get all doctors with pagination
    
    - **skip**: Number of records to skip (for pagination)
    - **limit**: Maximum number of records to return (1-100)
    """
    return DoctorService.get_all_doctors(db, skip, limit)

@router.put(
    "/{doctor_id}",
    response_model=DoctorResponse,
    summary="Update doctor details",
    description="Update existing doctor information (partial updates allowed)",
    responses={
        200: {"description": "Doctor updated successfully"},
        404: {"description": "Doctor not found"}
    }
)
def update_doctor(
    doctor_id: str,
    doctor: DoctorUpdate,
    db: Session = Depends(get_db)
):
    """Update doctor details. Only provided fields will be updated."""
    return DoctorService.update_doctor(db, doctor_id, doctor)

@router.delete(
    "/{doctor_id}",
    summary="Delete a doctor",
    description="Remove a doctor from the system",
    responses={
        200: {"description": "Doctor deleted successfully"},
        404: {"description": "Doctor not found"}
    }
)
def delete_doctor(doctor_id: str, db: Session = Depends(get_db)):
    """Delete a doctor by their doctor_id"""
    return DoctorService.delete_doctor(db, doctor_id)

@router.patch(
    "/{doctor_id}/activate_leave",
    summary="Doctor Leave",
    description="Set a Doctor on Leave for the day - creates a full day leave entry",
    responses={
        200: {"description": "Doctor marked as on leave and leave entry created"},
        404: {"description": "Doctor not found"}
    }
)
def leave_doctor(doctor_id: str, db: Session = Depends(get_db)):
    """Mark doctor as on leave for today and create a full-day leave entry"""
    return DoctorService.leave_doctor(db, doctor_id)


@router.patch(
    "/{doctor_id}/deactivate_leave",
    summary="Doctor Activate",
    description="Set a Doctor as Active - removes leave entry if it matches today's date",
    responses={
        200: {"description": "Doctor activated successfully, leave cancelled if applicable"},
        404: {"description": "Doctor not found"}
    }
)
def deactivate_leave_doctor(doctor_id: str, db: Session = Depends(get_db)):
    """Mark doctor as active and remove leave entry if it exists for today"""
    return DoctorService.deactivate_leave_doctor(db, doctor_id)

