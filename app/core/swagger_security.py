from fastapi import Request, HTTPException, status, Depends
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from ipaddress import ip_address, ip_network
from typing import List
import logging
import secrets

from core.config import settings
from modules.auth.dependencies import get_current_user_from_cookie
from core.database import get_db

logger = logging.getLogger(__name__)
security = HTTPBasic()

def verify_swagger_auth(credentials: HTTPBasicCredentials = Depends(security)):
    """Basic Auth для Swagger (для staging)"""
    correct_username = secrets.compare_digest(credentials.username, "admin")
    correct_password = secrets.compare_digest(credentials.password, "888791Qazwsx")
    
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверные учетные данные для доступа к документации",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


class SwaggerSecurityMiddleware(BaseHTTPMiddleware):
    """
    Middleware для защиты Swagger UI:
    1. Проверка IP-адреса (белый список)
    2. Проверка авторизации (только admin)
    """
    
    SWAGGER_PATHS = ["/docs", "/redoc", "/openapi.json"]
    
    def __init__(self, app, allowed_ips: List[str] = None):
        super().__init__(app)
        self.allowed_ips = allowed_ips or []
    
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        
        # Пропускаем все запросы, кроме Swagger
        if not any(path.startswith(swagger_path) for swagger_path in self.SWAGGER_PATHS):
            return await call_next(request)
        
        # ✅ 1. Проверка: документация включена?
        if not settings.ENABLE_DOCS:
            logger.warning({
                "event": "swagger_access_denied",
                "reason": "docs_disabled",
                "ip": request.client.host,
                "path": path
            })
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"detail": "Документация отключена в продакшене"}
            )
        
        # ✅ 2. Проверка IP-адреса (если настроен белый список)
        if self.allowed_ips:
            client_ip = request.client.host
            if not self._is_ip_allowed(client_ip):
                logger.warning({
                    "event": "swagger_access_denied",
                    "reason": "ip_not_allowed",
                    "ip": client_ip,
                    "path": path
                })
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": f"Доступ запрещен: IP {client_ip} не в белом списке"}
                )
        
        # ✅ 3. Проверка авторизации (только admin)
        if settings.DOCS_REQUIRE_AUTH:
            try:
                # Получаем токен из cookie
                access_token = request.cookies.get("access_token")
                
                if not access_token:
                    logger.warning({
                        "event": "swagger_access_denied",
                        "reason": "no_token",
                        "ip": request.client.host,
                        "path": path
                    })
                    return JSONResponse(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        content={
                            "detail": "Требуется аутентификация. Пожалуйста, войдите в систему на /auth/login-page"
                        }
                    )
                
                # Проверяем пользователя
                from modules.auth.utils import decode_token
                from modules.auth.models import User, UserRole
                from sqlalchemy.orm import Session
                
                db: Session = next(get_db())
                try:
                    payload = decode_token(access_token)
                    user_id = payload.get("sub")
                    
                    user = db.query(User).filter(User.id == user_id).first()
                    
                    if not user:
                        raise HTTPException(status_code=401, detail="User not found")
                    
                    if not user.is_active:
                        raise HTTPException(status_code=403, detail="User is inactive")
                    
                    # ✅ Проверка: только admin
                    if user.role != UserRole.ADMIN:
                        logger.warning({
                            "event": "swagger_access_denied",
                            "reason": "not_admin",
                            "user_id": user.id,
                            "role": user.role.value,
                            "ip": request.client.host,
                            "path": path
                        })
                        return JSONResponse(
                            status_code=status.HTTP_403_FORBIDDEN,
                            content={"detail": "Доступ к документации разрешен только для администраторов"}
                        )
                    
                    # ✅ Логируем доступ
                    logger.info({
                        "event": "Доступ к Swagger UI разрешен",
                        "user_id": user.id,
                        "email": user.email,
                        "ip": request.client.host,
                        "path": path
                    })
                    
                finally:
                    db.close()
                
            except Exception as e:
                logger.error({
                    "event": "swagger_auth_error",
                    "error": str(e),
                    "ip": request.client.host,
                    "path": path
                })
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Неверный или истекший токен. Пожалуйста, войдите в систему на /auth/login-page"}
                )
        
        # ✅ Все проверки пройдены
        return await call_next(request)
    
    def _is_ip_allowed(self, client_ip: str) -> bool:
        """Проверка IP-адреса по белому списку"""
        try:
            client_ip_obj = ip_address(client_ip)
            
            for allowed_ip in self.allowed_ips:
                # Поддержка CIDR (например, 192.168.0.0/24)
                if "/" in allowed_ip:
                    if client_ip_obj in ip_network(allowed_ip, strict=False):
                        return True
                else:
                    if str(client_ip_obj) == allowed_ip:
                        return True
            
            return False
        except Exception as e:
            logger.error(f"Ошибка проверки IP: {e}")
            return False