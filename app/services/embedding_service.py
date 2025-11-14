import logging
from typing import List, Dict, Tuple
from sqlalchemy.orm import Session
from qdrant_client import QdrantClient, models
import openai
from app.config.database import SessionLocal
from app.config.voice_config import VoiceAgentConfig
from app.models.doctor import Doctor, DoctorStatus

logger = logging.getLogger(__name__)

openai.api_key = VoiceAgentConfig.OPENAI_API_KEY

class EmbeddingService:
    def __init__(self):
        """Initialize with Qdrant connection from voice_config"""
        self.qdrant_client = QdrantClient(
            host=VoiceAgentConfig.QDRANT_HOST,
            port=VoiceAgentConfig.QDRANT_PORT,
            api_key=VoiceAgentConfig.QDRANT_API_KEY,
            https=False
        )
        self.collection_name = VoiceAgentConfig.QDRANT_COLLECTION_NAME
        self.embedding_model = VoiceAgentConfig.EMBEDDING_MODEL_NAME

        self.vector_size = self._get_vector_size()
        
        logger.info(f"EmbeddingService initialized with collection: {self.collection_name}")
    
    def _get_vector_size(self) -> int:
        """Get vector dimension based on OpenAI model"""
        model_dimensions = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
        }
        return model_dimensions.get(self.embedding_model, 1536)
    
    def get_openai_embeddings(
        self, 
        text_list: List[str], 
        model: str = None
    ) -> List[List[float]]:
        """Generate embeddings using OpenAI API"""
        if not text_list:
            logger.warning("Empty text list provided")
            return []
        
        model = model or self.embedding_model
        embeddings = []
        BATCH_SIZE = 1000
        
        try:
            total_batches = (len(text_list) + BATCH_SIZE - 1) // BATCH_SIZE
            
            for i in range(0, len(text_list), BATCH_SIZE):
                batch = text_list[i:i+BATCH_SIZE]
                batch_num = i // BATCH_SIZE + 1
                logger.info(f"Processing batch {batch_num}/{total_batches} (size: {len(batch)})")
                
                response = openai.embeddings.create(input=batch, model=model)
                batch_embeddings = [item.embedding for item in response.data]
                embeddings.extend(batch_embeddings)
                
            logger.info(f"Generated {len(embeddings)} embeddings successfully")
            return embeddings
            
        except Exception as e:
            logger.error(f"Error generating embeddings: {e}")
            raise
    
    def prepare_doctor_data(self, db_session: Session) -> Tuple[List[str], List[Dict]]:
        """Fetch doctors from PostgreSQL and prepare text chunks and metadata"""
        logger.info("Fetching doctors from PostgreSQL...")
        
        try:
            doctors = db_session.query(Doctor).filter(
                Doctor.status != DoctorStatus.DELETED
            ).all()
            logger.info(f"Found {len(doctors)} non-deleted doctors")
            
        except Exception as e:
            logger.error(f"Error querying doctors: {e}")
            return [], []
        
        if not doctors:
            logger.warning("No doctors found in database")
            return [], []
        
        text_chunks = []
        metadata_list = []
        
        for doctor in doctors:
            try:
                status_str = doctor.status.value if doctor.status else 'Unknown'
                specialization_str = doctor.specialization or "General Medicine"

                description = (
                    f"Doctor {doctor.name} (ID: {doctor.doctor_id}) "
                    f"specializes in {specialization_str}. "
                    f"Qualifications: {doctor.degree}. "
                    f"Current status is {status_str}."
                )
                
                text_chunks.append(description.strip())
                metadata_list.append({
                    "postgres_id": doctor.id,
                    "doctor_id": doctor.doctor_id,
                    "name": doctor.name,
                    "specialization": specialization_str,
                    "status": status_str,
                    "degree": doctor.degree,
                    "raw_text": description.strip()
                })
                
            except Exception as e:
                logger.error(f"Error processing doctor {getattr(doctor, 'id', '?')}: {e}")
                continue
        
        logger.info(f"Prepared {len(text_chunks)} doctor records")
        return text_chunks, metadata_list
    
    def ingest_to_qdrant(
        self, 
        text_chunks: List[str], 
        metadata_list: List[Dict], 
        embeddings: List[List[float]]
    ):
        """Recreate collection and upsert data to Qdrant"""
        logger.info(f"🔄 Recreating Qdrant collection '{self.collection_name}'...")
        
        try:
            self.qdrant_client.recreate_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.vector_size, 
                    distance=models.Distance.COSINE
                )
            )
            logger.info("Collection recreated successfully")
            
        except Exception as e:
            logger.error(f"Error recreating collection: {e}")
            raise
        
        logger.info("Preparing points for Qdrant...")
        points_to_upsert = []
        
        for i, (embedding, metadata) in enumerate(zip(embeddings, metadata_list)):
            points_to_upsert.append(
                models.PointStruct(
                    id=metadata['postgres_id'],
                    vector=embedding,
                    payload=metadata
                )
            )
        
        if not points_to_upsert:
            logger.warning("No points to upsert")
            return
        
        logger.info(f"Upserting {len(points_to_upsert)} points to Qdrant...")
        
        try:
            self.qdrant_client.upsert(
                collection_name=self.collection_name,
                points=points_to_upsert,
                wait=True
            )
            logger.info(f"Successfully upserted {len(points_to_upsert)} points")
            
        except Exception as e:
            logger.error(f"Error upserting points: {e}")
            raise
    
    async def run_full_ingestion(self, db_session: Session) -> Dict:
        """Execute complete ingestion pipeline"""
        try:
            logger.info("Starting full embedding ingestion process...")

            chunks, metadata = self.prepare_doctor_data(db_session)
            
            if not chunks or not metadata:
                return {
                    "status": "warning",
                    "message": "No doctor data found in database",
                    "doctors_count": 0
                }
            
            if len(chunks) != len(metadata):
                raise ValueError(f"Chunk/metadata count mismatch: {len(chunks)} vs {len(metadata)}")
            
            logger.info(f"Generating embeddings for {len(chunks)} doctors...")
            embeddings = self.get_openai_embeddings(chunks)
            
            if not embeddings or len(embeddings) != len(chunks):
                raise ValueError(f"Embedding generation failed or count mismatch: {len(embeddings)} vs {len(chunks)}")

            self.ingest_to_qdrant(chunks, metadata, embeddings)
            
            logger.info(f"🎉 Successfully processed {len(chunks)} doctors")
            return {
                "status": "success",
                "message": f"Successfully ingested {len(chunks)} doctors to Qdrant",
                "doctors_count": len(chunks)
            }
            
        except Exception as e:
            logger.error(f"Error during ingestion: {e}")
            raise
        finally:
            db_session.close()

# Singleton instance
embedding_service = EmbeddingService()
