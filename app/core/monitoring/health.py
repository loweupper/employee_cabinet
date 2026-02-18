"""
Comprehensive system health check module (fixed for sync SQLAlchemy)
"""
from enum import Enum
from typing import Dict, Any
from datetime import datetime
import logging
import asyncio
import time
import psutil
import shutil

logger = logging.getLogger("app")


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


# ============================================================
# DATABASE CHECK (SYNC ENGINE → RUN IN THREAD)
# ============================================================

def _check_database_sync() -> Dict[str, Any]:
    """Sync DB check executed inside a thread"""
    try:
        from core.database import engine
        from sqlalchemy import text

        start = time.time()

        # Sync engine → sync connect
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        latency_ms = round((time.time() - start) * 1000, 2)

        # Determine status
        if latency_ms < 100:
            status = HealthStatus.HEALTHY
        elif latency_ms < 500:
            status = HealthStatus.DEGRADED
        else:
            status = HealthStatus.UNHEALTHY

        return {
            "status": status.value,
            "latency_ms": latency_ms,
            "message": "Database connection successful"
        }

    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return {
            "status": HealthStatus.UNHEALTHY.value,
            "error": str(e),
            "message": "Database connection failed"
        }


async def check_database() -> Dict[str, Any]:
    """Async wrapper for sync DB check"""
    return await asyncio.to_thread(_check_database_sync)


# ============================================================
# REDIS CHECK (WITH TIMEOUT)
# ============================================================

async def check_redis() -> Dict[str, Any]:
    try:
        from core.redis import get_redis
        redis_client = await get_redis()

        start = time.time()

        # Add timeout to avoid hanging
        await asyncio.wait_for(redis_client.ping(), timeout=1.0)

        latency_ms = round((time.time() - start) * 1000, 2)

        if latency_ms < 50:
            status = HealthStatus.HEALTHY
        elif latency_ms < 200:
            status = HealthStatus.DEGRADED
        else:
            status = HealthStatus.UNHEALTHY

        return {
            "status": status.value,
            "latency_ms": latency_ms,
            "message": "Redis connection successful"
        }

    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        return {
            "status": HealthStatus.UNHEALTHY.value,
            "error": str(e),
            "message": "Redis connection failed"
        }


# ============================================================
# DISK CHECK
# ============================================================

async def check_disk_space(threshold_percent: int = 10) -> Dict[str, Any]:
    try:
        usage = shutil.disk_usage("/")

        total_gb = usage.total / (1024**3)
        used_gb = usage.used / (1024**3)
        free_gb = usage.free / (1024**3)
        percent_free = (usage.free / usage.total) * 100

        if percent_free >= threshold_percent * 2:
            status = HealthStatus.HEALTHY
        elif percent_free >= threshold_percent:
            status = HealthStatus.DEGRADED
        else:
            status = HealthStatus.UNHEALTHY

        return {
            "status": status.value,
            "total_gb": round(total_gb, 2),
            "used_gb": round(used_gb, 2),
            "free_gb": round(free_gb, 2),
            "percent_free": round(percent_free, 2),
            "message": f"{round(percent_free, 1)}% disk space available"
        }

    except Exception as e:
        logger.error(f"Disk space check failed: {e}")
        return {
            "status": HealthStatus.DEGRADED.value,
            "error": str(e),
            "message": "Could not check disk space"
        }


# ============================================================
# MEMORY CHECK
# ============================================================

async def check_memory(threshold_percent: int = 20) -> Dict[str, Any]:
    try:
        memory = psutil.virtual_memory()

        total_mb = memory.total / (1024**2)
        available_mb = memory.available / (1024**2)
        used_mb = memory.used / (1024**2)
        percent_available = memory.available / memory.total * 100

        if percent_available >= threshold_percent * 2:
            status = HealthStatus.HEALTHY
        elif percent_available >= threshold_percent:
            status = HealthStatus.DEGRADED
        else:
            status = HealthStatus.UNHEALTHY

        return {
            "status": status.value,
            "total_mb": round(total_mb, 2),
            "used_mb": round(used_mb, 2),
            "available_mb": round(available_mb, 2),
            "percent_available": round(percent_available, 2),
            "message": f"{round(percent_available, 1)}% memory available"
        }

    except Exception as e:
        logger.error(f"Memory check failed: {e}")
        return {
            "status": HealthStatus.DEGRADED.value,
            "error": str(e),
            "message": "Could not check memory"
        }


# ============================================================
# SYSTEM INFO
# ============================================================

async def get_system_info() -> Dict[str, Any]:
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_count = psutil.cpu_count()

        load_avg = psutil.getloadavg() if hasattr(psutil, "getloadavg") else (0, 0, 0)

        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.utcnow() - boot_time.replace(tzinfo=None)

        return {
            "cpu_percent": cpu_percent,
            "cpu_count": cpu_count,
            "load_average": {
                "1min": round(load_avg[0], 2),
                "5min": round(load_avg[1], 2),
                "15min": round(load_avg[2], 2)
            },
            "uptime_seconds": int(uptime.total_seconds()),
            "boot_time": boot_time.isoformat()
        }

    except Exception as e:
        logger.error(f"Could not get system info: {e}")
        return {"error": str(e)}


# ============================================================
# MAIN HEALTH CHECK
# ============================================================

async def check_health(detailed: bool = False) -> Dict[str, Any]:
    checks = {}

    try:
        db_check, redis_check, disk_check, memory_check = await asyncio.gather(
            check_database(),
            check_redis(),
            check_disk_space(),
            check_memory(),
            return_exceptions=True
        )

        def normalize(result):
            if isinstance(result, Exception):
                return {"status": HealthStatus.UNHEALTHY.value, "error": str(result)}
            return result

        checks["database"] = normalize(db_check)
        checks["redis"] = normalize(redis_check)
        checks["disk"] = normalize(disk_check)
        checks["memory"] = normalize(memory_check)

    except Exception as e:
        logger.error(f"Error during health check: {e}")
        return {
            "status": HealthStatus.UNHEALTHY.value,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

    statuses = [c["status"] for c in checks.values()]

    if HealthStatus.UNHEALTHY.value in statuses:
        overall = HealthStatus.UNHEALTHY
    elif HealthStatus.DEGRADED.value in statuses:
        overall = HealthStatus.DEGRADED
    else:
        overall = HealthStatus.HEALTHY

    result = {
        "status": overall.value,
        "timestamp": datetime.utcnow().isoformat()
    }

    if detailed:
        result["checks"] = checks
        result["system"] = await get_system_info()

    return result