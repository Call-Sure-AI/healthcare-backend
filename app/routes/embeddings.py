from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
import logging
from typing import Dict, Optional
from datetime import datetime

from app.config.database import get_db, SessionLocal
from app.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/embeddings", tags=["embeddings"])

task_status_store: Dict[str, Dict] = {}

class EmbeddingResponse(BaseModel):
    status: str
    message: str
    doctors_count: int | None = None

class TaskResponse(BaseModel):
    task_id: str
    status: str
    message: str

class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: int
    message: str
    result: Optional[Dict] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

async def run_embedding_ingestion_with_tracking(task_id: str):
    """Background task with status tracking"""
    task_status_store[task_id] = {
        "status": "processing",
        "progress": 0,
        "message": "Starting ingestion...",
        "started_at": datetime.now().isoformat(),
        "result": None
    }
    
    db = SessionLocal()
    
    try:
        task_status_store[task_id].update({
            "progress": 20,
            "message": "Fetching doctor data from PostgreSQL..."
        })
        
        chunks, metadata = embedding_service.prepare_doctor_data(db)
        
        if not chunks:
            task_status_store[task_id].update({
                "status": "completed",
                "progress": 100,
                "message": "No doctor data found",
                "result": {"doctors_count": 0},
                "completed_at": datetime.now().isoformat()
            })
            return
        
        task_status_store[task_id].update({
            "progress": 40,
            "message": f"Generating embeddings for {len(chunks)} doctors..."
        })
        
        embeddings = embedding_service.get_openai_embeddings(chunks)

        task_status_store[task_id].update({
            "progress": 80,
            "message": "Uploading embeddings to Qdrant..."
        })
        
        embedding_service.ingest_to_qdrant(chunks, metadata, embeddings)

        task_status_store[task_id].update({
            "status": "completed",
            "progress": 100,
            "message": f"Successfully ingested {len(chunks)} doctors",
            "result": {"doctors_count": len(chunks)},
            "completed_at": datetime.now().isoformat()
        })
        
        logger.info(f"Task {task_id} completed successfully")
        
    except Exception as e:
        logger.error(f"Task {task_id} failed: {str(e)}")
        task_status_store[task_id].update({
            "status": "failed",
            "progress": 0,
            "message": f"Error: {str(e)}",
            "completed_at": datetime.now().isoformat()
        })
    finally:
        db.close()

@router.post("/ingest-sync", response_model=EmbeddingResponse)
async def ingest_embeddings_sync(db: Session = Depends(get_db)):
    """
    Synchronous embedding ingestion (blocks until complete).
    Use for immediate confirmation.
    """
    try:
        logger.info("Sync ingestion endpoint called")
        result = await embedding_service.run_full_ingestion(db)
        return result
    except Exception as e:
        logger.error(f"Sync ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/ingest-async", response_model=TaskResponse)
async def ingest_embeddings_async(background_tasks: BackgroundTasks):
    """
    Asynchronous embedding ingestion with status tracking.
    Returns immediately with task_id.
    """
    try:
        task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        
        logger.info(f"Async ingestion endpoint called - Task ID: {task_id}")
        
        background_tasks.add_task(run_embedding_ingestion_with_tracking, task_id)
        
        return {
            "task_id": task_id,
            "status": "queued",
            "message": "Embedding ingestion started. Use task_id to check status."
        }
        
    except Exception as e:
        logger.error(f"Failed to queue task: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """Check status of an async embedding task"""
    if task_id not in task_status_store:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task_info = task_status_store[task_id]
    
    return {
        "task_id": task_id,
        "status": task_info["status"],
        "progress": task_info["progress"],
        "message": task_info["message"],
        "result": task_info.get("result"),
        "started_at": task_info.get("started_at"),
        "completed_at": task_info.get("completed_at")
    }

@router.get("/tasks")
async def list_all_tasks():
    """List all tracked tasks"""
    return {
        "tasks": [
            {
                "task_id": task_id,
                "status": info["status"],
                "progress": info["progress"],
                "message": info["message"],
                "started_at": info.get("started_at")
            }
            for task_id, info in task_status_store.items()
        ],
        "total_tasks": len(task_status_store)
    }

@router.delete("/tasks/cleanup")
async def cleanup_completed_tasks():
    """Remove completed/failed tasks from memory"""
    initial_count = len(task_status_store)
    
    completed_tasks = [
        task_id for task_id, info in task_status_store.items()
        if info["status"] in ["completed", "failed"]
    ]
    
    for task_id in completed_tasks:
        del task_status_store[task_id]
    
    return {
        "message": f"Cleaned up {len(completed_tasks)} tasks",
        "initial_count": initial_count,
        "remaining_count": len(task_status_store)
    }
