import os
import sys
import json
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from qdrant_client import QdrantClient, models
import traceback
import openai

# --- Load Environment Variables ---
load_dotenv()

# --- Configuration ---
DATABASE_URL = os.getenv("DATABASE_URL")
QDRANT_HOST = os.getenv("QDRANT_HOST")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME")
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# --- Setup Project Path (Adapt if your structure differs) ---
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# --- Imports from your application ---
try:
    from app.models.doctor import Doctor, DoctorStatus
except ImportError as e:
    print(f"Error importing application modules: {e}")
    sys.exit(1)

# --- Database Setup ---
if not DATABASE_URL:
    print("Error: DATABASE_URL not set in environment variables.")
    sys.exit(1)

try:
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    print("✓ Database engine created.")
except Exception as e:
    print(f"Error creating database engine: {e}")
    sys.exit(1)

# --- Embedding Model: OpenAI ---
if not OPENAI_API_KEY:
    print("Error: OPENAI_API_KEY not set in environment variables.")
    sys.exit(1)
openai.api_key = OPENAI_API_KEY
VECTOR_SIZE = 1536  # For text-embedding-3-small
print(f"✓ OpenAI Embedding model ready (Vector Size: {VECTOR_SIZE}).")

def get_openai_embeddings(text_list, model=EMBEDDING_MODEL_NAME):
    """
    Calls OpenAI embedding API (batches if necessary) and returns a list of embeddings.
    """
    if not text_list:
        return []
    try:
        # OpenAI max batch size is 2048
        embeddings = []
        BATCH_SIZE = 1000
        for i in range(0, len(text_list), BATCH_SIZE):
            batch = text_list[i:i+BATCH_SIZE]
            response = openai.embeddings.create(input=batch, model=model)
            batch_embeddings = [item.embedding for item in response.data]
            embeddings.extend(batch_embeddings)
        return embeddings
    except Exception as e:
        print(f"Error fetching embeddings from OpenAI: {e}")
        traceback.print_exc()
        return []

# --- Qdrant Client ---
try:
    print(f"Connecting to Qdrant at {QDRANT_HOST}:{QDRANT_PORT}...")
    qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, api_key=os.getenv("QDRANT_API_KEY"), https=False)
    qdrant_client.get_collections()
    print("✓ Connected to Qdrant.")
except Exception as e:
    print(f"Error connecting to Qdrant: {e}")
    sys.exit(1)


def prepare_doctor_data(db_session: Session):
    """
    Fetches doctors from DB and prepares text chunks and metadata.
    """
    print("Fetching doctors from PostgreSQL...")
    try:
        doctors = db_session.query(Doctor).filter(Doctor.status != DoctorStatus.DELETED).all()
        print(f"Found {len(doctors)} non-deleted doctors.")
    except Exception as e:
        print(f"Error querying doctors from database: {e}")
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
                f"Current status is {status_str}. "
            )
            text_chunks.append(description.strip())
            metadata_list.append({
                "postgres_id": doctor.id,  # Original DB ID
                "doctor_id": doctor.doctor_id,
                "name": doctor.name,
                "specialization": specialization_str,
                "status": status_str,
                "degree": doctor.degree,
                "raw_text": description.strip()
            })
        except Exception as e:
            print(f"Error processing doctor ID {getattr(doctor, 'id', '?')} ({getattr(doctor, 'name', '?')}): {e}")
            continue
    return text_chunks, metadata_list


def ingest_to_qdrant(text_chunks, metadata_list, embeddings):
    """
    Recreates collection and upserts data into Qdrant.
    """
    print(f"\nRecreating Qdrant collection '{QDRANT_COLLECTION_NAME}'...")
    try:
        qdrant_client.recreate_collection(
            collection_name=QDRANT_COLLECTION_NAME,
            vectors_config=models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE),
        )
        print("✓ Collection recreated (cleared previous entries).")
    except Exception as e:
        print(f"Error recreating Qdrant collection: {e}")
        return

    print("Preparing points for Qdrant...")
    points_to_upsert = []
    for i, (embedding, metadata) in enumerate(zip(embeddings, metadata_list)):
        qdrant_id = metadata['postgres_id']
        points_to_upsert.append(
            models.PointStruct(
                id=qdrant_id,
                vector=embedding,
                payload=metadata
            )
        )
    if not points_to_upsert:
        print("No points generated to upsert.")
        return

    print(f"Upserting {len(points_to_upsert)} points into Qdrant...")
    try:
        qdrant_client.upsert(
            collection_name=QDRANT_COLLECTION_NAME,
            points=points_to_upsert,
            wait=True
        )
        print("✓ Upsert complete.")
    except Exception as e:
        print(f"Error upserting points into Qdrant: {e}")
        traceback.print_exc()

# --- Main Execution ---
if __name__ == "__main__":
    db = None
    try:
        db = SessionLocal()
        chunks, metadata = prepare_doctor_data(db)
        if chunks and metadata and len(chunks) == len(metadata):
            print(f"\nGenerating {len(chunks)} embeddings with OpenAI...")
            embeddings = get_openai_embeddings(chunks)
            if embeddings and len(embeddings) == len(chunks):
                ingest_to_qdrant(chunks, metadata, embeddings)
            else:
                print("Failed to generate correct number of embeddings. Aborting.")
        elif not chunks:
            print("No doctor data found or prepared.")
        else:
            print("Mismatch between text chunks and metadata count. Aborting ingest.")
    except Exception as e:
        print(f"\nAn error occurred during the main process: {e}")
        traceback.print_exc()
    finally:
        if db:
            db.close()
            print("\nDatabase session closed.")
        print("Process finished.")
