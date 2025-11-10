# app/services/redis_service.py - ULTRA OPTIMIZED

import json
import redis
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from app.config.redis_config import get_redis_client
from app.config.voice_config import voice_config
import logging
import hashlib

logger = logging.getLogger("redis")

class RedisService:
    def __init__(self):
        self.redis_client: redis.Redis = get_redis_client()
        self.default_ttl = voice_config.CALL_SESSION_TTL

    def _get_key(self, call_sid: str) -> str:
        return f"call_session:{call_sid}"
    
    def _get_cache_key(self, prefix: str, identifier: str) -> str:
        """⚡ NEW: Generate cache keys"""
        return f"cache:{prefix}:{identifier}"

    def create_session(self, call_sid: str, session_data: Dict[str, Any]) -> bool:
        try:
            logger.debug(f"Creating session for {call_sid}")
            key = self._get_key(call_sid)
            session_data['created_at'] = datetime.now().isoformat()
            session_data['updated_at'] = datetime.now().isoformat()

            self.redis_client.setex(
                key,
                self.default_ttl,
                json.dumps(session_data)
            )
            logger.debug(f"✓ Created session: {call_sid}")
            return True
        except Exception as e:
            logger.error(f"❌ Error creating session: {e}")
            return False

    def get_session(self, call_sid: str) -> Optional[Dict[str, Any]]:
        try:
            key = self._get_key(call_sid)
            data = self.redis_client.get(key)

            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"❌ Error getting session {call_sid}: {e}")
            return None

    def update_session(self, call_sid: str, updates: Dict[str, Any]) -> bool:
        try:
            logger.debug(f"Updating session {call_sid} with {updates}")
            session = self.get_session(call_sid)
            if not session:
                logger.warning(f"Session not found: {call_sid}")
                return False

            session.update(updates)
            session['updated_at'] = datetime.now().isoformat()

            key = self._get_key(call_sid)
            self.redis_client.setex(
                key,
                self.default_ttl,
                json.dumps(session)
            )
            logger.debug(f"✓ Updated session: {call_sid}")
            return True
        except Exception as e:
            logger.error(f"❌ Error updating session: {e}")
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
            logger.error(f"❌ Error appending to conversation: {e}")
            return False

    # ⚡ NEW: Response caching methods
    def cache_response(
        self, 
        query_hash: str, 
        response: str, 
        ttl: int = 3600
    ) -> bool:
        """
        ⚡ NEW: Cache AI responses for common queries
        """
        try:
            key = self._get_cache_key("response", query_hash)
            self.redis_client.setex(key, ttl, response)
            logger.debug(f"✓ Cached response: {query_hash[:8]}")
            return True
        except Exception as e:
            logger.error(f"❌ Cache error: {e}")
            return False
    
    def get_cached_response(self, query_hash: str) -> Optional[str]:
        """
        ⚡ NEW: Retrieve cached response
        """
        try:
            key = self._get_cache_key("response", query_hash)
            data = self.redis_client.get(key)
            if data:
                logger.debug(f"✓ Cache hit: {query_hash[:8]}")
                return data
            return None
        except Exception as e:
            logger.error(f"❌ Cache retrieval error: {e}")
            return None
    
    def cache_tool_result(
        self,
        tool_name: str,
        args_hash: str,
        result: Dict[str, Any],
        ttl: int = 300  # 5 minutes for tool results
    ) -> bool:
        """
        ⚡ NEW: Cache tool execution results
        """
        try:
            key = self._get_cache_key(f"tool:{tool_name}", args_hash)
            self.redis_client.setex(key, ttl, json.dumps(result))
            logger.debug(f"✓ Cached tool result: {tool_name}")
            return True
        except Exception as e:
            logger.error(f"❌ Tool cache error: {e}")
            return False
    
    def get_cached_tool_result(
        self,
        tool_name: str,
        args_hash: str
    ) -> Optional[Dict[str, Any]]:
        """
        ⚡ NEW: Get cached tool result
        """
        try:
            key = self._get_cache_key(f"tool:{tool_name}", args_hash)
            data = self.redis_client.get(key)
            if data:
                logger.debug(f"✓ Tool cache hit: {tool_name}")
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"❌ Tool cache retrieval error: {e}")
            return None
    
    @staticmethod
    def hash_query(text: str) -> str:
        """⚡ NEW: Generate hash for caching"""
        return hashlib.md5(text.lower().strip().encode()).hexdigest()

    def delete_session(self, call_sid: str) -> bool:
        try:
            key = self._get_key(call_sid)
            self.redis_client.delete(key)
            logger.debug(f"✓ Deleted session: {call_sid}")
            return True
        except Exception as e:
            logger.error(f"❌ Error deleting session: {e}")
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
            logger.error(f"❌ Error extending TTL: {e}")
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
            logger.error(f"❌ Error getting active sessions: {e}")
            return []

    def set_temp_data(self, call_sid: str, key: str, value: Any, ttl: int = 300) -> bool:
        try:
            redis_key = f"temp:{call_sid}:{key}"
            self.redis_client.setex(redis_key, ttl, json.dumps(value))
            return True
        except Exception as e:
            logger.error(f"❌ Error setting temp data: {e}")
            return False

    def get_temp_data(self, call_sid: str, key: str) -> Optional[Any]:
        try:
            redis_key = f"temp:{call_sid}:{key}"
            data = self.redis_client.get(redis_key)
            return json.loads(data) if data else None
        except Exception as e:
            logger.error(f"❌ Error getting temp data: {e}")
            return None


# Global instance
redis_service = RedisService()
