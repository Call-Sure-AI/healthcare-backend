from typing import List, Optional

# Comprehensive symptom-to-specialization mapping
SYMPTOM_SPECIALIZATION_MAP = {
    "Cardiology": [
        "cardio", "cardiologist", "heart", "cardiac", "chest pain", 
        "blood pressure", "hypertension", "palpitations", 
        "irregular heartbeat", "cholesterol", "heart attack", 
        "angina", "breathlessness"
    ],
    "Orthopedics": [
        "ortho", "orthopedic", "orthopedist", "bone", "joint", 
        "fracture", "sprain", "back pain", "knee pain", "arthritis", 
        "shoulder pain", "neck pain"
    ],
    "Pediatrics": [
        "pediatric", "pediatrician", "child", "baby", "infant", 
        "kid", "vaccination", "children"
    ],
    "Dermatology": [
        "derma", "dermatologist", "dermatology", "skin", "rash", 
        "acne", "allergy", "eczema", "psoriasis", "hair loss"
    ],
    "Neurology": [
        "neuro", "neurologist", "neurology", "headache", "migraine", 
        "seizure", "epilepsy", "stroke", "paralysis", "numbness", 
        "tingling", "memory loss", "dizziness", "vertigo", "brain"
    ],
    "Gynecology": [
        "gynec", "gynecologist", "gynecology", "pregnancy", "pregnant", 
        "menstruation", "period", "pcos", "women's health"
    ],
    "Psychiatry": [
        "psych", "psychiatrist", "psychiatry", "depression", "anxiety", 
        "stress", "mental health", "insomnia", "panic attack"
    ],
    "General Medicine": [
        "general", "physician", "doctor", "fever", "cold", "cough", 
        "flu", "diabetes", "checkup", "fatigue"
    ],
    "Alternative Medicine": [
        "ayurveda", "homeopathy", "alternative", "natural treatment", 
        "herbal", "holistic", "BAMS", "ayurvedic"
    ]
}


def extract_specialization_from_text(text: str) -> Optional[str]:
    """
    Analyze user text (symptoms/reason) and return the matching specialization.
    Returns None if no clear match is found.
    """
    if not text:
        print(f"⚠️  Empty text provided")
        return None
        
    text_lower = text.lower()
    print(f"🔍 Analyzing text: '{text_lower}'")
    
    # Track matches with scores
    specialization_scores = {}
    
    for specialization, keywords in SYMPTOM_SPECIALIZATION_MAP.items():
        score = 0
        matched_keywords = []
        
        for keyword in keywords:
            if keyword in text_lower:
                # Longer keywords get higher scores (more specific)
                keyword_score = len(keyword.split())
                score += keyword_score
                matched_keywords.append(keyword)
        
        if score > 0:
            specialization_scores[specialization] = score
            print(f"   ✓ Matched '{specialization}' (score: {score}, keywords: {matched_keywords})")
    
    # Return specialization with highest score
    if specialization_scores:
        best_match = max(specialization_scores, key=specialization_scores.get)
        print(f"🎯 Detected specialization: {best_match} (from '{text}')")
        return best_match
    
    print(f"❌ No specialization detected in: '{text}'")
    return None


def filter_doctors_by_specialization(
    doctors: List[dict],
    specialization: Optional[str]
) -> List[dict]:
    """
    Filter doctors list by specialization.
    If no specialization provided or no matches, return top 5 doctors.
    """
    if not doctors:
        print(f"⚠️  No doctors provided to filter")
        return []
    
    if not specialization:
        # Return max 5 doctors if no specialization specified
        print(f"ℹ️  No specialization specified, returning first 5 doctors")
        return doctors[:5]
    
    print(f"🔍 Filtering {len(doctors)} doctors for specialization: '{specialization}'")
    
    # Filter doctors matching the specialization (case-insensitive)
    filtered = [
        doc for doc in doctors 
        if doc.get("specialization", "").lower() == specialization.lower()
    ]
    
    if filtered:
        print(f"✅ Found {len(filtered)} doctor(s) for '{specialization}':")
        for doc in filtered:
            print(f"   - {doc['name']} (ID: {doc['doctor_id']})")
        return filtered
    else:
        print(f"⚠️  No '{specialization}' specialists found in database")
        print(f"   Returning first 5 general doctors as fallback")
        return doctors[:5]
