import redis.asyncio as aioredis
import redis
from core.config import settings
import logging

logger = logging.getLogger(__name__)

# Sync Redis client (for backward compatibility)
redis_client = None
# Async Redis client
async_redis_client = None

try:
    # Sync client
    redis_client = redis.from_url(
        settings.REDIS_URL,
        encoding="utf8",
        decode_responses=True,
        socket_connect_timeout=5,
        socket_keepalive=True,
    )
    
    # Test connection
    redis_client.ping()
    logger.info("✅ Connected to Redis (sync)")
    
except Exception as e:
    logger.error(f"❌ Failed to connect to Redis: {e}")
    logger.warning("⚠️ Application will continue without Redis. Some features may be unavailable.")
    redis_client = None


async def get_redis() -> aioredis.Redis:
    """
    Get async Redis client instance.
    Creates connection pool if not exists.
    """
    global async_redis_client
    
    if async_redis_client is None:
        try:
            async_redis_client = await aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf8",
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
            )
            await async_redis_client.ping()
            logger.info("✅ Connected to Redis (async)")
        except Exception as e:
            logger.error(f"❌ Failed to connect to async Redis: {e}")
            raise
    
    return async_redis_client


def get_redis_sync() -> redis.Redis:
    """
    Get sync Redis client instance.
    Returns None if Redis is not available.
    """
    return redis_client


async def close_redis():
    """Close Redis connections"""
    global async_redis_client
    
    if async_redis_client:
        await async_redis_client.close()
        async_redis_client = None
        logger.info("Redis async connection closed")
