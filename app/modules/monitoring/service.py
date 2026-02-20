"""
Service layer for monitoring functionality (SQL-only version)
"""

import json
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session
from sqlalchemy import func

from core.database import SessionLocal
from modules.monitoring.service_alerts import AlertService
from modules.monitoring.models import Alert, AlertSeverity, AlertType
from core.monitoring.health import check_health
from modules.auth.models import Session as SessionModel
from modules.monitoring.schemas import (
    AlertResponse, AlertCountsResponse, DashboardStats,
    LogEntry, HealthCheckResponse
)

logger = logging.getLogger("app")


class MonitoringService:
    """Service for monitoring operations (SQL only)"""

    # ---------------------------------------------------------
    # DASHBOARD STATS
    # ---------------------------------------------------------
    @staticmethod
    async def get_dashboard_stats(db: Session) -> DashboardStats:
        stats = DashboardStats()

        try:
            # 1. SQL alert counts
            alert_counts = AlertService.get_alert_counts(db)
            stats.alerts_unresolved = alert_counts.get("unresolved", 0)
            stats.alerts_critical = alert_counts.get("critical", 0)
            stats.alerts_high = alert_counts.get("high", 0)

            # 2. Active sessions
            active_sessions = db.query(SessionModel).filter(
                SessionModel.is_revoked == False,
                SessionModel.expires_at > datetime.utcnow()
            ).count()
            stats.active_sessions = active_sessions

            # 3. Failed logins in last hour (SQL)
            failed_alerts = AlertService.get_alerts(
                db=db,
                hours=1,
                alert_type=AlertType.MULTIPLE_FAILED_LOGINS
            )
            stats.failed_logins_1h = len(failed_alerts)

            # 4. System health
            health = await check_health(detailed=False)
            stats.system_status = health.get("status", "unknown")

        except Exception as e:
            logger.error(f"Error getting dashboard stats: {e}")

        return stats

    # ---------------------------------------------------------
    # ALERTS (SQL)
    # ---------------------------------------------------------
    @staticmethod
    async def get_alerts(
        limit: int = 100,
        severity: Optional[AlertSeverity] = None,
        alert_type: Optional[AlertType] = None,
        resolved: Optional[bool] = None,
        hours: Optional[int] = None
    ):
        db = SessionLocal()
        try:
            return AlertService.get_alerts(
                db=db,
                limit=limit,
                severity=severity,
                alert_type=alert_type,
                resolved=resolved,
                hours=hours
            )
        finally:
            db.close()

    @staticmethod
    async def get_alert_by_id(alert_id: int, db: Session) -> Optional[Alert]:
        return db.query(Alert).filter(Alert.id == alert_id).first()

    @staticmethod
    async def resolve_alert(alert_id: int, resolved_by: Optional[int], db: Session) -> bool:
        return AlertService.resolve_alert(db, alert_id, resolved_by)

    @staticmethod
    async def get_alert_counts(db: Session) -> AlertCountsResponse:
        counts = AlertService.get_alert_counts(db)
        return AlertCountsResponse(**counts)

    # ---------------------------------------------------------
    # LOGS
    # ---------------------------------------------------------
    @staticmethod
    def get_recent_logs(
        log_file: str = "logs/app.log",
        limit: int = 100,
        level: Optional[str] = None,
        search: Optional[str] = None
    ) -> List[LogEntry]:

        logs = []
        log_path = Path(log_file)

        if not log_path.exists():
            logger.warning(f"Log file not found: {log_file}")
            return logs

        try:
            with open(log_path, "r") as f:
                lines = f.readlines()[-1000:]

            for line in reversed(lines):
                try:
                    log_data = json.loads(line.strip())

                    if level and log_data.get("level") != level:
                        continue

                    if search and search.lower() not in json.dumps(log_data).lower():
                        continue

                    log_entry = LogEntry(
                        timestamp=datetime.fromisoformat(
                            log_data.get("timestamp", datetime.utcnow().isoformat())
                        ),
                        level=log_data.get("level", "INFO"),
                        logger=log_data.get("logger", "unknown"),
                        message=log_data.get("message", log_data.get("event", "")),
                        request_id=log_data.get("request_id"),
                        user_id=log_data.get("user_id"),
                        ip=log_data.get("ip"),
                        details=log_data
                    )
                    logs.append(log_entry)

                    if len(logs) >= limit:
                        break

                except Exception:
                    continue

        except Exception as e:
            logger.error(f"Error reading logs: {e}")

        return logs

    @staticmethod
    async def get_security_logs(limit: int = 100) -> List[LogEntry]:
        return MonitoringService.get_recent_logs(
            log_file="logs/security.log",
            limit=limit
        )

    # ---------------------------------------------------------
    # SYSTEM HEALTH
    # ---------------------------------------------------------
    @staticmethod
    async def get_system_health(detailed: bool = False) -> Dict[str, Any]:
        return await check_health(detailed=detailed)
