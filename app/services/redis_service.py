import json
import redis
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from app.config.redis_config import get_redis_client
from app.config.voice_config import voice_config
import logging

logger = logging.getLogger("rag.agent")

class RedisService:
    def __init__(self):
        self.redis_client: redis.Redis = get_redis_client()
        self.default_ttl = voice_config.CALL_SESSION_TTL
    
    def _get_key(self, call_sid: str) -> str:
        return f"call_session:{call_sid}"
    
    def create_session(self, call_sid: str, session_data: Dict[str, Any]) -> bool:
        try:
            logger.debug(f"[Redis] Creating session for call_sid={call_sid}")
            key = self._get_key(call_sid)
            session_data['created_at'] = datetime.now().isoformat()
            session_data['updated_at'] = datetime.now().isoformat()
            
            self.redis_client.setex(
                key,
                self.default_ttl,
                json.dumps(session_data)
            )
            print(f"Created session: {call_sid}")
            return True
        except Exception as e:
            print(f"Error creating session: {e}")
            return False
    
    def get_session(self, call_sid: str) -> Optional[Dict[str, Any]]:
        try:
            logger.debug(f"[Redis] Getting session for call_sid={call_sid}")
            key = self._get_key(call_sid)
            data = self.redis_client.get(key)
            
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"[Redis] Error getting session for call_sid={call_sid}: {e}")
            print(f"Error getting session: {e}")
            return None
    
    def update_session(self, call_sid: str, updates: Dict[str, Any]) -> bool:
        try:
            logger.debug(f"[Redis] Updating session {call_sid} with {update_data}")
            session = self.get_session(call_sid)
            if not session:
                print(f"Session not found: {call_sid}")
                return False

            session.update(updates)
            session['updated_at'] = datetime.now().isoformat()

            key = self._get_key(call_sid)
            self.redis_client.setex(
                key,
                self.default_ttl,
                json.dumps(session)
            )
            print(f"Updated session: {call_sid}")
            return True
        except Exception as e:
            print(f"Error updating session: {e}")
            return False
    
    def append_to_conversation(self, call_sid: str, role: str, content: str) -> bool:
        try:
            session = self.get_session(call_sid)
            if not session:
                return False
            
            if 'conversation_history' not in session:
                session['conversation_history'] = []
            
            message = {
                "role": role,
                "content": content,
                "timestamp": datetime.now().isoformat()
            }
            
            session['conversation_history'].append(message)
            
            return self.update_session(call_sid, {
                'conversation_history': session['conversation_history']
            })
        except Exception as e:
            print(f"Error appending to conversation: {e}")
            return False
    
    def delete_session(self, call_sid: str) -> bool:
        try:
            key = self._get_key(call_sid)
            self.redis_client.delete(key)
            print(f"Deleted session: {call_sid}")
            return True
        except Exception as e:
            print(f"Error deleting session: {e}")
            return False
    
    def extend_session_ttl(self, call_sid: str, extra_seconds: int = 300) -> bool:
        try:
            key = self._get_key(call_sid)
            current_ttl = self.redis_client.ttl(key)
            
            if current_ttl > 0:
                new_ttl = current_ttl + extra_seconds
                self.redis_client.expire(key, new_ttl)
                return True
            return False
        except Exception as e:
            print(f"Error extending TTL: {e}")
            return False
    
    def get_all_active_sessions(self) -> list[Dict[str, Any]]:
        try:
            pattern = "call_session:*"
            keys = self.redis_client.keys(pattern)
            
            sessions = []
            for key in keys:
                data = self.redis_client.get(key)
                if data:
                    sessions.append(json.loads(data))
            
            return sessions
        except Exception as e:
            print(f"Error getting active sessions: {e}")
            return []
    
    def set_temp_data(self, call_sid: str, key: str, value: Any, ttl: int = 300) -> bool:
        try:
            redis_key = f"temp:{call_sid}:{key}"
            self.redis_client.setex(redis_key, ttl, json.dumps(value))
            return True
        except Exception as e:
            print(f"Error setting temp data: {e}")
            return False
    
    def get_temp_data(self, call_sid: str, key: str) -> Optional[Any]:
        try:
            redis_key = f"temp:{call_sid}:{key}"
            data = self.redis_client.get(redis_key)
            return json.loads(data) if data else None
        except Exception as e:
            print(f"Error getting temp data: {e}")
            return None


# Redis Global instance
redis_service = RedisService()
