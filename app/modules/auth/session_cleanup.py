from datetime import datetime, timezone
from sqlalchemy.orm import Session
from core.database import SessionLocal
from modules.auth.models import Session as SessionModel
import logging

logger = logging.getLogger("app")

def cleanup_expired_sessions():
    db: Session = SessionLocal()
    try:
        result = db.query(SessionModel).filter(
            SessionModel.expires_at < datetime.now(timezone.utc)
        ).delete(synchronize_session=False)

        db.commit()

        if result > 0:
            logger.info(f"Expired sessions cleaned: {result}")

    except Exception as e:
        logger.error(f"Error cleaning expired sessions: {e}")
    finally:
        db.close()
