from typing import Optional
from sqlalchemy.orm import Session
from modules.monitoring.models import Alert, AlertSeverity, AlertType
from modules.monitoring.repository import AlertRepository
from sqlalchemy import func, case

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
        limit: int = 50,
        page: int = 1,
        severity: Optional[AlertSeverity] = None,
        alert_type: Optional[AlertType] = None,
        resolved: Optional[bool] = None,
        hours: Optional[int] = None
    ):
        
        query = db.query(Alert)

        if severity:
            query = query.filter(Alert.severity == severity)

        if alert_type:
            query = query.filter(Alert.type == alert_type)

        if resolved is not None:
            query = query.filter(Alert.resolved == resolved)

        if hours:
            from datetime import datetime, timedelta
            since = datetime.utcnow() - timedelta(hours=hours)
            query = query.filter(Alert.timestamp >= since)

        total = query.count()

        alerts = (
            query.order_by(Alert.timestamp.desc())
                .offset((page - 1) * limit)
                .limit(limit)
                .all()
        )

        return alerts, total

    @staticmethod
    def resolve_alert(db: Session, alert_id: int, resolved_by: int | None):
        return AlertRepository.resolve(db, alert_id, resolved_by)
    
    
    from sqlalchemy import case, func
    from sqlalchemy.orm import Session

    @staticmethod
    def get_alert_counts(db: Session):
        counts = db.query(
            func.count(Alert.id).label("total"),
            func.sum(
                case(
                    (Alert.resolved == False, 1),
                    else_=0,
                )
            ).label("unresolved"),
            func.sum(
                case(
                    (Alert.severity == AlertSeverity.LOW, 1),
                    else_=0,
                )
            ).label("low"),
            func.sum(
                case(
                    (Alert.severity == AlertSeverity.MEDIUM, 1),
                    else_=0,
                )
            ).label("medium"),
            func.sum(
                case(
                    (Alert.severity == AlertSeverity.HIGH, 1),
                    else_=0,
                )
            ).label("high"),
            func.sum(
                case(
                    (Alert.severity == AlertSeverity.CRITICAL, 1),
                    else_=0,
                )
            ).label("critical"),
        ).one()

        return {
            "total": counts.total,
            "unresolved": counts.unresolved,
            "low": counts.low,
            "medium": counts.medium,
            "high": counts.high,
            "critical": counts.critical,
        }

