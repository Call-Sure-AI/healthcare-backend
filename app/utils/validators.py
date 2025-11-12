# app/utils/validators.py - ULTRA FAST VERSION (< 0.1ms overhead)

import re
from typing import Tuple

# ⚡ Pre-compile regex patterns for maximum speed
PHONE_PATTERN = re.compile(r'^\+(\d{1,3})(\d+)$')
CLEANUP_PATTERN = re.compile(r'[\s\-\(\)\.]')

# ⚡ Country code validation rules (dict lookup is O(1))
COUNTRY_RULES = {
    '91': (10, '6789'),     # India: 10 digits, starts with 6-9
    '1': (10, None),        # US/Canada: 10 digits
    '44': (10, None),       # UK: 10 digits
    '61': (9, None),        # Australia: 9 digits
    '86': (11, None),       # China: 11 digits
    '81': (10, None),       # Japan: 10 digits
}


def validate_phone_with_feedback(phone: str) -> Tuple[bool, str, str]:
    """
    ⚡ ULTRA FAST: <0.1ms phone validation with detailed feedback
    Returns: (is_valid, formatted_phone, error_message)
    """
    # ⚡ Fast cleanup using pre-compiled regex
    cleaned = CLEANUP_PATTERN.sub('', phone)
    
    # ⚡ Quick check: must start with +
    if not cleaned.startswith('+'):
        return False, phone, "Phone must include country code starting with +. Example: +91-7530000402"
    
    # ⚡ Fast pattern match
    match = PHONE_PATTERN.match(cleaned)
    if not match:
        return False, phone, "Invalid format. Use: +[country code][number]"
    
    country_code = match.group(1)
    number = match.group(2)
    num_len = len(number)
    
    # ⚡ O(1) lookup for known countries
    if country_code in COUNTRY_RULES:
        expected_len, valid_starts = COUNTRY_RULES[country_code]
        
        # Check length
        if num_len != expected_len:
            country_names = {
                '91': 'Indian', '1': 'US/Canada', '44': 'UK',
                '61': 'Australian', '86': 'Chinese', '81': 'Japanese'
            }
            country = country_names.get(country_code, f"+{country_code}")
            return False, phone, f"{country} numbers need {expected_len} digits. You provided {num_len}."
        
        # Check starting digit (India only)
        if valid_starts and number[0] not in valid_starts:
            return False, phone, f"Indian mobile numbers must start with 6, 7, 8, or 9."
        
        # ⚡ Format for display
        if country_code == '91':
            formatted = f"+91-{number[:5]}-{number[5:]}"
        elif country_code == '1':
            formatted = f"+1-{number[:3]}-{number[3:6]}-{number[6:]}"
        else:
            formatted = f"+{country_code}-{number}"
        
        return True, formatted, ""
    
    # ⚡ Generic validation for other countries (7-15 digits)
    if 7 <= num_len <= 15:
        return True, f"+{country_code}-{number}", ""
    
    if num_len < 7:
        return False, phone, "Phone number too short. Need at least 7 digits after country code."
    else:
        return False, phone, "Phone number too long. Maximum 15 digits."


def validate_phone_number(phone: str) -> Tuple[bool, str]:
    """
    ⚡ FAST: Simple validation without detailed feedback
    Use this for quick checks. Use validate_phone_with_feedback for user-facing errors.
    Returns: (is_valid, formatted_number)
    """
    is_valid, formatted, _ = validate_phone_with_feedback(phone)
    return is_valid, formatted


# Keep all other functions unchanged...
def validate_date_format(date_str: str) -> bool:
    """Validate date string format (YYYY-MM-DD)"""
    pattern = r'^\d{4}-\d{2}-\d{2}$'
    return bool(re.match(pattern, date_str))


def validate_time_format(time_str: str) -> bool:
    """Validate time string format (HH:MM)"""
    pattern = r'^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$'
    return bool(re.match(pattern, time_str))


def sanitize_text(text: str, max_length: int = 500) -> str:
    """Sanitize user input text"""
    cleaned = re.sub(r'[^\w\s\.,!?\-]', '', text)
    return cleaned[:max_length].strip()


def extract_digits(text: str) -> str:
    """Extract only digits from text"""
    return re.sub(r'\D', '', text)


def parse_patient_name(name: str) -> str:
    """Parse and validate patient name"""
    cleaned = ' '.join(name.split())
    if 2 <= len(cleaned) <= 50 and re.match(r'^[a-zA-Z\s]+$', cleaned):
        return cleaned.title()
    return None