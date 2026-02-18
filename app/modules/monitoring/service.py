"""
Service layer for monitoring functionality
"""
import json
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import func

from core.monitoring.alerts import alert_manager, Alert, AlertSeverity, AlertType
from core.monitoring.health import check_health
from modules.auth.models import Session as SessionModel
from modules.monitoring.schemas import (
    AlertResponse, AlertCountsResponse, DashboardStats,
    LogEntry, HealthCheckResponse
)

logger = logging.getLogger("app")


class MonitoringService:
    """Service for monitoring operations"""
    
    @staticmethod
    async def get_dashboard_stats(db: Session) -> DashboardStats:
        """
        Get aggregated statistics for dashboard
        
        Args:
            db: Database session
            
        Returns:
            Dashboard statistics
        """
        stats = DashboardStats()
        
        try:
            # Get alert counts
            alert_counts = await alert_manager.get_alert_counts()
            stats.alerts_unresolved = alert_counts.get('unresolved', 0)
            stats.alerts_critical = alert_counts.get('critical', 0)
            stats.alerts_high = alert_counts.get('high', 0)
            
            # Get active sessions count
            active_sessions = db.query(SessionModel).filter(
                SessionModel.is_revoked == False,
                SessionModel.expires_at > datetime.utcnow()
            ).count()
            stats.active_sessions = active_sessions
            
            # Update active sessions metric
            from core.monitoring.metrics import update_active_sessions
            update_active_sessions(active_sessions)
            
            # Get failed logins in last hour
            alerts = await alert_manager.get_recent_alerts(
                hours=1,
                alert_type=AlertType.MULTIPLE_FAILED_LOGINS
            )
            stats.failed_logins_1h = len(alerts)
            
            # Check system health
            health = await check_health(detailed=False)
            stats.system_status = health.get('status', 'unknown')
            
            # Note: Request metrics would come from Prometheus
            # For now, we'll leave them at 0
            
        except Exception as e:
            logger.error(f"Error getting dashboard stats: {e}")
        
        return stats
    
    @staticmethod
    async def get_alerts(
        limit: int = 100,
        severity: Optional[AlertSeverity] = None,
        alert_type: Optional[AlertType] = None,
        resolved: Optional[bool] = None,
        hours: Optional[int] = None
    ) -> List[Alert]:
        """
        Get alerts with filtering
        
        Args:
            limit: Maximum number of alerts
            severity: Filter by severity
            alert_type: Filter by type
            resolved: Filter by resolution status
            hours: Only alerts from last N hours
            
        Returns:
            List of alerts
        """
        return await alert_manager.get_recent_alerts(
            limit=limit,
            severity=severity,
            alert_type=alert_type,
            resolved=resolved,
            hours=hours
        )
    
    @staticmethod
    async def get_alert_by_id(alert_id: str) -> Optional[Alert]:
        """
        Get specific alert by ID
        
        Args:
            alert_id: Alert ID
            
        Returns:
            Alert object if found, None if not found
        """
        return await alert_manager.get_alert_by_id(alert_id)
    
    @staticmethod
    async def resolve_alert(alert_id: str, resolved_by: Optional[int] = None) -> bool:
        """
        Mark alert as resolved
        
        Args:
            alert_id: Alert ID to resolve
            resolved_by: User ID who resolved it
            
        Returns:
            True if resolved successfully
        """
        return await alert_manager.resolve_alert(alert_id, resolved_by)
    
    @staticmethod
    async def get_alert_counts() -> AlertCountsResponse:
        """
        Get alert counts by severity
        
        Returns:
            Alert counts
        """
        counts = await alert_manager.get_alert_counts()
        return AlertCountsResponse(**counts)
    
    @staticmethod
    def get_recent_logs(
        log_file: str = "logs/app.log",
        limit: int = 100,
        level: Optional[str] = None,
        search: Optional[str] = None
    ) -> List[LogEntry]:
        """
        Read recent logs from log file
        
        Args:
            log_file: Path to log file
            limit: Maximum number of log entries
            level: Filter by log level
            search: Search term in log message
            
        Returns:
            List of log entries
        """
        logs = []
        log_path = Path(log_file)
        
        if not log_path.exists():
            logger.warning(f"Log file not found: {log_file}")
            return logs
        
        try:
            # Read last N lines from file
            with open(log_path, 'r') as f:
                # Read last 1000 lines max to avoid memory issues
                lines = f.readlines()[-1000:]
            
            # Parse JSON logs
            for line in reversed(lines):  # Newest first
                try:
                    log_data = json.loads(line.strip())
                    
                    # Apply filters
                    if level and log_data.get('level') != level:
                        continue
                    
                    if search and search.lower() not in json.dumps(log_data).lower():
                        continue
                    
                    # Create log entry
                    log_entry = LogEntry(
                        timestamp=datetime.fromisoformat(log_data.get('timestamp', datetime.utcnow().isoformat())),
                        level=log_data.get('level', 'INFO'),
                        logger=log_data.get('logger', 'unknown'),
                        message=log_data.get('message', log_data.get('event', '')),
                        request_id=log_data.get('request_id'),
                        user_id=log_data.get('user_id'),
                        ip=log_data.get('ip'),
                        details=log_data
                    )
                    logs.append(log_entry)
                    
                    if len(logs) >= limit:
                        break
                        
                except json.JSONDecodeError:
                    # Skip non-JSON lines
                    continue
                except Exception as e:
                    logger.debug(f"Error parsing log line: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Error reading logs: {e}")
        
        return logs
    
    @staticmethod
    async def get_security_logs(limit: int = 100) -> List[LogEntry]:
        """
        Get recent security logs
        
        Args:
            limit: Maximum number of entries
            
        Returns:
            List of security log entries
        """
        return MonitoringService.get_recent_logs(
            log_file="logs/security.log",
            limit=limit
        )
    
    @staticmethod
    async def get_system_health(detailed: bool = False) -> Dict[str, Any]:
        """
        Get system health status
        
        Args:
            detailed: Return detailed health information
            
        Returns:
            Health status dictionary
        """
        return await check_health(detailed=detailed)
