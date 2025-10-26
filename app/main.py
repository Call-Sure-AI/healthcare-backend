from fastapi import FastAPI, Request, status, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.config.database import engine, Base
from app.routes import doctor, appointment
from app.routes import voice_agent
from app.config.redis_config import redis_config
from app.config.voice_config import voice_config
import time
from fastapi.staticfiles import StaticFiles
from fastapi import WebSocket, Query
from typing import Dict, Any
import base64
from app.services.voice_agent_service import VoiceAgentService
from app.services.deepgram_service import DeepgramManager
from app.services.elevenlabs_service import elevenlabs_service  
from app.services.redis_service import redis_service
from app.config.voice_config import voice_config
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import inspect
import logging

logging.basicConfig(level=logging.DEBUG)

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Healthcare Appointment Booking System",
    description="""
    Healthcare Appointment Management API
    
    This API allows you to manage doctors and appointments for healthcare organizations.
    
    ### Features:
    * **Doctor Management**: Add, update, and manage doctor profiles with shift timings
    * **Appointment Booking**: Book appointments with availability and capacity validation
    * **Availability Checking**: Get available time slots for any doctor
    * **Statistics**: Track appointment metrics and doctor utilization
    
    ### Business Rules:
    * Maximum **4 appointments per hour** per doctor
    * Appointments in **15-minute intervals** (00, 15, 30, 45)
    * Automatic validation of shift timings and availability dates
    
    ### For Frontend Developers:
    * All endpoints return consistent JSON responses
    * Errors include detailed messages and status codes
    * CORS enabled for cross-origin requests
    * OpenAPI schema available at `/openapi.json`
    """,
    version="1.0.0",
    contact={
        "name": "Healthcare API Support",
        "email": "support@healthcare-api.com",
    },
    license_info={
        "name": "MIT License",
        "url": "https://opensource.org/licenses/MIT",
    },
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    swagger_ui_parameters={
        "defaultModelsExpandDepth": -1,
        "docExpansion": "none",
        "filter": True,
        "showRequestHeaders": True,
        "syntaxHighlight.theme": "monokai"
    }
)

origins = [
    "http://localhost:3000",  # React
    "http://localhost:3001",
    "http://localhost:4200",  # Angular
    "http://localhost:5173",  # Vite
    "http://localhost:8080",  # Vue
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8080",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"]  # All hosts allowed for WebSocket compatibility
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"Request path: {request.url.path}")
    print(f"Request headers: {dict(request.headers)}")
    print(f"Request client: {request.client}")
    
    if "upgrade" in request.headers.get("connection", "").lower():
        print("WebSocket upgrade detected!")
        print(f"Origin header: {request.headers.get('origin', 'NO ORIGIN')}")
        print(f"Host header: {request.headers.get('host', 'NO HOST')}")
    
    response = await call_next(request)
    return response

class WebSocketMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path == "/api/v1/voice/stream":
            if "origin" in request.headers:
                request.scope["headers"] = [
                    (k, v) for k, v in request.scope["headers"] 
                    if k.lower() != b"origin"
                ]
        
        response = await call_next(request)
        return response

app.add_middleware(WebSocketMiddleware)

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "code": exc.status_code,
                "message": exc.detail,
                "type": "HTTPException"
            },
            "data": None
        }
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        errors.append({
            "field": " -> ".join(str(loc) for loc in error["loc"]),
            "message": error["msg"],
            "type": error["type"]
        })
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "error": {
                "code": 422,
                "message": "Validation Error",
                "type": "ValidationError",
                "details": errors
            },
            "data": None
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error": {
                "code": 500,
                "message": "Internal server error",
                "type": "InternalError"
            },
            "data": None
        }
    )

@app.websocket("/test-ws")
async def test_websocket(websocket: WebSocket):
    print("Test WebSocket endpoint hit!")
    await websocket.accept()
    print("Test WebSocket accepted!")
    await websocket.send_text("Connected successfully!")
    await websocket.close()


system_router = APIRouter(prefix="/api", tags=["System"])

@system_router.get("/")
def api_root():
    """Root API endpoint with information"""
    return {
        "success": True,
        "data": {
            "message": "Healthcare Appointment Booking System API",
            "version": "1.0.0",
            "documentation": {
                "swagger_ui": "/api/docs",
                "redoc": "/api/redoc",
                "openapi_schema": "/api/openapi.json"
            },
            "endpoints": {
                "doctors": "/api/v1/doctors",
                "appointments": "/api/v1/appointments"
            }
        }
    }

@system_router.get("/health")
def health_check():
    """Health check endpoint for monitoring"""
    return {
        "success": True,
        "data": {
            "status": "healthy",
            "service": "healthcare-api",
            "version": "1.0.0"
        }
    }

@system_router.get("/debug/routes")
def list_routes():
    routes = []
    for route in app.routes:
        route_info = {
            "path": route.path,
            "name": getattr(route, "name", "N/A"),
        }
        
        if hasattr(route, "endpoint"):
            if inspect.iscoroutinefunction(route.endpoint):
                sig = inspect.signature(route.endpoint)
                if any("WebSocket" in str(param.annotation) for param in sig.parameters.values()):
                    route_info["type"] = "WebSocket"
                else:
                    route_info["type"] = "HTTP"
        
        routes.append(route_info)
    
    return {"total": len(routes), "routes": routes}

@app.get("/api/v1/status", tags=["System"])
def api_status():
    """Detailed API status information"""
    return {
        "success": True,
        "data": {
            "api_version": "1.0.0",
            "status": "operational",
            "features": {
                "doctor_management": True,
                "appointment_booking": True,
                "availability_check": True,
                "statistics": True
            },
            "limits": {
                "max_appointments_per_hour": 4,
                "appointment_interval_minutes": 15
            }
        }
    }
app.include_router(system_router)

app.include_router(doctor.router, prefix="/api/v1", tags=["👨‍⚕️ Doctors"])
app.include_router(appointment.router, prefix="/api/v1", tags=["📅 Appointments"])
app.include_router(voice_agent.router, prefix="/api/v1", tags=["Voice Agent"])

app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
