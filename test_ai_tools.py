from app.config.database import SessionLocal
from app.routes.ai_tools import AIToolsExecutor

db = SessionLocal()
executor = AIToolsExecutor(db)

print('🧪 Testing book_appointment function...\n')

# Test data
test_booking = {
    'patient_name': 'Test Patient',
    'patient_phone': '9876543210',
    'doctor_id': 'DOC0011',
    'appointment_date': '2025-10-20',
    'appointment_time': '10:00',
    'reason': 'Fever and cough - Test booking'
}

print('📋 Booking Details:')
for key, value in test_booking.items():
    print(f'   {key}: {value}')

print('\n🔧 Calling book_appointment...\n')

result = executor.book_appointment(**test_booking)

print('📊 Result:')
import json
print(json.dumps(result, indent=2))

if result.get('success'):
    print('\n✅ SUCCESS! Appointment booked.')
    print(f'   Confirmation: {result.get("confirmation_number")}')
    print(f'   Appointment ID: {result.get("appointment_id")}')
else:
    print('\n❌ FAILED!')
    print(f'   Error: {result.get("error")}')

db.close()