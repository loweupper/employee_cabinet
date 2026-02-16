"""
Comprehensive system health check module
"""
from enum import Enum
from typing import Dict, Any, Optional
from datetime import datetime
import logging
import asyncio
import time
import psutil
import shutil

logger = logging.getLogger("app")


class HealthStatus(str, Enum):
    """System health status levels"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


async def check_health(detailed: bool = False) -> Dict[str, Any]:
    """
    Check overall system health
    
    Args:
        detailed: Whether to return detailed health information
        
    Returns:
        Dictionary with health status and checks
    """
    checks = {}
    overall_status = HealthStatus.HEALTHY
    
    # Run all health checks concurrently
    try:
        db_check, redis_check, disk_check, memory_check = await asyncio.gather(
            check_database(),
            check_redis(),
            check_disk_space(),
            check_memory(),
            return_exceptions=True
        )
        
        checks["database"] = db_check if not isinstance(db_check, Exception) else {
            "status": HealthStatus.UNHEALTHY.value,
            "error": str(db_check)
        }
        checks["redis"] = redis_check if not isinstance(redis_check, Exception) else {
            "status": HealthStatus.UNHEALTHY.value,
            "error": str(redis_check)
        }
        checks["disk"] = disk_check if not isinstance(disk_check, Exception) else {
            "status": HealthStatus.DEGRADED.value,
            "error": str(disk_check)
        }
        checks["memory"] = memory_check if not isinstance(memory_check, Exception) else {
            "status": HealthStatus.DEGRADED.value,
            "error": str(memory_check)
        }
        
    except Exception as e:
        logger.error(f"Error during health check: {e}")
        return {
            "status": HealthStatus.UNHEALTHY.value,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }
    
    # Determine overall status
    statuses = [check.get("status") for check in checks.values()]
    
    if HealthStatus.UNHEALTHY.value in statuses:
        overall_status = HealthStatus.UNHEALTHY
    elif HealthStatus.DEGRADED.value in statuses:
        overall_status = HealthStatus.DEGRADED
    
    result = {
        "status": overall_status.value,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    if detailed:
        result["checks"] = checks
        result["system"] = await get_system_info()
    
    return result


async def check_database() -> Dict[str, Any]:
    """
    Check database connectivity and latency
    
    Returns:
        Database health status
    """
    try:
        from core.database import engine
        from sqlalchemy import text
        
        start = time.time()
        
        # Try to execute a simple query
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        
        latency_ms = round((time.time() - start) * 1000, 2)
        
        # Update metrics
        from core.monitoring.metrics import update_database_connections, record_database_query
        try:
            # Get pool status
            pool = engine.pool
            pool_size = pool.size()
            checked_in = pool.checkedin()
            checked_out = pool_size - checked_in
            
            update_database_connections(checked_out)
        except Exception as e:
            logger.debug(f"Could not get pool metrics: {e}")
        
        record_database_query(latency_ms / 1000)
        
        # Determine status based on latency
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


async def check_redis() -> Dict[str, Any]:
    """
    Check Redis connectivity and latency
    
    Returns:
        Redis health status
    """
    try:
        from core.redis import get_redis
        
        redis_client = await get_redis()
        
        start = time.time()
        await redis_client.ping()
        latency_ms = round((time.time() - start) * 1000, 2)
        
        # Determine status based on latency
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


async def check_disk_space(threshold_percent: int = 10) -> Dict[str, Any]:
    """
    Check available disk space
    
    Args:
        threshold_percent: Minimum free space percentage (default 10%)
        
    Returns:
        Disk space health status
    """
    try:
        # Check root partition
        usage = shutil.disk_usage("/")
        
        total_gb = usage.total / (1024**3)
        used_gb = usage.used / (1024**3)
        free_gb = usage.free / (1024**3)
        percent_free = (usage.free / usage.total) * 100
        
        # Determine status
        if percent_free >= threshold_percent * 2:  # >= 20%
            status = HealthStatus.HEALTHY
        elif percent_free >= threshold_percent:  # >= 10%
            status = HealthStatus.DEGRADED
        else:  # < 10%
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


async def check_memory(threshold_percent: int = 20) -> Dict[str, Any]:
    """
    Check available memory
    
    Args:
        threshold_percent: Minimum available memory percentage (default 20%)
        
    Returns:
        Memory health status
    """
    try:
        memory = psutil.virtual_memory()
        
        total_mb = memory.total / (1024**2)
        available_mb = memory.available / (1024**2)
        used_mb = memory.used / (1024**2)
        percent_available = memory.available / memory.total * 100
        
        # Determine status
        if percent_available >= threshold_percent * 2:  # >= 40%
            status = HealthStatus.HEALTHY
        elif percent_available >= threshold_percent:  # >= 20%
            status = HealthStatus.DEGRADED
        else:  # < 20%
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


async def get_system_info() -> Dict[str, Any]:
    """
    Get general system information
    
    Returns:
        System information dictionary
    """
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_count = psutil.cpu_count()
        
        load_avg = psutil.getloadavg() if hasattr(psutil, 'getloadavg') else (0, 0, 0)
        
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
