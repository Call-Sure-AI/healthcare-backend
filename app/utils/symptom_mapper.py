from typing import List, Optional

# Comprehensive symptom-to-specialization mapping
SYMPTOM_SPECIALIZATION_MAP = {
    "Cardiology": [
        "chest pain", "heart", "cardiac", "blood pressure", "hypertension",
        "palpitations", "irregular heartbeat", "cholesterol", "heart attack",
        "angina", "breathlessness", "shortness of breath"
    ],
    "Orthopedics": [
        "bone", "joint", "fracture", "sprain", "back pain", "knee pain",
        "arthritis", "shoulder pain", "neck pain", "hip pain", "leg pain",
        "muscle pain", "sports injury", "ligament", "cartilage"
    ],
    "Pediatrics": [
        "child", "baby", "infant", "kid", "vaccination", "fever in child",
        "newborn", "growth", "development", "pediatric", "children"
    ],
    "Dermatology": [
        "skin", "rash", "acne", "allergy", "eczema", "psoriasis", "moles",
        "hair loss", "dandruff", "itching", "hives", "pigmentation"
    ],
    "Neurology": [
        "headache", "migraine", "seizure", "epilepsy", "stroke", "paralysis",
        "numbness", "tingling", "memory loss", "dizziness", "vertigo",
        "parkinson", "alzheimer", "tremor"
    ],
    "Gynecology": [
        "pregnancy", "pregnant", "menstruation", "period", "pcos", "pcod",
        "gynec", "women's health", "uterus", "ovarian", "menopause",
        "contraception", "fertility"
    ],
    "Psychiatry": [
        "depression", "anxiety", "stress", "mental health", "insomnia",
        "panic attack", "mood", "bipolar", "schizophrenia", "ocd", "ptsd"
    ],
    "General Medicine": [
        "fever", "cold", "cough", "flu", "diabetes", "thyroid", "general checkup",
        "health checkup", "fatigue", "weakness", "weight loss", "weight gain"
    ],
    "Alternative Medicine": [
        "ayurveda", "homeopathy", "alternative", "natural treatment",
        "herbal", "holistic", "traditional medicine"
    ]
}


def extract_specialization_from_text(text: str) -> Optional[str]:
    """
    Analyze user text (symptoms/reason) and return the matching specialization.
    Returns None if no clear match is found.
    """
    text_lower = text.lower()
    
    # Track matches with scores
    specialization_scores = {}
    
    for specialization, keywords in SYMPTOM_SPECIALIZATION_MAP.items():
        score = 0
        for keyword in keywords:
            if keyword in text_lower:
                # Longer keywords get higher scores (more specific)
                score += len(keyword.split())
        
        if score > 0:
            specialization_scores[specialization] = score
    
    # Return specialization with highest score
    if specialization_scores:
        best_match = max(specialization_scores, key=specialization_scores.get)
        print(f"🎯 Detected specialization: {best_match} (from '{text}')")
        return best_match
    
    return None


def filter_doctors_by_specialization(
    doctors: List[dict],
    specialization: Optional[str]
) -> List[dict]:
    """
    Filter doctors list by specialization.
    If no specialization provided or no matches, return top 5 doctors.
    """
    if not specialization or not doctors:
        # Return max 5 doctors if no specialization match
        return doctors[:5]
    
    # Filter doctors matching the specialization
    filtered = [
        doc for doc in doctors 
        if doc.get("specialization", "").lower() == specialization.lower()
    ]
    
    if filtered:
        print(f"Found {len(filtered)} doctors for {specialization}")
        return filtered
    else:
        print(f"No {specialization} specialists found, returning top 5 general doctors")
        return doctors[:5]
