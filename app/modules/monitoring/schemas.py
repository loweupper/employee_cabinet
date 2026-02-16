"""
Pydantic schemas for monitoring API
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any
from datetime import datetime
from enum import Enum


class AlertSeveritySchema(str, Enum):
    """Alert severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertTypeSchema(str, Enum):
    """Types of security alerts"""
    MULTIPLE_FAILED_LOGINS = "multiple_failed_logins"
    NEW_IP_LOGIN = "new_ip_login"
    SUSPICIOUS_FILE_UPLOAD = "suspicious_file_upload"
    SQL_INJECTION_ATTEMPT = "sql_injection_attempt"
    XSS_ATTEMPT = "xss_attempt"
    BRUTE_FORCE_ATTEMPT = "brute_force_attempt"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    UNUSUAL_ACTIVITY = "unusual_activity"
    ACCOUNT_LOCKOUT = "account_lockout"


class AlertResponse(BaseModel):
    """Alert data for API responses"""
    id: str
    timestamp: datetime
    severity: AlertSeveritySchema
    type: AlertTypeSchema
    message: str
    user_id: Optional[int] = None
    ip_address: str
    details: Dict[str, Any]
    resolved: bool = False
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[int] = None
    
    class Config:
        from_attributes = True


class AlertListResponse(BaseModel):
    """Paginated list of alerts"""
    alerts: List[AlertResponse]
    total: int
    page: int = 1
    per_page: int = 50


class AlertCountsResponse(BaseModel):
    """Alert counts by severity"""
    total: int
    unresolved: int
    low: int
    medium: int
    high: int
    critical: int


class HealthStatusEnum(str, Enum):
    """Health status levels"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class HealthCheckDetail(BaseModel):
    """Individual health check result"""
    status: str
    latency_ms: Optional[float] = None
    message: Optional[str] = None
    error: Optional[str] = None
    total_mb: Optional[float] = None
    used_mb: Optional[float] = None
    available_mb: Optional[float] = None
    percent_available: Optional[float] = None
    total_gb: Optional[float] = None
    used_gb: Optional[float] = None
    free_gb: Optional[float] = None
    percent_free: Optional[float] = None


class SystemInfo(BaseModel):
    """System information"""
    cpu_percent: float
    cpu_count: int
    load_average: Dict[str, float]
    uptime_seconds: int
    boot_time: str


class HealthCheckResponse(BaseModel):
    """Health check response"""
    status: str
    timestamp: str
    checks: Optional[Dict[str, HealthCheckDetail]] = None
    system: Optional[SystemInfo] = None


class MetricDataPoint(BaseModel):
    """Single metric data point"""
    timestamp: datetime
    value: float
    labels: Optional[Dict[str, str]] = None


class DashboardStats(BaseModel):
    """Statistics for monitoring dashboard"""
    total_requests_24h: int = 0
    failed_requests_24h: int = 0
    avg_response_time_ms: float = 0.0
    active_sessions: int = 0
    failed_logins_1h: int = 0
    alerts_unresolved: int = 0
    alerts_critical: int = 0
    alerts_high: int = 0
    system_status: str = "healthy"
    database_status: str = "healthy"
    redis_status: str = "healthy"


class LogEntry(BaseModel):
    """Log entry schema"""
    timestamp: datetime
    level: str
    logger: str
    message: str
    request_id: Optional[str] = None
    user_id: Optional[int] = None
    ip: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class LogListResponse(BaseModel):
    """Paginated log list"""
    logs: List[LogEntry]
    total: int
    page: int = 1
    per_page: int = 100


class ResolveAlertRequest(BaseModel):
    """Request to resolve an alert"""
    resolved_by: Optional[int] = None


class AlertFilterParams(BaseModel):
    """Parameters for filtering alerts"""
    severity: Optional[AlertSeveritySchema] = None
    alert_type: Optional[AlertTypeSchema] = None
    resolved: Optional[bool] = None
    hours: Optional[int] = None
    limit: int = Field(default=100, le=1000)
