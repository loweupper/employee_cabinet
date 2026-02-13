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
    redis_client.ping()
    logger.info("✅ Connected to Redis")
except Exception as e:
    logger.error(f"❌ Failed to connect to Redis: {e}")
    raise