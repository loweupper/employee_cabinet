import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import contextvars

# ✅ Context variable для хранения request_id в пределах одного запроса
request_id_ctx = contextvars.ContextVar('request_id', default=None)

class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware для генерации уникального request_id для каждого запроса
    """
    
    async def dispatch(self, request: Request, call_next):
        # Генерируем или получаем request_id из заголовка
        request_id = request.headers.get('X-Request-ID', str(uuid.uuid4()))
        
        # Сохраняем в context variable
        request_id_ctx.set(request_id)
        
        # Добавляем в state запроса
        request.state.request_id = request_id
        
        # Выполняем запрос
        response = await call_next(request)
        
        # Добавляем request_id в заголовок ответа
        response.headers['X-Request-ID'] = request_id
        
        return response


def get_request_id() -> str:
    """Получить текущий request_id"""
    return request_id_ctx.get()