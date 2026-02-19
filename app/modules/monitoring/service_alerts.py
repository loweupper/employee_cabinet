from typing import Optional
from sqlalchemy.orm import Session
from modules.monitoring.models import Alert, AlertSeverity, AlertType
from modules.monitoring.repository import AlertRepository


class AlertService:

    @staticmethod
    def create_alert(
        db: Session,
        severity: AlertSeverity,
        type: AlertType,
        message: str,
        user_id=None,
        ip_address=None,
        details=None
    ) -> Alert:
        alert = Alert(
            severity=severity,
            type=type,
            message=message,
            user_id=user_id,
            ip_address=ip_address,
            details=details
        )
        return AlertRepository.create(db, alert)

    @staticmethod
    def get_alerts(
        db: Session,
        limit: int = 100,
        severity: Optional[AlertSeverity] = None,
        alert_type: Optional[AlertType] = None,
        resolved: Optional[bool] = None,
        hours: Optional[int] = None
    ):
        
        return AlertRepository.get_recent(
            db=db, 
            limit=limit, 
            severity=severity, 
            alert_type=alert_type,
            resolved=resolved,
            hours=hours
        )

    @staticmethod
    def resolve_alert(db: Session, alert_id: int, resolved_by: int | None):
        return AlertRepository.resolve(db, alert_id, resolved_by)
