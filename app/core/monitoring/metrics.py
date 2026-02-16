"""
Prometheus-compatible metrics collection system for monitoring application performance
"""
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from typing import Optional
import logging

logger = logging.getLogger("app")

# HTTP Request Metrics
http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status_code']
)

http_request_duration_seconds = Histogram(
    'http_request_duration_seconds',
    'HTTP request latency in seconds',
    ['method', 'endpoint'],
    buckets=(0.001, 0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0)
)

# Authentication Metrics
auth_attempts_total = Counter(
    'auth_attempts_total',
    'Total authentication attempts',
    ['result', 'email']
)

auth_failures_total = Counter(
    'auth_failures_total',
    'Total authentication failures',
    ['email']
)

# Session Metrics
active_sessions_count = Gauge(
    'active_sessions_count',
    'Number of currently active user sessions'
)

# File Upload Metrics
file_uploads_total = Counter(
    'file_uploads_total',
    'Total file upload attempts',
    ['file_type', 'result']
)

# Security Event Metrics
security_events_total = Counter(
    'security_events_total',
    'Total security events detected',
    ['event_type']
)

# Database Metrics
database_connections = Gauge(
    'database_connections',
    'Number of active database connections'
)

database_query_duration_seconds = Histogram(
    'database_query_duration_seconds',
    'Database query execution time',
    buckets=(0.001, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0)
)


# Helper functions for recording metrics
def record_request(method: str, endpoint: str, status_code: int, duration: float):
    """
    Record HTTP request metrics
    
    Args:
        method: HTTP method (GET, POST, etc.)
        endpoint: API endpoint path
        status_code: HTTP response status code
        duration: Request duration in seconds
    """
    try:
        # Sanitize endpoint to avoid high cardinality
        sanitized_endpoint = _sanitize_endpoint(endpoint)
        
        http_requests_total.labels(
            method=method,
            endpoint=sanitized_endpoint,
            status_code=status_code
        ).inc()
        
        http_request_duration_seconds.labels(
            method=method,
            endpoint=sanitized_endpoint
        ).observe(duration)
    except Exception as e:
        logger.error(f"Failed to record request metrics: {e}")


def record_auth_attempt(email: str, success: bool):
    """
    Record authentication attempt
    
    Args:
        email: User email attempting authentication
        success: Whether authentication was successful
    """
    try:
        # Mask email for privacy
        masked_email = _mask_email(email)
        result = "success" if success else "failure"
        
        auth_attempts_total.labels(
            result=result,
            email=masked_email
        ).inc()
        
        if not success:
            auth_failures_total.labels(email=masked_email).inc()
    except Exception as e:
        logger.error(f"Failed to record auth attempt metrics: {e}")


def update_active_sessions(count: int):
    """
    Update active sessions count
    
    Args:
        count: Current number of active sessions
    """
    try:
        active_sessions_count.set(count)
    except Exception as e:
        logger.error(f"Failed to update active sessions: {e}")


def record_file_upload(file_type: str, success: bool):
    """
    Record file upload attempt
    
    Args:
        file_type: Type/extension of uploaded file
        success: Whether upload was successful
    """
    try:
        result = "success" if success else "failure"
        file_uploads_total.labels(
            file_type=file_type,
            result=result
        ).inc()
    except Exception as e:
        logger.error(f"Failed to record file upload metrics: {e}")


def record_security_event(event_type: str):
    """
    Record security event
    
    Args:
        event_type: Type of security event (e.g., 'brute_force', 'sql_injection')
    """
    try:
        security_events_total.labels(event_type=event_type).inc()
    except Exception as e:
        logger.error(f"Failed to record security event: {e}")


def update_database_connections(count: int):
    """
    Update database connections count
    
    Args:
        count: Current number of active database connections
    """
    try:
        database_connections.set(count)
    except Exception as e:
        logger.error(f"Failed to update database connections: {e}")


def record_database_query(duration: float):
    """
    Record database query execution time
    
    Args:
        duration: Query duration in seconds
    """
    try:
        database_query_duration_seconds.observe(duration)
    except Exception as e:
        logger.error(f"Failed to record database query metrics: {e}")


def get_metrics() -> bytes:
    """
    Get all metrics in Prometheus format
    
    Returns:
        Metrics data in Prometheus text format
    """
    return generate_latest()


def get_metrics_content_type() -> str:
    """
    Get the content type for Prometheus metrics
    
    Returns:
        Content type string
    """
    return CONTENT_TYPE_LATEST


def _sanitize_endpoint(endpoint: str) -> str:
    """
    Sanitize endpoint to avoid high cardinality in metrics
    Replaces IDs and dynamic parts with placeholders
    
    Args:
        endpoint: Original endpoint path
        
    Returns:
        Sanitized endpoint path
    """
    import re
    
    # Replace numeric IDs with placeholder
    endpoint = re.sub(r'/\d+', '/{id}', endpoint)
    
    # Replace UUIDs with placeholder
    endpoint = re.sub(
        r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
        '/{uuid}',
        endpoint,
        flags=re.IGNORECASE
    )
    
    # Limit endpoint length
    if len(endpoint) > 100:
        endpoint = endpoint[:100] + '...'
    
    return endpoint


def _mask_email(email: str) -> str:
    """
    Mask email address for privacy in metrics
    
    Args:
        email: Email address to mask
        
    Returns:
        Masked email (e.g., u***@example.com)
    """
    try:
        if '@' not in email:
            return 'invalid@email'
        
        local, domain = email.split('@', 1)
        if len(local) <= 1:
            masked_local = '*'
        else:
            masked_local = local[0] + '***'
        
        return f"{masked_local}@{domain}"
    except Exception:
        return 'unknown@email'
