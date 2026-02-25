from sqlalchemy.orm import Session
from sqlalchemy import desc
from modules.monitoring.models import Alert


class AlertRepository:

    @staticmethod
    def create(db: Session, alert: Alert) -> Alert:
        db.add(alert)
        db.commit()
        db.refresh(alert)
        return alert

    @staticmethod
    def get_by_id(db: Session, alert_id: int) -> Alert | None:
        return db.query(Alert).filter(Alert.id == alert_id).first()

    @staticmethod
    def get_recent(
        db: Session,
        limit: int = 100,
        severity=None,
        alert_type=None,
        resolved=None,
        hours=None
    ):
        q = db.query(Alert)

        if severity:
            q = q.filter(Alert.severity == severity)

        if alert_type:
            q = q.filter(Alert.type == alert_type)

        if resolved is not None:
            q = q.filter(Alert.resolved == resolved)

        if hours:
            from datetime import datetime, timedelta
            since = datetime.utcnow() - timedelta(hours=hours)
            q = q.filter(Alert.timestamp >= since)

        return q.order_by(desc(Alert.timestamp)).limit(limit).all()

    @staticmethod
    def resolve(db: Session, alert_id: str, resolved_by: int | None):
        alert = db.query(Alert).filter(Alert.id == alert_id).first()
        if not alert or alert.resolved:
            return False

        from datetime import datetime
        alert.resolved = True
        alert.resolved_at = datetime.utcnow()
        alert.resolved_by = resolved_by

        db.commit()
        return True
