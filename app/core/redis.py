import redis
from core.config import settings
import logging

logger = logging.getLogger(__name__)

try:
    redis_client = redis.from_url(
        settings.REDIS_URL,
        encoding="utf8",
        decode_responses=True,
        socket_connect_timeout=5,
        socket_keepalive=True,
    )
    # Проверяем соединение
    try:
        redis_client.ping()
        logger.info("✅ Connected to Redis")
    except (redis.ConnectionError, redis.TimeoutError) as e:
        logger.error(f"❌ Failed to connect to Redis: {e}")
        logger.warning("⚠️ Application will continue without Redis. Some features may be unavailable.")
except Exception as e:
    logger.error(f"❌ Failed to initialize Redis client: {e}")
    logger.warning("⚠️ Application will continue without Redis. Some features may be unavailable.")
    # Create a dummy redis client that can be imported but won't work
    redis_client = None