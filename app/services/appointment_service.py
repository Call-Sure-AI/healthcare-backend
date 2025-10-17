from sqlalchemy.orm import Session
from app.models.appointment import Appointment, AppointmentStatus
from app.schemas.appointment import AppointmentCreate, AppointmentUpdate
from app.services.doctor_service import DoctorService
from fastapi import HTTPException, status
from datetime import datetime, timedelta
from collections import defaultdict

class AppointmentService:
    # Maximum appointments per hour per doctor
    MAX_APPOINTMENTS_PER_HOUR = 4
    APPOINTMENT_INTERVAL_MINUTES = 15  # 15-minute slots
    
    @staticmethod
    def get_hour_from_time(time_str: str) -> int:
        """Extract hour from time string (HH:MM format)"""
        return int(time_str.split(":")[0])
    
    @staticmethod
    def check_hourly_capacity(db: Session, doctor_id: str, appointment_date: str, appointment_time: str):
        """
        Check if the doctor has capacity in the requested hour.
        Maximum 4 appointments per hour allowed.
        """
        appointment_hour = AppointmentService.get_hour_from_time(appointment_time)
        
        # Query all scheduled appointments for this doctor on this date
        scheduled_appointments = db.query(Appointment).filter(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == appointment_date,
            Appointment.status == AppointmentStatus.SCHEDULED
        ).all()
        
        # Count appointments in the requested hour
        appointments_in_hour = 0
        for apt in scheduled_appointments:
            apt_hour = AppointmentService.get_hour_from_time(apt.appointment_time)
            if apt_hour == appointment_hour:
                appointments_in_hour += 1
        
        if appointments_in_hour >= AppointmentService.MAX_APPOINTMENTS_PER_HOUR:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Doctor has reached maximum capacity ({AppointmentService.MAX_APPOINTMENTS_PER_HOUR} appointments) for the hour {appointment_hour}:00-{appointment_hour + 1}:00"
            )
        
        return True
    
    @staticmethod
    def validate_time_format(appointment_time: str):
        """Validate that appointment time is in 15-minute intervals"""
        try:
            time_obj = datetime.strptime(appointment_time, "%H:%M")
            minutes = time_obj.minute
            
            # Check if minutes are in 15-minute intervals (0, 15, 30, 45)
            if minutes not in [0, 15, 30, 45]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Appointment time must be in 15-minute intervals (00, 15, 30, 45). Invalid time: {appointment_time}"
                )
            return time_obj.time()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid time format. Use HH:MM format (e.g., 09:30)"
            )
    
    @staticmethod
    def validate_appointment_availability(doctor, appointment_date: str, appointment_time: str):
        """
        Validate if the appointment falls within doctor's availability
        """
        # Check if appointment date is in doctor's availability_dates
        if appointment_date not in doctor.availability_dates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Doctor is not available on {appointment_date}. Available dates: {', '.join(doctor.availability_dates)}"
            )
        
        # Get the day of week from appointment date
        date_obj = datetime.strptime(appointment_date, "%Y-%m-%d")
        day_name = date_obj.strftime("%A").lower()
        
        # Check if doctor has shift timings for this day
        if day_name not in doctor.shift_timings:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Doctor has no shift scheduled for {day_name.capitalize()}"
            )
        
        # Validate time format and 15-minute intervals
        appointment_time_obj = AppointmentService.validate_time_format(appointment_time)
        
        # Check if appointment time falls within any of the shift timings
        shift_slots = doctor.shift_timings[day_name]
        is_within_shift = False
        
        for shift_slot in shift_slots:
            try:
                start_time_str, end_time_str = shift_slot.split("-")
                start_time = datetime.strptime(start_time_str.strip(), "%H:%M").time()
                end_time = datetime.strptime(end_time_str.strip(), "%H:%M").time()
                
                if start_time <= appointment_time_obj < end_time:
                    is_within_shift = True
                    break
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Invalid shift timing format in database: {shift_slot}"
                )
        
        if not is_within_shift:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Appointment time {appointment_time} is outside doctor's shift hours on {day_name.capitalize()}. Available slots: {', '.join(shift_slots)}"
            )
        
        return True
    
    @staticmethod
    def create_appointment(db: Session, appointment_data: AppointmentCreate):
        # Verify doctor exists
        doctor = DoctorService.get_doctor_by_id(db, appointment_data.doctor_id)
        
        # Validate appointment time format and shift availability
        AppointmentService.validate_appointment_availability(
            doctor, 
            appointment_data.appointment_date, 
            appointment_data.appointment_time
        )
        
        # Check hourly capacity (max 4 per hour)
        AppointmentService.check_hourly_capacity(
            db,
            appointment_data.doctor_id,
            appointment_data.appointment_date,
            appointment_data.appointment_time
        )
        
        # Check for exact time slot conflict
        existing_appointment = db.query(Appointment).filter(
            Appointment.doctor_id == appointment_data.doctor_id,
            Appointment.appointment_date == appointment_data.appointment_date,
            Appointment.appointment_time == appointment_data.appointment_time,
            Appointment.status == AppointmentStatus.SCHEDULED
        ).first()
        
        if existing_appointment:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This exact time slot is already booked"
            )
        
        db_appointment = Appointment(**appointment_data.model_dump())
        db.add(db_appointment)
        db.commit()
        db.refresh(db_appointment)
        return db_appointment
    
    @staticmethod
    def generate_time_slots(start_time_str: str, end_time_str: str, date_obj: datetime) -> list:
        """
        Generate 15-minute interval time slots between start and end time
        """
        start_time = datetime.strptime(start_time_str.strip(), "%H:%M")
        end_time = datetime.strptime(end_time_str.strip(), "%H:%M")
        
        slots = []
        current_time = start_time
        
        while current_time < end_time:
            slots.append(current_time.strftime("%H:%M"))
            current_time += timedelta(minutes=AppointmentService.APPOINTMENT_INTERVAL_MINUTES)
        
        return slots
    
    @staticmethod
    def get_available_slots(db: Session, doctor_id: str, appointment_date: str):
        """
        Get all available 15-minute time slots for a doctor on a specific date.
        Each hour can have maximum 4 appointments.
        """
        doctor = DoctorService.get_doctor_by_id(db, doctor_id)
        
        # Check if date is available
        if appointment_date not in doctor.availability_dates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Doctor is not available on {appointment_date}"
            )
        
        # Get day of week
        date_obj = datetime.strptime(appointment_date, "%Y-%m-%d")
        day_name = date_obj.strftime("%A").lower()
        
        if day_name not in doctor.shift_timings:
            return {"available_slots": [], "message": f"No shift scheduled for {day_name.capitalize()}"}
        
        # Get all scheduled appointments for this doctor on this date
        scheduled_appointments = db.query(Appointment).filter(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == appointment_date,
            Appointment.status == AppointmentStatus.SCHEDULED
        ).all()
        
        # Create a dictionary to track booked times and hourly counts
        booked_times = set(apt.appointment_time for apt in scheduled_appointments)
        hourly_counts = defaultdict(int)
        
        for apt in scheduled_appointments:
            hour = AppointmentService.get_hour_from_time(apt.appointment_time)
            hourly_counts[hour] += 1
        
        # Generate all possible 15-minute slots
        all_slots = []
        shift_slots = doctor.shift_timings[day_name]
        
        for shift_slot in shift_slots:
            start_time_str, end_time_str = shift_slot.split("-")
            slots = AppointmentService.generate_time_slots(start_time_str, end_time_str, date_obj)
            all_slots.extend(slots)
        
        # Filter available slots based on:
        # 1. Not already booked
        # 2. Hour hasn't reached capacity (4 appointments)
        available_slots = []
        for slot in all_slots:
            hour = AppointmentService.get_hour_from_time(slot)
            
            # Check if slot is not booked and hour hasn't reached capacity
            if slot not in booked_times and hourly_counts[hour] < AppointmentService.MAX_APPOINTMENTS_PER_HOUR:
                available_slots.append(slot)
        
        # Calculate statistics
        total_slots = len(all_slots)
        booked_slots = len(booked_times)
        
        return {
            "doctor_id": doctor_id,
            "date": appointment_date,
            "day": day_name.capitalize(),
            "total_slots": total_slots,
            "booked_slots": booked_slots,
            "available_slots": available_slots,
            "slots_by_hour": dict(hourly_counts)
        }
    
    @staticmethod
    def get_appointment_by_id(db: Session, appointment_id: int):
        appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        if not appointment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Appointment with ID {appointment_id} not found"
            )
        return appointment
    
    @staticmethod
    def get_all_appointments(db: Session, skip: int = 0, limit: int = 100):
        return db.query(Appointment).offset(skip).limit(limit).all()
    
    @staticmethod
    def get_appointments_by_doctor(db: Session, doctor_id: str):
        return db.query(Appointment).filter(Appointment.doctor_id == doctor_id).all()
    
    @staticmethod
    def get_appointments_by_date(db: Session, appointment_date: str):
        return db.query(Appointment).filter(Appointment.appointment_date == appointment_date).all()
    
    @staticmethod
    def get_doctor_statistics(db: Session, doctor_id: str, appointment_date: str):
        """
        Get statistics about appointments for a doctor on a specific date
        """
        doctor = DoctorService.get_doctor_by_id(db, doctor_id)
        
        scheduled_appointments = db.query(Appointment).filter(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == appointment_date,
            Appointment.status == AppointmentStatus.SCHEDULED
        ).all()
        
        # Calculate hourly distribution
        hourly_distribution = defaultdict(list)
        for apt in scheduled_appointments:
            hour = AppointmentService.get_hour_from_time(apt.appointment_time)
            hourly_distribution[hour].append({
                "time": apt.appointment_time,
                "patient": apt.patient_name
            })
        
        # Calculate total capacity
        date_obj = datetime.strptime(appointment_date, "%Y-%m-%d")
        day_name = date_obj.strftime("%A").lower()
        
        total_hours = 0
        if day_name in doctor.shift_timings:
            for shift in doctor.shift_timings[day_name]:
                start, end = shift.split("-")
                start_hour = int(start.split(":")[0])
                end_hour = int(end.split(":")[0])
                total_hours += (end_hour - start_hour)
        
        total_capacity = total_hours * AppointmentService.MAX_APPOINTMENTS_PER_HOUR
        
        return {
            "doctor_id": doctor_id,
            "doctor_name": doctor.name,
            "date": appointment_date,
            "total_appointments": len(scheduled_appointments),
            "total_capacity": total_capacity,
            "capacity_utilization": f"{(len(scheduled_appointments) / total_capacity * 100):.1f}%" if total_capacity > 0 else "0%",
            "appointments_by_hour": dict(hourly_distribution),
            "max_per_hour": AppointmentService.MAX_APPOINTMENTS_PER_HOUR
        }
    
    @staticmethod
    def update_appointment(db: Session, appointment_id: int, appointment_data: AppointmentUpdate):
        appointment = AppointmentService.get_appointment_by_id(db, appointment_id)
        
        # If updating date or time, validate availability and capacity
        if appointment_data.appointment_date or appointment_data.appointment_time:
            doctor = DoctorService.get_doctor_by_id(db, appointment.doctor_id)
            new_date = appointment_data.appointment_date or appointment.appointment_date
            new_time = appointment_data.appointment_time or appointment.appointment_time
            
            AppointmentService.validate_appointment_availability(doctor, new_date, new_time)
            AppointmentService.check_hourly_capacity(db, appointment.doctor_id, new_date, new_time)
        
        update_data = appointment_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(appointment, key, value)
        
        db.commit()
        db.refresh(appointment)
        return appointment
    
    @staticmethod
    def cancel_appointment(db: Session, appointment_id: int):
        appointment = AppointmentService.get_appointment_by_id(db, appointment_id)
        appointment.status = AppointmentStatus.CANCELLED
        db.commit()
        db.refresh(appointment)
        return appointment
    
    @staticmethod
    def delete_appointment(db: Session, appointment_id: int):
        appointment = AppointmentService.get_appointment_by_id(db, appointment_id)
        db.delete(appointment)
        db.commit()
        return {"message": f"Appointment {appointment_id} deleted successfully"}
