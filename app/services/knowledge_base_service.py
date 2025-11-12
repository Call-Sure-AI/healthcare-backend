from typing import List, Dict, Optional, Tuple
from qdrant_client import QdrantClient
from app.config.voice_config import voice_config
import openai
import logging

logger = logging.getLogger("knowledge_base")

class KnowledgeBaseService:
    """
    Service for querying knowledge base stored in Qdrant.
    Uses OpenAI embeddings to match user queries with relevant clinic information.
    """
    
    def __init__(self):
        """Initialize Qdrant client and OpenAI for embeddings"""
        self.qdrant_client = QdrantClient(
            host=voice_config.QDRANT_HOST,
            port=voice_config.QDRANT_PORT,
            api_key=voice_config.QDRANT_API_KEY,
            https=False
        )
        openai.api_key = voice_config.OPENAI_API_KEY
        self.kb_collection = "healthcare_knowledge_base"
        self.doctors_collection = voice_config.QDRANT_COLLECTION_NAME
        self.embedding_model = voice_config.EMBEDDING_MODEL_NAME
        logger.info(f"Knowledge Base Service initialized")
    
    def _get_embedding(self, text: str) -> List[float]:
        """Generate embedding for query using OpenAI"""
        try:
            response = openai.embeddings.create(
                input=text,
                model=self.embedding_model
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return None
    
    def search_knowledge(
        self,
        query: str,
        limit: int = 3,
        score_threshold: float = 0.5
    ) -> List[Dict]:
        """
        Search knowledge base for relevant information
        
        Args:
            query: User's question or query text
            limit: Maximum number of results to return
            score_threshold: Minimum similarity score (0-1)
        
        Returns:
            List of matching knowledge base entries with content and metadata
        """
        try:
            # Generate query embedding
            query_vector = self._get_embedding(query)
            if not query_vector:
                return []
            
            # Search Qdrant
            search_results = self.qdrant_client.search(
                collection_name=self.kb_collection,
                query_vector=query_vector,
                limit=limit,
                score_threshold=score_threshold
            )
            
            # Format results
            results = []
            for hit in search_results:
                results.append({
                    "content": hit.payload.get("content", ""),
                    "category": hit.payload.get("category", ""),
                    "subcategory": hit.payload.get("subcategory", ""),
                    "score": hit.score,
                    "relevance": "high" if hit.score > 0.8 else "medium" if hit.score > 0.6 else "low"
                })
            
            logger.info(f"KB Search: '{query[:50]}...' → {len(results)} results")
            return results
            
        except Exception as e:
            logger.error(f"Knowledge base search error: {e}")
            return []
    
    def classify_query_intent(self, query: str) -> str:
        """
        Determine if query needs knowledge base, doctor search, or hybrid approach
        
        Returns:
            'knowledge_base', 'doctor_search', or 'hybrid'
        """
        query_lower = query.lower()
        
        # Knowledge base keywords (policy/info questions)
        kb_keywords = [
            "how to", "what is", "can i", "policy", "cancel", "reschedule",
            "information", "details about", "explain", "hours", "contact",
            "emergency", "duration", "insurance", "payment", "how does",
            "what are", "where", "when", "why", "parking", "location",
            "bring", "prepare", "first time", "walk-in", "telemedicine",
            "prescription", "refill", "lab test", "follow-up", "chronic"
        ]
        
        # Doctor search keywords (appointment booking)
        doctor_keywords = [
            "book", "appointment", "doctor", "available", "schedule",
            "specialist", "cardiologist", "neurologist", "urgent",
            "today", "tomorrow", "next week", "symptoms", "pain",
            "fever", "headache", "need to see"
        ]
        
        kb_score = sum(1 for kw in kb_keywords if kw in query_lower)
        doctor_score = sum(1 for kw in doctor_keywords if kw in query_lower)
        
        if kb_score > doctor_score:
            return "knowledge_base"
        elif doctor_score > kb_score:
            return "doctor_search"
        else:
            return "hybrid"
    
    def get_context_for_query(
        self,
        query: str,
        max_length: int = 500
    ) -> Tuple[str, str]:
        """
        Get knowledge base context for a query
        
        Returns:
            Tuple of (context_text, intent_type)
        """
        intent = self.classify_query_intent(query)
        
        if intent == "doctor_search":
            # Don't query KB for pure doctor searches
            return "", "doctor_search"
        
        # Search knowledge base
        results = self.search_knowledge(query, limit=2 if intent == "hybrid" else 3)
        
        if not results:
            return "", intent
        
        # Combine results into context
        context_parts = []
        for result in results:
            if result["score"] > 0.6:  # Only include relevant results
                content = result["content"].strip()
                if len(" ".join(context_parts)) + len(content) < max_length:
                    context_parts.append(content)
        
        context = "\n\n".join(context_parts)
        logger.info(f"Context generated: {len(context)} chars, intent={intent}")
        
        return context, intent
    
    def answer_direct_question(self, query: str) -> Optional[str]:
        """
        Answer simple factual questions directly from knowledge base
        Used for quick info queries that don't need LLM processing
        
        Returns:
            Direct answer if available, None if needs LLM processing
        """
        query_lower = query.lower()
        
        # Direct answers for common questions
        direct_answers = {
            "hours": f"We're open 6 AM to 11 PM daily, every day including weekends.",
            "location": f"We're located at {voice_config.CLINIC_ADDRESS}.",
            "address": f"Our address is {voice_config.CLINIC_ADDRESS}.",
            "phone": f"You can reach us at {voice_config.CLINIC_PHONE}.",
            "parking": "We offer free parking on-site with wheelchair accessible spaces.",
            "emergency": "For emergencies like chest pain, difficulty breathing, or severe bleeding, please call 911 immediately.",
        }
        
        for keyword, answer in direct_answers.items():
            if keyword in query_lower and len(query_lower.split()) < 8:
                logger.info(f"Direct answer: {keyword}")
                return answer
        
        return None
    
    def check_collection_exists(self) -> bool:
        """Check if knowledge base collection exists in Qdrant"""
        try:
            collections = self.qdrant_client.get_collections()
            collection_names = [c.name for c in collections.collections]
            exists = self.kb_collection in collection_names
            
            if exists:
                collection_info = self.qdrant_client.get_collection(self.kb_collection)
                count = collection_info.points_count
                logger.info(f"Knowledge base collection exists: {count} entries")
            else:
                logger.warning(f"Knowledge base collection '{self.kb_collection}' not found")
            
            return exists
            
        except Exception as e:
            logger.error(f"Error checking KB collection: {e}")
            return False

# Global instance
knowledge_base_service = KnowledgeBaseService()
