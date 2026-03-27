import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.database import SessionLocal
from core.request_id_middleware import get_request_id


class DatabaseLogHandler(logging.Handler):
    """
    Обработчик логов для записи в базу данных
    """

    # ✅ TTL для разных уровней логов
    TTL_DAYS = {
        "DEBUG": 7,  # 7 дней
        "INFO": 30,  # 30 дней
        "WARNING": 90,  # 3 месяца
        "ERROR": 180,  # 6 месяцев
        "CRITICAL": 365,  # 1 год
    }

    def __init__(self):
        super().__init__()
        self._disabled_until = 0.0
        self._failure_cooldown_sec = 60

    @staticmethod
    def _is_safe_user_id(value):
        if hasattr(value, "expression") or hasattr(value, "property"):
            return None
        return value

    def _parse_record_payload(self, record) -> dict:
        if not isinstance(record.msg, dict):
            return {
                "event": "log_message",
                "message": str(record.msg),
                "user_id": None,
                "user_email": None,
                "ip_address": None,
                "user_agent_str": None,
                "http_method": None,
                "http_path": None,
                "http_status": None,
                "duration_ms": None,
                "trace_id": None,
                "extra_data": {},
            }

        msg = record.msg
        http_status_raw = msg.get("status")
        http_status = http_status_raw if isinstance(http_status_raw, int) else None

        excluded_keys = {
            "event",
            "message",
            "user_id",
            "email",
            "ip",
            "user_agent",
            "method",
            "path",
            "status",
            "duration_ms",
            "request_id",
            "trace_id",
        }

        extra_data = {
            k: v
            for k, v in msg.items()
            if k not in excluded_keys and not (k == "status" and isinstance(v, int))
        }

        return {
            "event": msg.get("event", "unknown"),
            "message": msg.get("message"),
            "user_id": self._is_safe_user_id(msg.get("user_id")),
            "user_email": msg.get("email"),
            "ip_address": msg.get("ip"),
            "user_agent_str": msg.get("user_agent"),
            "http_method": msg.get("method"),
            "http_path": msg.get("path"),
            "http_status": http_status,
            "duration_ms": msg.get("duration_ms"),
            "trace_id": msg.get("trace_id"),
            "extra_data": extra_data,
        }

    @staticmethod
    def _expires_at(level_name: str) -> datetime:
        ttl_days = DatabaseLogHandler.TTL_DAYS.get(level_name, 30)
        return datetime.now(timezone.utc) + timedelta(days=ttl_days)

    def emit(self, record):
        """Записываем лог в БД"""
        if time.monotonic() < self._disabled_until:
            return

        try:
            from modules.admin.models import AuditLog, LogLevel

            db: Session = SessionLocal()

            try:
                # Fail-fast для проблемных соединений/долгих запросов в логгер.
                db.execute(text("SET LOCAL statement_timeout = '2000ms'"))

                # ✅ Получаем request_id из context
                request_id = get_request_id()
                payload = self._parse_record_payload(record)

                # ✅ Получаем или создаём User-Agent
                user_agent_id = None
                if payload["user_agent_str"]:
                    user_agent_id = self._get_or_create_user_agent(
                        db,
                        payload["user_agent_str"],
                    )

                # Создаём запись лога
                log_entry = AuditLog(
                    request_id=request_id,
                    trace_id=payload["trace_id"],
                    level=LogLevel[record.levelname],
                    event=payload["event"],
                    message=payload["message"],
                    extra_data=payload["extra_data"],
                    user_id=payload["user_id"],
                    user_email=payload["user_email"],
                    ip_address=payload["ip_address"],
                    user_agent_id=user_agent_id,
                    http_method=payload["http_method"],
                    http_path=payload["http_path"],
                    http_status=payload["http_status"],
                    duration_ms=payload["duration_ms"],
                    expires_at=self._expires_at(record.levelname),
                )

                db.add(log_entry)
                db.commit()
            except (
                SQLAlchemyError,
                ValueError,
                TypeError,
                KeyError,
                IndexError,
            ) as e:
                import sys

                print(f"Ошибка записи в базу данных: {e}", file=sys.stderr)
                try:
                    db.rollback()
                except SQLAlchemyError:
                    pass
                self._disabled_until = time.monotonic() + self._failure_cooldown_sec
            finally:
                try:
                    db.close()
                except SQLAlchemyError:
                    pass

        except (ImportError, SQLAlchemyError, ValueError, TypeError) as e:
            print(f"Ошибка в DatabaseLogHandler: {e}")

    def _get_or_create_user_agent(
        self,
        db: Session,
        user_agent_str: str,
    ) -> int:
        """Получить или создать User-Agent в кеше"""
        from modules.admin.models import UserAgentCache

        # Ограничиваем длину до 1000 символов
        user_agent_str = user_agent_str[:1000]

        # Ищем существующий
        ua = (
            db.query(UserAgentCache)
            .filter(UserAgentCache.user_agent == user_agent_str)
            .first()
        )

        if ua:
            # Не коммитим здесь отдельно: минимизируем транзакции в emit().
            return ua.id

        new_ua = UserAgentCache(user_agent=user_agent_str)
        db.add(new_ua)
        db.flush()
        return new_ua.id
