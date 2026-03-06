from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from contextlib import asynccontextmanager
import logging
import logging.config
import json
from datetime import datetime
import pytz
import re
import asyncio
from modules.auth.session_cleanup import cleanup_expired_sessions
from modules.monitoring.models import Alert


from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette_csrf import CSRFMiddleware

from core.config import settings
from core.database import Base, engine
from core.logging.middleware import AccessLogMiddleware
from modules.auth.routes import router as auth_router
from modules.auth.dependencies import get_current_user_from_cookie
from modules.auth.models import Session, User
from modules.profile.routes import router as profile_router
from modules.objects.routes import router as object_router
from modules.documents.routes import router as documents_router
from modules.admin.routes import router as admin_router
from core.database import get_db
from core.template_helpers import get_sidebar_context
from core.swagger_security import SwaggerSecurityMiddleware
from core.request_id_middleware import RequestIDMiddleware
from core.db_log_handler import DatabaseLogHandler
from core.logging.handlers import setup_log_handlers

# ===================================
# JSON Logging for Production
# ===================================

class JsonFormatter(logging.Formatter):
    """Кастомный форматтер для структурированного JSON-логирования с Moscow timezone"""
    
    def format(self, record):
        # ✅ Конвертируем время в Moscow timezone
        moscow_tz = pytz.timezone('Europe/Moscow')
        dt = datetime.fromtimestamp(record.created, tz=pytz.utc)
        moscow_time = dt.astimezone(moscow_tz)
        
        log_data = {
            "time": moscow_time.strftime("%Y-%m-%d %H:%M:%S"),  # ✅ Moscow time
            "level": record.levelname,
            "logger": record.name,
        }
        
        # Если message — словарь, мержим его в корень
        if isinstance(record.msg, dict):
            log_data.update(record.msg)
        else:
            log_data["message"] = record.getMessage()
        
        # Добабляем exception, если есть
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data, ensure_ascii=False)


LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,

    "formatters": {
        "json": {
            "()": JsonFormatter,
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        },
    },

    "handlers": {
        "default": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "stream": "ext://sys.stdout",
        },
        "access": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "stream": "ext://sys.stdout",
        },
        "database": {
            "()": DatabaseLogHandler,
            "level": "INFO",
        },
    },

    "loggers": {
        "uvicorn": {
            "handlers": ["default"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn.access": {
            "handlers": ["access"],
            "level": "INFO",
            "propagate": False,
        },
        "app": {
            "handlers": ["default", "database"],
            "level": "DEBUG" if settings.DEBUG else "INFO",
            "propagate": True,
        },
        "audit": {
            "handlers": ["default", "database"],
            "level": "INFO",
            "propagate": True,
        },
        "system": {
            "handlers": ["default", "database"],
            "level": "INFO",
            "propagate": True,
        },
        "security": {
            "handlers": ["default", "database"],
            "level": "WARNING",
            "propagate": True,
        },
    },
}

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("app")

# ===================================
# Подключаем кастомные файловые хендлеры
# ===================================
file_handlers = setup_log_handlers(base_dir="/app/logs")

root_logger = logging.getLogger()

# Добавляем наши хендлеры
for h in file_handlers.values():
    root_logger.addHandler(h)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.debug({"event": "app_startup", "debug_mode": settings.DEBUG, "environment": settings.ENVIRONMENT})
    
    # Initialize monitoring components
    if settings.MONITORING_ENABLED:
        try:
            # Initialize login attempt tracker
            from core.redis import get_redis
            from core.monitoring.detector import init_login_tracker
            redis_client = await get_redis()
            await init_login_tracker(redis_client)
            logger.debug("Login attempt tracker initialized")
            
            # Initialize email notifier if configured
            if settings.SMTP_HOST and settings.SMTP_USER and settings.ALERT_EMAIL_RECIPIENTS:
                from core.notifications.email_notifier import init_email_notifier
                await init_email_notifier(
                    smtp_host=settings.SMTP_HOST,
                    smtp_port=settings.SMTP_PORT,
                    username=settings.SMTP_USER,
                    password=settings.SMTP_PASSWORD,
                    from_email=settings.SMTP_FROM_EMAIL,
                    from_name=settings.SMTP_FROM_NAME
                )
                logger.debug("Email notifier initialized")
            
            # Initialize Telegram notifier if configured
            if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID:
                from core.notifications.telegram_notifier import init_telegram_notifier
                await init_telegram_notifier(
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    chat_id=settings.TELEGRAM_CHAT_ID
                )
                logger.debug("Telegram notifier initialized")
                
        except Exception as e:
            logger.error(f"Failed to initialize monitoring components: {e}")
    
    yield
    logger.debug({"event": "app_shutdown"})


# ===================================
# FastAPI App с улучшенным Swagger
# ===================================
app = FastAPI(
    title="🏢 Employee Cabinet API",
    description="""
    ## Корпоративная система управления сотрудниками
    
    ### 🎯 Возможности:
    * 👤 **Аутентификация** — JWT токены, OTP, сессии
    * 👥 **Управление пользователями** — RBAC (Role-Based Access Control)
    * 🏢 **Объекты** — управление корпоративными объектами
    * 📄 **Документы** — загрузка и управление файлами
    * 👑 **Админ-панель** — полное управление системой
    
    ### 🔐 Как использовать аутентификацию:
    
    1. **Получите токен:**
       ```bash
       POST /api/v1/auth/login
       {
         "email": "admin@example.com",
         "password": "password"
       }
       ```
    
    2. **Скопируйте access_token из ответа**
    
    3. **Нажмите кнопку 🔒 Authorize вверху страницы**
    
    4. **Вставьте токен в формате:**
       ```
       Bearer YOUR_ACCESS_TOKEN_HERE
       ```
    
    5. **Нажмите Authorize и Close**
    
    6. **Теперь можете тестировать защищённые endpoints!**
    
    ---
    
    ### 👥 Роли пользователей:
    
    | Роль | Описание | Доступ |
    |------|----------|--------|
    | 👑 `admin` | Администратор | Полный доступ ко всем функциям |
    | 💰 `accountant` | Бухгалтер | Финансовые документы и отчёты |
    | 👔 `hr` | HR-менеджер | Управление персоналом |
    | 🔧 `engineer` | Инженер | Технические объекты |
    | ⚖️ `lawyer` | Юрист | Юридические документы |
    | 👤 `employee` | Сотрудник | Базовый доступ к своему профилю |
    
    ---
    
    ### 📊 Статусы объектов:
    * ✅ `active` — активный
    * 📦 `inactive` — неактивный
    * 🗄️ `archived` — архивный
    
    ### 📄 Статусы пользователей:
    * ✅ `active` — активный
    * ⏳ `pending` — ожидает активации
    * ⏸️ `deactivated` — деактивирован
    * 🗑️ `deleted` — удалён
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.ENABLE_DOCS else None,  # ✅ Отключается через .env
    redoc_url="/redoc" if settings.ENABLE_DOCS else None,
    openapi_url="/openapi.json" if settings.ENABLE_DOCS else None,
    terms_of_service="https://example.com/terms/",
    contact={
        "name": "IT Support",
        "url": "https://example.com/support",
        "email": "support@example.com",
    },
    license_info={
        "name": "Proprietary",
        "identifier": "Proprietary",
    },
)

# ===================================
# Кастомная OpenAPI схема с Bearer Auth
# ===================================
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title="🏢 Employee Cabinet API",
        version="1.0.0",
        description="Корпоративная система управления сотрудниками",
        routes=app.routes,
    )
    
    # ✅ Добавляем Bearer Token аутентификацию
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "🔑 Введите JWT ��окен в формате: Bearer YOUR_TOKEN"
        }
    }
    
    # ✅ Применяем глобальную аутентификацию
    openapi_schema["security"] = [{"BearerAuth": []}]
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# ===================================
# Rate Limiting Setup
# ===================================
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ===================================
# Templates & Static
# ===================================
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ===================================
# Middleware 
# ===================================

# ✅ Добавляем в обратном порядке выполнения:

# 5. CORS (выполнится первым)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_CREDENTIALS,
    allow_methods=settings.CORS_METHODS,
    allow_headers=settings.CORS_HEADERS,
)

# 4. CSRF Protection (выполнится вторым)
app.add_middleware(
    CSRFMiddleware,
    secret=settings.SECRET_KEY,
    cookie_name="csrftoken",
    cookie_secure=settings.ENVIRONMENT == "production",
    cookie_httponly=False,
    cookie_samesite="lax",
    header_name="X-CSRFToken",
    safe_methods={"GET", "HEAD", "OPTIONS", "TRACE"},
    exempt_urls=[
        re.compile(r"^/api/v1/auth/login$"),       # ✅ Regex pattern
        re.compile(r"^/api/v1/auth/register$"),    # ✅ Regex pattern
        re.compile(r"^/api/v1/auth/refresh$"),     # ✅ Regex pattern
        re.compile(r"^/health$"),                  # ✅ Regex pattern
        re.compile(r"^/docs.*"),                   # ✅ Regex pattern (все /docs/*)
        re.compile(r"^/openapi\.json$"),           # ✅ Regex pattern
        re.compile(r"^/redoc$"),                   # ✅ Regex pattern
        re.compile(r"^/admin/.*"),

        # ✅ ВАШИ ВЕБ-ЭНДПОИНТЫ ДЛЯ ОБЪЕКТОВ
        re.compile(r"^/objects/create$"),
        re.compile(r"^/objects/\d+/edit$"),
        re.compile(r"^/objects/\d+/access/grant$"),
        re.compile(r"^/objects/\d+/access/\d+/revoke$"),
        re.compile(r"^/objects/\d+/access/grant-department$"),
        re.compile(r"^/objects/\d+/access/\d+/update$"),
        re.compile(r"^/objects/\d+/delete$"),
        re.compile(r"^/objects/\d+/activate$"),
        re.compile(r"^/objects/\d+/deactivate$"),
        re.compile(r"^/objects/\d+/archive$"),
        re.compile(r"^/objects/\d+/unarchive$"),
        re.compile(r"^/objects/\d+/restore$"),
        re.compile(r"^/objects/\d+/subcategories/create$"),
        re.compile(r"^/objects/\d+/subcategories/\d+/update$"),
        re.compile(r"^/objects/\d+/subcategories/\d+/delete$"),

        # ✅ ДОКУМЕНТЫ
        re.compile(r"^/objects/\d+/documents/upload$"),
        re.compile(r"^/objects/\d+/documents/\d+/update$"),
        re.compile(r"^/objects/\d+/documents/\d+/delete$"),
        re.compile(r"^/documents/\d+/update$"),
        re.compile(r"^/documents/batch-delete$"),
    ],
)

# 3. Access Logging (выполнится третьим)
app.add_middleware(AccessLogMiddleware)

# 2. Swagger Security (выполнится третьим)
if settings.ENABLE_DOCS:
    app.add_middleware(
        SwaggerSecurityMiddleware,
        allowed_ips=settings.DOCS_ALLOWED_IPS
    )

# 1. Request ID (выполнится ПЕРВЫМ - то что нам нужно!)
app.add_middleware(RequestIDMiddleware)

# ===================================
# Подключение роутеров
# ===================================
app.include_router(auth_router, prefix="/api/v1")
app.include_router(profile_router, prefix="/profile")
app.include_router(object_router, prefix="/objects")
app.include_router(documents_router, prefix="/documents")
app.include_router(admin_router)

# Monitoring routes (admin only)
if settings.MONITORING_ENABLED:
    from modules.monitoring.routes import router as monitoring_router
    app.include_router(monitoring_router, prefix="/admin")


# ===================================
# Главная страница (редирект)
# ===================================
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root(request: Request):
    """Главная страница (редирект на Dashboard или Login)"""
    token = request.cookies.get("access_token")
    if token:
        return RedirectResponse(url="/dashboard", status_code=303)
    return RedirectResponse(url="/api/v1/auth/login-page", status_code=303)


# ===================================
# Healthcheck endpoint
# ===================================
@app.get(
    "/health",
    summary="Health check",
    tags=["🔧 System / Система"]
)
async def health(detailed: bool = False):
    """
    Проверка что сервис запущен и работает
    Supports detailed health checks with ?detailed=true
    """
    if detailed and settings.MONITORING_ENABLED:
        from core.monitoring.health import check_health
        return await check_health(detailed=True)
    
    return {"status": "ok", "app": settings.APP_NAME, "version": "1.0.0"}


# ===================================
# Dashboard (личный кабинет)
# ===================================
@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(
    request: Request,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """
    Главная страница личного кабинета
    """
    from modules.objects.models import Object, ObjectAccess
    
    # Базовый запрос: объекты с доступом
    base_query = db.query(Object).join(ObjectAccess).filter(
        ObjectAccess.user_id == user.id,
        Object.deleted_at == None  # Исключаем удаленные
    )
    
    # Активные объекты
    active_count = base_query.filter(
        Object.is_active == True,
        Object.is_archived == False
    ).count()
    
    # Неактивные (только для владельца/админа)
    if user.role.value == "admin":
        inactive_count = db.query(Object).filter(
            Object.is_active == False,
            Object.is_archived == False,
            Object.deleted_at == None
        ).count()
    else:
        inactive_count = db.query(Object).filter(
            Object.created_by == user.id,
            Object.is_active == False,
            Object.is_archived == False,
            Object.deleted_at == None
        ).count()
    
    # В архиве
    archived_count = base_query.filter(
        Object.is_archived == True
    ).count()
    
    # Последние активные объекты (топ-5)
    recent_objects = base_query.filter(
        Object.is_active == True,
        Object.is_archived == False
    ).order_by(Object.created_at.desc()).limit(5).all()
    
    logger.info({
        "event": "dashboard_access",
        "user_id": user.id,
        "email": user.email,
        "active_count": active_count,
        "inactive_count": inactive_count,
        "archived_count": archived_count
    })

    sidebar_context = get_sidebar_context(user, db)
    
    return templates.TemplateResponse(
        "web/dashboard/index.html",
        {
            "request": request,
            "user": user,
            "current_user": user,
            "active_count": active_count,
            "inactive_count": inactive_count,
            "archived_count": archived_count,
            "recent_objects": recent_objects,
            **sidebar_context  # ✅ Распаковываем sidebar context      
        }
    )

# ===================================
# Страница доступа к документации
# ===================================
@app.get("/docs-access-denied", response_class=HTMLResponse, include_in_schema=False)
async def docs_access_denied(request: Request):
    """Страница с информацией о доступе к документации"""
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Доступ к документации</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 600px;
                margin: 100px auto;
                padding: 20px;
                text-align: center;
            }
            .icon { font-size: 64px; margin-bottom: 20px; }
            h1 { color: #333; }
            .info { background: #f0f0f0; padding: 20px; border-radius: 10px; margin: 20px 0; }
            .button { 
                display: inline-block;
                padding: 12px 24px;
                background: #4F46E5;
                color: white;
                text-decoration: none;
                border-radius: 8px;
                margin: 10px;
            }
            .button:hover { background: #4338CA; }
        </style>
    </head>
    <body>
        <div class="icon">🔒</div>
        <h1>Доступ к API документации</h1>
        <div class="info">
            <p><strong>Требования для доступа:</strong></p>
            <ul style="text-align: left;">
                <li>✅ Авторизация в системе</li>
                <li>👑 Роль: Администратор</li>
                <li>🌐 Разрешённый IP-адрес</li>
            </ul>
        </div>
        <a href="/api/v1/auth/login-page" class="button">🔑 Войти в сис��ему</a>
        <a href="/dashboard" class="button">🏠 На главную</a>
    </body>
    </html>
    """

# HEALTH CHECKS
@app.on_event("startup")
async def init_monitoring():
    from core.monitoring.metrics import init_metrics
    from core.monitoring.alerts import alert_manager
    await alert_manager.initialize()
    init_metrics()

# Периодическая очистка сессий (раз в час)
async def periodic_session_cleanup(): 
    while True: 
        cleanup_expired_sessions() 
        await asyncio.sleep(3600) # раз в час

@app.on_event("startup") 
async def startup_event(): 
    asyncio.create_task(periodic_session_cleanup())



if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        reload=settings.DEBUG,
        log_level="info"
    )