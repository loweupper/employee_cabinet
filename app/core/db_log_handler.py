from asyncio.log import logger
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from core.database import SessionLocal
from core.request_id_middleware import get_request_id


class DatabaseLogHandler(logging.Handler):
    """
    Обработчик логов для записи в базу данных
    """
    
    # ✅ TTL для разных уровней логов
    TTL_DAYS = {
        "DEBUG": 7,      # 7 дней
        "INFO": 30,      # 30 дней
        "WARNING": 90,   # 3 месяца
        "ERROR": 180,    # 6 месяцев
        "CRITICAL": 365, # 1 год
    }
    
    def emit(self, record):
        """Записываем лог в БД"""
        try:
            from modules.admin.models import AuditLog, LogLevel
            
            db: Session = SessionLocal()
            
            try:
                # ✅ Получаем request_id из context
                request_id = get_request_id()
                
                # Парсим сообщение и извлекаем данные
                if isinstance(record.msg, dict):
                    event = record.msg.get("event", "unknown")
                    message = record.msg.get("message", None)
                    user_id = record.msg.get("user_id", None)
                    # Защита от ORM-атрибутов
                    if hasattr(user_id, "expression") or hasattr(user_id, "property"):
                        user_id = None
                    user_email = record.msg.get("email", None)
                    ip_address = record.msg.get("ip", None)
                    user_agent_str = record.msg.get("user_agent", None)
                    http_method = record.msg.get("method", None)
                    http_path = record.msg.get("path", None)
                    http_status_raw = record.msg.get("status", None)
                    if http_status_raw is not None and isinstance(http_status_raw, int):
                        http_status = http_status_raw
                    else:
                        http_status = None
                    duration_ms = record.msg.get("duration_ms", None)
                    trace_id = record.msg.get("trace_id", None)
                    
                    # Остальные данные в extra_data
                    extra_data = {}
                    logger.debug(f"Parsed log record: event={event}, user_id={user_id}, ip={ip_address}, user_agent={user_agent_str}, http_method={http_method}, http_path={http_path}, http_status={http_status}, duration_ms={duration_ms}, trace_id={trace_id}")
                    # Parse message
                    if isinstance(record.msg, dict):
                        extra_data = {k: v for k, v in record.msg.items() 
                                      if k not in ["event", "message", "user_id", "email", "ip", 
                                                 "user_agent", "method", "path", "status", "duration_ms", 
                                                 "request_id", "trace_id"]
                                      and not (k == "status" and isinstance(v, int))}
                        logger.debug(f"Extracted extra_data for log: {extra_data}")

                else:
                    event = "log_message"
                    message = str(record.msg)
                    user_id = None
                    user_email = None
                    ip_address = None
                    user_agent_str = None
                    http_method = None
                    http_path = None
                    http_status = None
                    duration_ms = None
                    trace_id = None
                    extra_data = extra_data or None
                
                # ✅ Получаем или создаём User-Agent
                user_agent_id = None
                if user_agent_str:
                    user_agent_id = self._get_or_create_user_agent(db, user_agent_str)
                
                # ✅ Вычисляем expires_at на основе TTL
                ttl_days = self.TTL_DAYS.get(record.levelname, 30)
                expires_at = datetime.utcnow() + timedelta(days=ttl_days)
                
                # Создаём запись лога
                log_entry = AuditLog(
                    request_id=request_id,
                    trace_id=trace_id,
                    level=LogLevel[record.levelname],
                    event=event,
                    message=message,
                    extra_data=extra_data,
                    user_id=user_id,
                    user_email=user_email,
                    ip_address=ip_address,
                    user_agent_id=user_agent_id,
                    http_method=http_method,
                    http_path=http_path,
                    http_status=http_status,
                    duration_ms=duration_ms,
                    expires_at=expires_at,
                )
                
                db.add(log_entry)
                db.commit()
            except Exception as e:
                import sys
                print(f"Failed to write log to database: {e}", file=sys.stderr)
                try:
                    db.rollback()
                except:
                    pass
                finally:
                    db.close()
                
        except Exception as e:
            print(f"Ошибка в DatabaseLogHandler: {e}")
    
    def _get_or_create_user_agent(self, db: Session, user_agent_str: str) -> int:
        """Получить или создать User-Agent в кеше"""
        from modules.admin.models import UserAgentCache
        
        # Ограничиваем длину до 1000 символов
        user_agent_str = user_agent_str[:1000]
        
        # Ищем существующий
        ua = db.query(UserAgentCache).filter(
            UserAgentCache.user_agent == user_agent_str
        ).first()
        
        if ua:
            # Увеличиваем счётчик
            ua.usage_count += 1
            ua.last_seen = datetime.utcnow()
            return ua.id
        else:
            # Создаём новый
            new_ua = UserAgentCache(user_agent=user_agent_str)
            db.add(new_ua)
            return new_ua.id