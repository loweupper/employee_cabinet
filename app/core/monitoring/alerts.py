"""
Security alert management system with severity levels and in-memory storage
"""
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from collections import deque
import uuid
import logging
import asyncio

logger = logging.getLogger("app")


class AlertSeverity(str, Enum):
    """Уровни критичности для оповещений безопасности"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertType(str, Enum):
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


@dataclass
class Alert:
    """Security alert data structure"""
    id: str
    timestamp: datetime
    severity: AlertSeverity
    type: AlertType
    message: str
    user_id: Optional[int]
    ip_address: str
    details: Dict
    resolved: bool = False
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[int] = None


class AlertManager:
    """
    Manages security alerts with in-memory storage
    Keeps last 1000 alerts or 24 hours, whichever is reached first
    """
    
    def __init__(self, max_alerts: int = 1000, retention_hours: int = 24):
        """
        Initialize alert manager
        
        Args:
            max_alerts: Maximum number of alerts to keep in memory
            retention_hours: Hours to retain alerts
        """
        self.max_alerts = max_alerts
        self.retention_hours = retention_hours
        self.alerts: deque = deque(maxlen=max_alerts)
        self._lock = asyncio.Lock()
        
        logger.info(f"AlertManager initialized: max_alerts={max_alerts}, retention_hours={retention_hours}")
    
    async def create_alert(
        self,
        severity: AlertSeverity,
        alert_type: AlertType,
        message: str,
        user_id: Optional[int],
        ip_address: str,
        details: Dict
    ) -> Alert:
        """
        Create and store a new security alert
        
        Args:
            severity: Alert severity level
            alert_type: Type of alert
            message: Human-readable alert message
            user_id: Optional user ID associated with alert
            ip_address: IP address where event occurred
            details: Additional context about the alert
            
        Returns:
            Created Alert object
        """
        alert = Alert(
            id=str(uuid.uuid4()),
            timestamp=datetime.utcnow(),
            severity=severity,
            type=alert_type,
            message=message,
            user_id=user_id,
            ip_address=ip_address,
            details=details
        )
        
        async with self._lock:
            self.alerts.append(alert)
            self._cleanup_old_alerts()
        
        # Log alert creation
        logger.warning({
            "event": "security_alert_created",
            "alert_id": alert.id,
            "severity": severity.value,
            "type": alert_type.value,
            "message": message,
            "user_id": user_id,
            "ip_address": ip_address,
            "details": details
        })
        
        # Record metric
        from core.monitoring.metrics import record_security_event
        record_security_event(alert_type.value)
        
        return alert
    
    async def get_recent_alerts(
        self,
        limit: int = 100,
        severity: Optional[AlertSeverity] = None,
        alert_type: Optional[AlertType] = None,
        resolved: Optional[bool] = None,
        hours: Optional[int] = None
    ) -> List[Alert]:
        """
        Get recent alerts with optional filtering
        
        Args:
            limit: Maximum number of alerts to return
            severity: Filter by severity level
            alert_type: Filter by alert type
            resolved: Filter by resolution status
            hours: Only return alerts from last N hours
            
        Returns:
            List of filtered alerts, newest first
        """
        async with self._lock:
            alerts = list(self.alerts)
        
        # Apply filters
        if hours:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            alerts = [a for a in alerts if a.timestamp >= cutoff]
        
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        
        if alert_type:
            alerts = [a for a in alerts if a.type == alert_type]
        
        if resolved is not None:
            alerts = [a for a in alerts if a.resolved == resolved]
        
        # Sort by timestamp descending (newest first)
        alerts.sort(key=lambda a: a.timestamp, reverse=True)
        
        return alerts[:limit]
    
    async def get_alert_by_id(self, alert_id: str) -> Optional[Alert]:
        """
        Get a specific alert by ID
        
        Args:
            alert_id: Alert ID to find
            
        Returns:
            Alert if found, None otherwise
        """
        async with self._lock:
            for alert in self.alerts:
                if alert.id == alert_id:
                    return alert
        return None
    
    async def resolve_alert(self, alert_id: str, resolved_by: Optional[int] = None) -> bool:
        """
        Mark an alert as resolved
        
        Args:
            alert_id: Alert ID to resolve
            resolved_by: Optional user ID who resolved the alert
            
        Returns:
            True if alert was found and resolved, False otherwise
        """
        async with self._lock:
            for alert in self.alerts:
                if alert.id == alert_id and not alert.resolved:
                    alert.resolved = True
                    alert.resolved_at = datetime.utcnow()
                    alert.resolved_by = resolved_by
                    
                    logger.info({
                        "event": "alert_resolved",
                        "alert_id": alert_id,
                        "resolved_by": resolved_by,
                        "alert_type": alert.type.value
                    })
                    return True
        return False
    
    async def get_alert_counts(self) -> Dict[str, int]:
        """
        Get counts of alerts by severity
        
        Returns:
            Dictionary with counts by severity level
        """
        async with self._lock:
            counts = {
                "total": len(self.alerts),
                "unresolved": sum(1 for a in self.alerts if not a.resolved),
                "low": sum(1 for a in self.alerts if a.severity == AlertSeverity.LOW and not a.resolved),
                "medium": sum(1 for a in self.alerts if a.severity == AlertSeverity.MEDIUM and not a.resolved),
                "high": sum(1 for a in self.alerts if a.severity == AlertSeverity.HIGH and not a.resolved),
                "critical": sum(1 for a in self.alerts if a.severity == AlertSeverity.CRITICAL and not a.resolved),
            }
        return counts
    
    def _cleanup_old_alerts(self):
        """Remove alerts older than retention period"""
        cutoff = datetime.utcnow() - timedelta(hours=self.retention_hours)
        
        # Remove from the left (oldest) while they're too old
        while self.alerts and self.alerts[0].timestamp < cutoff:
            removed = self.alerts.popleft()
            logger.debug(f"Removed old alert: {removed.id} from {removed.timestamp}")


# Global alert manager instance
alert_manager = AlertManager()


# Convenience functions
async def create_alert(
    severity: AlertSeverity,
    alert_type: AlertType,
    message: str,
    user_id: Optional[int],
    ip_address: str,
    details: Dict
) -> Alert:
    """Create a new security alert"""
    return await alert_manager.create_alert(
        severity, alert_type, message, user_id, ip_address, details
    )


async def get_recent_alerts(
    limit: int = 100,
    severity: Optional[AlertSeverity] = None,
    alert_type: Optional[AlertType] = None,
    resolved: Optional[bool] = None,
    hours: Optional[int] = None
) -> List[Alert]:
    """Get recent alerts with filtering"""
    return await alert_manager.get_recent_alerts(
        limit, severity, alert_type, resolved, hours
    )


async def resolve_alert(alert_id: str, resolved_by: int = None) -> bool:
    """Resolve an alert"""
    return await alert_manager.resolve_alert(alert_id, resolved_by)


async def get_alert_counts() -> Dict[str, int]:
    """Get alert counts by severity"""
    return await alert_manager.get_alert_counts()
