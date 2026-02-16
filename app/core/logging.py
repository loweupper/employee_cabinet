import time
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from jose import jwt, JWTError
from core.config import settings

logger = logging.getLogger("app")


class AccessLogMiddleware(BaseHTTPMiddleware):
    """
    Middleware для логирования всех HTTP запросов в структурированном виде
    Логи будут обогащены данными из запроса и сохранены в базу данных через DatabaseLogHandler
    """
    async def dispatch(self, request: Request, call_next):
        start = time.time()

        # ✅ Получаем request_id из context (уже установлен в RequestIDMiddleware)
        request_id = getattr(request.state, "request_id", None)

        # IP клиента
        client_ip = request.client.host if request.client else "unknown"

        # User-Agent
        user_agent = request.headers.get("user-agent", "-")

        # ✅ Попытка получить user_id (если авторизован)
        user_id = None
        user_email = None

        # Сначала пробуем из cookie, потом из Authorization header
        token = request.cookies.get("access_token")
        if not token:
            auth_header = request.headers.get("authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]
        
        if token:
            try:
                payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
                user_id = payload.get("sub")
                user_email = payload.get("email")
            except JWTError:
                pass
        
        try:
            # Выполняем запрос
            response = await call_next(request)
            duration = round((time.time() - start) * 1000, 2)

            # Логируем успешный запрос
            logger.info({
                "event": "http_request",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration,
                "ip": client_ip,
                "user_agent": user_agent,
                "user_id": int(user_id) if user_id else None,
                "email": user_email,
            })
            
            # Record metrics
            try:
                from core.monitoring.metrics import record_request
                record_request(
                    method=request.method,
                    endpoint=request.url.path,
                    status_code=response.status_code,
                    duration=duration / 1000  # Convert ms to seconds
                )
            except Exception as metric_error:
                # Don't let metrics errors break the request
                logger.debug(f"Failed to record metrics: {metric_error}")

            # ✅ Добавляем request_id в headers для трейсинга
            if request_id:
                response.headers["X-Request-ID"] = request_id

            return response
        
        except Exception as e:
            duration = round((time.time() - start) * 1000, 2)
            
            # ✅ Логируем ошибку
            logger.error({
                "event": "http_request_error",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "duration_ms": duration,
                "ip": client_ip,
                "user_agent": user_agent,
                "user_id": int(user_id) if user_id else None,
                "email": user_email,
                "error": str(e),
                "error_type": type(e).__name__,
            })
            
            # Прокидываем исключение дальше
            raise