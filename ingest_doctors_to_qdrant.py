import os
import sys
import json
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer
import traceback

# --- Load Environment Variables ---
load_dotenv()

# --- Configuration ---
DATABASE_URL = os.getenv("DATABASE_URL")
QDRANT_HOST = os.getenv("QDRANT_HOST")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME")
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME")

# --- Setup Project Path (Adapt if your structure differs) ---
# This assumes the script is run from the project root directory
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# --- Imports from your application ---
# Adjust these imports based on your actual project structure
try:
    from app.models.doctor import Doctor, DoctorStatus # Import your SQLAlchemy model and Enum
    # If DoctorService is simple enough to replicate fetching, you might query directly.
    # Otherwise, ensure DoctorService can be instantiated outside FastAPI context.
    # Using direct query here for simplicity, assuming direct model access.
except ImportError as e:
    print(f"Error importing application modules: {e}")
    print("Please ensure this script is run from the project root or adjust sys.path.")
    print("Make sure your models (app/models/doctor.py) exist.")
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

# --- Embedding Model ---
try:
    print(f"Loading embedding model: {EMBEDDING_MODEL_NAME}...")
    embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    VECTOR_SIZE = embedding_model.get_sentence_embedding_dimension()
    print(f"✓ Embedding model loaded (Vector Size: {VECTOR_SIZE}).")
except Exception as e:
    print(f"Error loading embedding model '{EMBEDDING_MODEL_NAME}': {e}")
    sys.exit(1)

# --- Qdrant Client ---
try:
    print(f"Connecting to Qdrant at {QDRANT_HOST}:{QDRANT_PORT}...")
    qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, api_key=os.getenv("QDRANT_API_KEY"), https=False)
    # Optional: Verify connection (e.g., try listing collections)
    qdrant_client.get_collections()
    print("✓ Connected to Qdrant.")
except Exception as e:
    print(f"Error connecting to Qdrant: {e}")
    sys.exit(1)


def prepare_doctor_data(db_session: Session):
    """Fetches doctors from DB and prepares text chunks and metadata."""
    print("Fetching doctors from PostgreSQL...")
    try:
        # Fetch only doctors who are not DELETED
        doctors = db_session.query(Doctor).filter(Doctor.status != DoctorStatus.DELETED).all()
        print(f"Found {len(doctors)} non-deleted doctors.")
    except Exception as e:
        print(f"Error querying doctors from database: {e}")
        return [], []

    text_chunks = []
    metadata_list = []

    for doctor in doctors:
        try:
            # Create descriptive text (using .value for Enum)
            status_str = doctor.status.value if doctor.status else 'Unknown'
            specialization_str = doctor.specialization or "General Medicine"

            description = (
                f"Doctor {doctor.name} (ID: {doctor.doctor_id}) "
                f"specializes in {specialization_str}. "
                f"Qualifications: {doctor.degree}. "
                f"Current status is {status_str}. "
                # Optional: Add concise info about shifts if needed, avoid excessive length
                # shift_days = list(doctor.shift_timings.keys()) if doctor.shift_timings else []
                # if shift_days:
                #    description += f"Works on {', '.join(shift_days)}. "
            )
            text_chunks.append(description.strip())
            metadata_list.append({
                "postgres_id": doctor.id,       # Original DB ID
                "doctor_id": doctor.doctor_id,  # Doctor's functional ID
                "name": doctor.name,
                "specialization": specialization_str,
                "status": status_str,
                "degree": doctor.degree,
                "raw_text": description.strip() # Store the generated text itself
            })
        except Exception as e:
            print(f"Error processing doctor ID {doctor.id} ({doctor.name}): {e}")
            continue # Skip this doctor if processing fails

    return text_chunks, metadata_list

def ingest_to_qdrant(text_chunks, metadata_list, embeddings):
    """Creates collection and upserts data into Qdrant."""
    print(f"\nCreating or recreating Qdrant collection '{QDRANT_COLLECTION_NAME}'...")
    try:
        qdrant_client.recreate_collection(
            collection_name=QDRANT_COLLECTION_NAME,
            vectors_config=models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE),
            # Optional: Add payload indexing for faster filtering later
            # payload_schema={
            #     "specialization": models.PayloadSchemaType.KEYWORD,
            #     "status": models.PayloadSchemaType.KEYWORD
            # }
        )
        print("✓ Collection created/recreated.")
    except Exception as e:
        print(f"Error creating/recreating Qdrant collection: {e}")
        return

    print("Preparing points for Qdrant...")
    points_to_upsert = []
    for i, (embedding, metadata) in enumerate(zip(embeddings, metadata_list)):
        # Use the stable PostgreSQL primary key as the Qdrant point ID
        qdrant_id = metadata['postgres_id']

        points_to_upsert.append(
            models.PointStruct(
                id=qdrant_id,
                vector=embedding.tolist(),
                payload=metadata # Store all collected metadata
            )
        )

    if not points_to_upsert:
        print("No points generated to upsert.")
        return

    print(f"Upserting {len(points_to_upsert)} points into Qdrant...")
    try:
        # Upsert in batches if you have a very large number of doctors
        qdrant_client.upsert(
            collection_name=QDRANT_COLLECTION_NAME,
            points=points_to_upsert,
            wait=True # Wait for operation to complete
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
            print(f"\nGenerating {len(chunks)} embeddings...")
            embeddings_np = embedding_model.encode(chunks, show_progress_bar=True)
            ingest_to_qdrant(chunks, metadata, embeddings_np)
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