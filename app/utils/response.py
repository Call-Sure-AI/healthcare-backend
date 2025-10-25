from typing import Any, Optional
from fastapi.responses import JSONResponse
from fastapi import status

class APIResponse:    
    @staticmethod
    def success(data: Any, message: str = "Success", status_code: int = status.HTTP_200_OK):
        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": message,
                "data": data,
                "error": None
            }
        )
    
    @staticmethod
    def created(data: Any, message: str = "Resource created successfully"):
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "success": True,
                "message": message,
                "data": data,
                "error": None
            }
        )
    
    @staticmethod
    def error(message: str, error_type: str = "Error", status_code: int = status.HTTP_400_BAD_REQUEST, details: Optional[Any] = None):
        return JSONResponse(
            status_code=status_code,
            content={
                "success": False,
                "message": None,
                "data": None,
                "error": {
                    "code": status_code,
                    "message": message,
                    "type": error_type,
                    "details": details
                }
            }
        )
