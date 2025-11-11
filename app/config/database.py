# app/config/database.py - ULTRA OPTIMIZED

from sqlalchemy import create_engine, pool
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import os
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    database_url: str

    api_version: str = "1.0.0"
    api_title: str = "Healthcare Appointment Booking System"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    allowed_origins: str = "http://localhost:3000,http://localhost:5173"
    debug: bool = True
    log_level: str = "info"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra='ignore'
    )

settings = Settings()

# ⚡ OPTIMIZED: Larger connection pool for parallel queries
engine = create_engine(
    settings.database_url,
    poolclass=pool.QueuePool,
    pool_size=20,  # ⚡ Increased from 10
    max_overflow=40,  # ⚡ Increased from 20
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False  # ⚡ Disable echo in production
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
