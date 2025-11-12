import os
import sys
from dotenv import load_dotenv
from qdrant_client import QdrantClient, models
import openai
import traceback

# Load environment variables
load_dotenv()

# Configuration
QDRANT_HOST = os.getenv("QDRANT_HOST")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
KB_COLLECTION_NAME = "healthcare_knowledge_base"

# Vector size for text-embedding-3-small
VECTOR_SIZE = 1536

# Setup paths
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# Import knowledge base content
try:
    from app.config.knowledge_base_content import KNOWLEDGE_BASE
except ImportError as e:
    print(f"Error importing knowledge base content: {e}")
    sys.exit(1)

# Setup OpenAI
if not OPENAI_API_KEY:
    print("Error: OPENAI_API_KEY not set in environment variables.")
    sys.exit(1)

openai.api_key = OPENAI_API_KEY
print(f"✓ OpenAI API key configured (Model: {EMBEDDING_MODEL_NAME})")

def get_openai_embeddings(text_list: list) -> list:
    """
    Generate embeddings for a list of texts using OpenAI API
    """
    if not text_list:
        return []
    
    try:
        embeddings = []
        BATCH_SIZE = 1000
        
        for i in range(0, len(text_list), BATCH_SIZE):
            batch = text_list[i:i+BATCH_SIZE]
            print(f"  Generating embeddings for batch {i//BATCH_SIZE + 1}...")
            
            response = openai.embeddings.create(
                input=batch,
                model=EMBEDDING_MODEL_NAME
            )
            
            batch_embeddings = [item.embedding for item in response.data]
            embeddings.extend(batch_embeddings)
        
        return embeddings
        
    except Exception as e:
        print(f"Error generating embeddings: {e}")
        traceback.print_exc()
        return []

def prepare_knowledge_base_data():
    """
    Convert knowledge base dictionary to text chunks with metadata
    """
    print("\nPreparing knowledge base data...")
    
    text_chunks = []
    metadata_list = []
    chunk_id = 1
    
    for category, content_dict in KNOWLEDGE_BASE.items():
        for subcategory, text in content_dict.items():
            # Clean and prepare text
            cleaned_text = text.strip()
            
            # Create text chunk
            text_chunks.append(cleaned_text)
            
            # Create metadata
            metadata_list.append({
                "id": chunk_id,
                "category": category,
                "subcategory": subcategory,
                "content": cleaned_text,
                "type": "knowledge_base",
                "char_count": len(cleaned_text)
            })
            
            chunk_id += 1
    
    print(f"✓ Prepared {len(text_chunks)} knowledge base entries")
    print(f"  Categories: {len(KNOWLEDGE_BASE)} ({', '.join(KNOWLEDGE_BASE.keys())})")
    
    return text_chunks, metadata_list

def ingest_to_qdrant(qdrant_client, text_chunks, metadata_list, embeddings):
    """
    Create/recreate collection and upsert knowledge base data into Qdrant
    """
    print(f"\nSetting up Qdrant collection '{KB_COLLECTION_NAME}'...")
    
    try:
        # Check if collection exists
        collections = qdrant_client.get_collections()
        collection_names = [c.name for c in collections.collections]
        
        if KB_COLLECTION_NAME in collection_names:
            print(f"  Collection '{KB_COLLECTION_NAME}' already exists - recreating...")
            qdrant_client.delete_collection(collection_name=KB_COLLECTION_NAME)
        
        # Create collection
        qdrant_client.create_collection(
            collection_name=KB_COLLECTION_NAME,
            vectors_config=models.VectorParams(
                size=VECTOR_SIZE,
                distance=models.Distance.COSINE
            )
        )
        print(f"✓ Collection '{KB_COLLECTION_NAME}' created")
        
    except Exception as e:
        print(f"Error creating collection: {e}")
        traceback.print_exc()
        return
    
    # Prepare points for upsert
    print("\nPreparing points for Qdrant...")
    points_to_upsert = []
    
    for i, (embedding, metadata) in enumerate(zip(embeddings, metadata_list)):
        point_id = metadata['id']
        
        points_to_upsert.append(
            models.PointStruct(
                id=point_id,
                vector=embedding,
                payload=metadata
            )
        )
    
    if not points_to_upsert:
        print("No points to upsert!")
        return
    
    # Upsert to Qdrant
    print(f"Upserting {len(points_to_upsert)} points to Qdrant...")
    
    try:
        qdrant_client.upsert(
            collection_name=KB_COLLECTION_NAME,
            points=points_to_upsert,
            wait=True
        )
        print(f"✓ Successfully upserted {len(points_to_upsert)} knowledge base entries")
        
        # Verify
        collection_info = qdrant_client.get_collection(KB_COLLECTION_NAME)
        print(f"✓ Verified: Collection has {collection_info.points_count} points")
        
    except Exception as e:
        print(f"Error upserting points: {e}")
        traceback.print_exc()

def main():
    """Main execution"""
    print("="*60)
    print("Healthcare Voice Agent - Knowledge Base Ingestion")
    print("="*60)
    
    # Connect to Qdrant
    try:
        print(f"\nConnecting to Qdrant at {QDRANT_HOST}:{QDRANT_PORT}...")
        qdrant_client = QdrantClient(
            host=QDRANT_HOST,
            port=QDRANT_PORT,
            api_key=QDRANT_API_KEY,
            https=False
        )
        qdrant_client.get_collections()
        print("Connected to Qdrant successfully")
    except Exception as e:
        print(f"Error connecting to Qdrant: {e}")
        sys.exit(1)
    
    # Prepare data
    text_chunks, metadata_list = prepare_knowledge_base_data()
    
    if not text_chunks or not metadata_list:
        print("Error: No knowledge base data to ingest")
        sys.exit(1)
    
    # Generate embeddings
    print(f"\nGenerating embeddings for {len(text_chunks)} entries...")
    embeddings = get_openai_embeddings(text_chunks)
    
    if not embeddings or len(embeddings) != len(text_chunks):
        print(f"Error: Expected {len(text_chunks)} embeddings, got {len(embeddings)}")
        sys.exit(1)
    
    print(f"✓ Generated {len(embeddings)} embeddings successfully")
    
    # Ingest to Qdrant
    ingest_to_qdrant(qdrant_client, text_chunks, metadata_list, embeddings)
    
    print("\n" + "="*60)
    print("✨ Knowledge Base Ingestion Complete!")
    print("="*60)
    print(f"Collection: {KB_COLLECTION_NAME}")
    print(f"Entries: {len(text_chunks)}")
    print(f"Categories: {len(KNOWLEDGE_BASE)}")
    print("\nYour voice agent can now answer policy and procedure questions!")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nIngestion interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\nFatal error: {e}")
        traceback.print_exc()
        sys.exit(1)
