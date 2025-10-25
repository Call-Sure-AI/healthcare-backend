import os
import redis
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


class RedisConfig:
    """Redis configuration and connection manager"""
    
    def __init__(self):
        self.host = os.getenv("REDIS_HOST", "localhost")
        self.port = int(os.getenv("REDIS_PORT", 6379))
        self.password = os.getenv("REDIS_PASSWORD", None)
        self.db = int(os.getenv("REDIS_DB", 0))
        self.max_connections = int(os.getenv("REDIS_MAX_CONNECTIONS"))
        self.socket_timeout = int(os.getenv("REDIS_SOCKET_TIMEOUT"))
        self.socket_connect_timeout = int(os.getenv("REDIS_SOCKET_CONNECT_TIMEOUT"))
        self.decode_responses = True
        
        self._client: Optional[redis.Redis] = None
        self._connection_pool: Optional[redis.ConnectionPool] = None
    
    def get_connection_pool(self) -> redis.ConnectionPool:
        """Create and return Redis connection pool"""
        if not self._connection_pool:
            self._connection_pool = redis.ConnectionPool(
                host=self.host,
                port=self.port,
                password=self.password if self.password else None,
                db=self.db,
                max_connections=self.max_connections,
                socket_timeout=self.socket_timeout,
                socket_connect_timeout=self.socket_connect_timeout,
                decode_responses=self.decode_responses
            )
        return self._connection_pool
    
    def get_client(self) -> redis.Redis:
        """Get Redis client instance"""
        if not self._client:
            self._client = redis.Redis(
                connection_pool=self.get_connection_pool()
            )
        return self._client
    
    def test_connection(self) -> bool:
        """Test Redis connection"""
        try:
            client = self.get_client()
            client.ping()
            print("Redis connection successful")
            return True
        except redis.ConnectionError as e:
            print(f"Redis connection failed: {e}")
            return False
        except Exception as e:
            print(f"Unexpected Redis error: {e}")
            return False
    
    def close(self):
        """Close Redis connection"""
        if self._client:
            self._client.close()
            self._client = None
        if self._connection_pool:
            self._connection_pool.disconnect()
            self._connection_pool = None


# Redis instance
redis_config = RedisConfig()


def get_redis_client() -> redis.Redis:
    """Dependency injection for Redis client"""
    return redis_config.get_client()
