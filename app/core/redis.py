import asyncio
import logging

import redis
import redis.asyncio as aioredis

from core.config import settings

logger = logging.getLogger(__name__)

# Sync Redis client (for backward compatibility)
redis_client = None
# Async Redis client
async_redis_client = None


def _build_common_kwargs() -> dict:
    return {
        "encoding": "utf8",
        "decode_responses": True,
        "socket_connect_timeout": 5,
        "socket_keepalive": True,
    }


def _create_sync_client() -> redis.Redis:
    return redis.from_url(settings.REDIS_URL, **_build_common_kwargs())


async def _create_async_client() -> aioredis.Redis:
    client = await aioredis.from_url(
        settings.REDIS_URL,
        **_build_common_kwargs(),
    )
    await asyncio.wait_for(client.ping(), timeout=1.0)
    return client


async def _close_async_client_safely(client: aioredis.Redis) -> None:
    try:
        await client.aclose()
    except AttributeError:
        await client.close()
    except Exception:
        # Ignore close errors during reconnect/teardown.
        pass


try:
    # Sync client
    redis_client = _create_sync_client()

    # Test connection
    redis_client.ping()
    logger.info({"event": "redis_sync_connected"})

except Exception as e:
    logger.error(
        {
            "event": "redis_sync_connection_failed",
            "error_type": type(e).__name__,
            "error": str(e),
        }
    )
    logger.warning(
        {
            "event": "redis_sync_disabled",
            "message": "Application will continue without Redis",
        }
    )
    redis_client = None


async def get_redis() -> aioredis.Redis:
    """
    Get async Redis client instance.
    Creates connection pool if not exists.
    """
    global async_redis_client

    if async_redis_client is None:
        try:
            async_redis_client = await _create_async_client()
            logger.info({"event": "redis_async_connected"})
        except Exception as e:
            logger.error(
                {
                    "event": "redis_async_connection_failed",
                    "error_type": type(e).__name__,
                    "error": str(e),
                }
            )
            raise
    else:
        try:
            await asyncio.wait_for(async_redis_client.ping(), timeout=1.0)
        except Exception as ping_error:
            logger.warning(
                {
                    "event": "redis_async_ping_failed",
                    "error_type": type(ping_error).__name__,
                }
            )
            await _close_async_client_safely(async_redis_client)
            async_redis_client = None

            try:
                async_redis_client = await _create_async_client()
                logger.info({"event": "redis_async_reconnected"})
            except Exception as reconnect_error:
                logger.error(
                    {
                        "event": "redis_async_reconnect_failed",
                        "error_type": type(reconnect_error).__name__,
                        "error": str(reconnect_error),
                    }
                )
                raise

    return async_redis_client


def get_redis_sync() -> redis.Redis:
    """
    Get sync Redis client instance.
    Returns None if Redis is not available.
    """
    global redis_client
    if redis_client is not None:
        try:
            redis_client.ping()
            return redis_client
        except Exception as e:
            logger.warning(
                {
                    "event": "redis_sync_ping_failed",
                    "error_type": type(e).__name__,
                }
            )
            redis_client = None

    try:
        redis_client = _create_sync_client()
        redis_client.ping()
        logger.info({"event": "redis_sync_reconnected"})
        return redis_client
    except Exception as e:
        logger.warning(
            {
                "event": "redis_sync_unavailable",
                "error_type": type(e).__name__,
            }
        )
        redis_client = None
        return None


def is_redis_sync_available() -> bool:
    """Quick status helper used by services to log degraded mode once."""
    return get_redis_sync() is not None


async def close_redis():
    """Close Redis connections"""
    global async_redis_client

    if async_redis_client:
        try:
            await _close_async_client_safely(async_redis_client)
        finally:
            async_redis_client = None
            logger.info({"event": "redis_async_closed"})
