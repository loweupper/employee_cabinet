from sqlalchemy.orm import Session
from datetime import datetime
from core.database import SessionLocal
from modules.admin.models import AuditLog
import logging

logger = logging.getLogger("app")


def cleanup_expired_logs():
    """
    Удаляет или архивирует просроченные логи
    """
    db: Session = SessionLocal()
    
    try:
        now = datetime.utcnow()
        
        # # ✅ Вариант 1: Удалить просроченные
        # deleted_count = db.query(AuditLog).filter(
        #     AuditLog.expires_at <= now,
        #     AuditLog.is_archived == False
        # ).delete(synchronize_session=False)
        
        # ✅ Вариант 2: Пометить как архивные (soft delete)
        archived_count = db.query(AuditLog).filter(
            AuditLog.expires_at <= now,
            AuditLog.is_archived == False
        ).update({"is_archived": True}, synchronize_session=False)
        
        db.commit()
        
        logger.info({
            "event": "log_cleanup",
            "deleted_count": archived_count,
            "timestamp": now.isoformat()
        })
        
        return archived_count
        
    except Exception as e:
        db.rollback()
        logger.error({
            "event": "log_cleanup_error",
            "error": str(e)
        })
        return 0
    finally:
        db.close()


# ✅ Для запуска через APScheduler
if __name__ == "__main__":
    cleanup_expired_logs()