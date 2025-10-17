from sqlalchemy.orm import Session
from app.models.doctor import Doctor
from app.models.appointment import Appointment
from app.schemas.doctor import DoctorCreate, DoctorUpdate
from app.models.appointment import AppointmentStatus
from app.models.doctor import DoctorStatus
from app.models.leave import DoctorLeave, LeaveType
from fastapi import HTTPException, status
from datetime import datetime, date


class DoctorService:
    @staticmethod
    def create_doctor(db: Session, doctor_data: DoctorCreate):
        existing_doctor = db.query(Doctor).filter(Doctor.doctor_id == doctor_data.doctor_id).first()
        if existing_doctor:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Doctor with ID {doctor_data.doctor_id} already exists"
            )
        
        db_doctor = Doctor(**doctor_data.model_dump())
        db.add(db_doctor)
        db.commit()
        db.refresh(db_doctor)
        return db_doctor
    
    @staticmethod
    def get_doctor_by_id(db: Session, doctor_id: str):
        doctor = db.query(Doctor).filter(Doctor.doctor_id == doctor_id).first()
        if not doctor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Doctor with ID {doctor_id} not found"
            )
        return doctor
    
    @staticmethod
    def get_all_doctors(db: Session, skip: int = 0, limit: int = 100):
        return db.query(Doctor).filter(Doctor.status.in_([DoctorStatus.ACTIVE, DoctorStatus.INACTIVE])).all()

    @staticmethod
    def get_all_active_doctors(db: Session, skip: int = 0, limit: int = 100):
        return db.query(Doctor).filter(Doctor.status == DoctorStatus.ACTIVE).all()

    @staticmethod
    def update_doctor(db: Session, doctor_id: str, doctor_data: DoctorUpdate):
        doctor = DoctorService.get_doctor_by_id(db, doctor_id)
        
        update_data = doctor_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(doctor, key, value)
        
        db.commit()
        db.refresh(doctor)
        return doctor
    
    @staticmethod
    def delete_doctor(db: Session, doctor_id: str):
        doctor = DoctorService.get_doctor_by_id(db, doctor_id)
        doctor.status = DoctorStatus.DELETED
        db.commit()
        db.refresh(doctor)
        db.query(Appointment).filter(
            Appointment.doctor_id == doctor_id,
            Appointment.status == AppointmentStatus.SCHEDULED
        ).update(
            {"status": AppointmentStatus.CANCELLED, "notes": "Cancelled due to doctor deletion"},
            synchronize_session=False
        )
        db.commit()
        return {"message": f"Doctor {doctor_id} marked as deleted, appointments cancelled"}

    @staticmethod
    def leave_doctor(db: Session, doctor_id: str):
        """
        Mark doctor as on leave for today:
        1. Set doctor status to INACTIVE
        2. Create a full-day leave entry
        3. Cancel today's scheduled appointments
        """
        today = date.today()

        doctor = DoctorService.get_doctor_by_id(db, doctor_id)
        if not doctor:
            raise HTTPException(status_code=404, detail=f"Doctor {doctor_id} not found")

        doctor.status = DoctorStatus.INACTIVE
        doctor.on_leave = True

        leave_entry = DoctorLeave(
            doctor_id=doctor_id,
            type=LeaveType.FULL_DAY,
            start_date=today,
            end_date=today,
            start_time=None,
            end_time=None,
            reason="Doctor marked as on leave"
        )
        db.add(leave_entry)

        cancelled_count = db.query(Appointment).filter(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == today.strftime('%Y-%m-%d'),
            Appointment.status == AppointmentStatus.SCHEDULED
        ).update(
            {
                "status": AppointmentStatus.CANCELLED,
                "notes": f"Cancelled due to doctor being on leave"
            },
            synchronize_session=False
        )
        
        db.commit()
        db.refresh(doctor)
        
        return {
            "message": f"Doctor {doctor_id} marked as on leave",
            "leave_id": leave_entry.id,
            "cancelled_appointments": cancelled_count,
            "leave_date": today.strftime('%Y-%m-%d')
        }

    @staticmethod
    def deactivate_leave_doctor(db: Session, doctor_id: str):
        """
        Mark doctor as active:
        1. Set doctor status to ACTIVE
        2. Delete leave entry if it matches today's date
        3. Re-schedule today's cancelled appointments
        """
        today = date.today()

        doctor = DoctorService.get_doctor_by_id(db, doctor_id)
        if not doctor:
            raise HTTPException(status_code=404, detail=f"Doctor {doctor_id} not found")

        doctor.status = DoctorStatus.ACTIVE
        doctor.on_leave = False

        leave_entry = db.query(DoctorLeave).filter(
            DoctorLeave.doctor_id == doctor_id,
            DoctorLeave.start_date <= today,
            DoctorLeave.end_date >= today,
            DoctorLeave.type == LeaveType.FULL_DAY
        ).first()
        
        deleted_leave = False
        if leave_entry:
            db.delete(leave_entry)
            deleted_leave = True

        rescheduled_count = db.query(Appointment).filter(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == today.strftime('%Y-%m-%d'),
            Appointment.status == AppointmentStatus.CANCELLED
        ).update(
            {
                "status": AppointmentStatus.SCHEDULED,
                "notes": "Re-scheduled - Doctor is now available"
            },
            synchronize_session=False
        )
        
        db.commit()
        db.refresh(doctor)
        
        return {
            "message": f"Doctor {doctor_id} marked as active",
            "leave_cancelled": deleted_leave,
            "rescheduled_appointments": rescheduled_count,
            "date": today.strftime('%Y-%m-%d')
        }
