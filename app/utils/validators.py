import re
from typing import Optional


def validate_phone_number(phone: str) -> tuple[bool, str]:
    """
    Validate Indian phone number
    Returns: (is_valid, formatted_number)
    """
    # Remove spaces, dashes, and parentheses
    cleaned = re.sub(r'[\s\-\(\)]', '', phone)
    
    # Remove +91 country code if present
    if cleaned.startswith('+91'):
        cleaned = cleaned[3:]
    elif cleaned.startswith('91') and len(cleaned) == 12:
        cleaned = cleaned[2:]
    
    # Indian mobile number: 10 digits starting with 6-9
    pattern = r'^[6-9]\d{9}$'
    
    if re.match(pattern, cleaned):
        # Format as +91-XXXXX-XXXXX
        formatted = f"+91-{cleaned[:5]}-{cleaned[5:]}"
        return True, formatted
    
    return False, phone


def validate_date_format(date_str: str) -> bool:
    """
    Validate date string format (YYYY-MM-DD)
    """
    pattern = r'^\d{4}-\d{2}-\d{2}$'
    return bool(re.match(pattern, date_str))


def validate_time_format(time_str: str) -> bool:
    """
    Validate time string format (HH:MM)
    """
    pattern = r'^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$'
    return bool(re.match(pattern, time_str))


def sanitize_text(text: str, max_length: int = 500) -> str:
    """
    Sanitize user input text
    """
    # Remove special characters except basic punctuation
    cleaned = re.sub(r'[^\w\s\.,!?\-]', '', text)
    # Limit length
    return cleaned[:max_length].strip()


def extract_digits(text: str) -> str:
    """
    Extract only digits from text
    """
    return re.sub(r'\D', '', text)


def parse_patient_name(name: str) -> Optional[str]:
    """
    Parse and validate patient name
    """
    # Remove extra spaces
    cleaned = ' '.join(name.split())
    
    # Name should be 2-50 characters, only letters and spaces
    if 2 <= len(cleaned) <= 50 and re.match(r'^[a-zA-Z\s]+$', cleaned):
        return cleaned.title()
    
    return None
