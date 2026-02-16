from pydantic_settings import BaseSettings
from datetime import timedelta
from pydantic import Field, field_validator, ValidationInfo
import os
from typing import Optional
import warnings
import logging
from urllib.parse import quote_plus

from typing import List, Union

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    APP_NAME: str = "Employee Cabinet"
    DEBUG: bool = True
    SECRET_KEY: str

    # Database
    POSTGRES_HOST: str
    POSTGRES_PORT: int
    POSTGRES_DB: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    DATABASE_URL: Optional[str] = None

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379
    REDIS_URL: Optional[str] = None

    # Files
    FILES_PATH: str = "/files"
    MAX_FILE_SIZE: int = 10485760  # 10MB in bytes (10 * 1024 * 1024)

    # ===== JWT Configuration =====
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_SECONDS: int = 3600  # 1 hour
    REFRESH_TOKEN_EXPIRATION_DAYS: int = 7  # 7 days

    # ===== OTP Configuration =====
    OTP_LENGTH: int = 6
    OTP_EXPIRATION_SECONDS: int = 300  # 5 minutes
    OTP_MAX_ATTEMPTS: int = 5

    # ===== Email Configuration =====
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_FROM_NAME: str = "Employee Cabinet"

    # ===== Rate Limiting =====
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 5  # requests per minute
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    # ===== Security =====
    ACCOUNT_LOCKOUT_THRESHOLD: int = 5  # попыток перед блокировкой
    ACCOUNT_LOCKOUT_DURATION_MINUTES: int = 15  # на сколько заблокировать
    
    # ===== Monitoring =====
    MONITORING_ENABLED: bool = True
    METRICS_ENABLED: bool = True
    ALERT_EMAIL_RECIPIENTS: List[str] = Field(default_factory=lambda: [])
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[str] = None
    LOG_RETENTION_DAYS: int = 30
    ALERT_RETENTION_HOURS: int = 24
    BRUTE_FORCE_THRESHOLD: int = 5
    BRUTE_FORCE_WINDOW_MINUTES: int = 5



    # ===== CORS =====
    CORS_ORIGINS: list[str] = Field(default=["http://localhost:3000", "http://localhost:8000"])
    CORS_CREDENTIALS: bool = True
    CORS_METHODS: list[str] = ["GET", "POST", "PUT", "DELETE"]
    CORS_HEADERS: list[str] = ["Content-Type", "Authorization"]

    # ===================================
    # Swagger UI Security
    # ===================================
    ENABLE_DOCS: bool = True  # ✅ Включить/выключить документацию
    DOCS_REQUIRE_AUTH: bool = True  # ✅ Требовать авторизацию для доступа к /docs
    DOCS_ALLOWED_IPS: List[str] = Field(default_factory=lambda: ["127.0.0.1"])  # ✅ Белый список IP
    
    # Swagger Basic Auth credentials (for staging/dev environments)
    SWAGGER_USERNAME: str = Field(description="Username for Swagger basic auth")
    SWAGGER_PASSWORD: str = Field(description="Password for Swagger basic auth")
    
     # Environment
    ENVIRONMENT: str = "development"  # development, staging, production
     
    class Config:
        env_file = ".env"
        case_sensitive = True
        # Allow JSON parsing errors to be caught by validators
        env_parse_none_str = 'empty'
    
    @field_validator('SECRET_KEY')
    @classmethod
    def validate_secret_key(cls, v: str, info: ValidationInfo) -> str:
        """Validate that SECRET_KEY is strong enough"""
        if len(v) < 32:
            raise ValueError(
                f"SECRET_KEY must be at least 32 characters long (current: {len(v)}). "
                "Generate a strong key with: python generate_secrets.py --type secret_key"
            )
        
        # Warn if using default/weak patterns
        weak_patterns = ['change', 'secret', 'password', 'default', 'test', '123']
        if any(pattern in v.lower() for pattern in weak_patterns):
            warnings.warn(
                f"SECRET_KEY appears to contain weak patterns. "
                "Use a cryptographically random key in production.",
                UserWarning
            )
        
        return v
    
    @field_validator('DEBUG')
    @classmethod
    def validate_debug_mode(cls, v: bool, info: ValidationInfo) -> bool:
        """Warn if DEBUG is enabled in production"""
        # We need to check ENVIRONMENT from info.data if available
        environment = info.data.get('ENVIRONMENT', 'development')
        
        if v is True and environment == 'production':
            warnings.warn(
                "DEBUG=True in production environment! This should be disabled in production.",
                UserWarning
            )
        
        return v
    
    @field_validator('DATABASE_URL')
    @classmethod
    def build_database_url(cls, v: Optional[str], info: ValidationInfo) -> str:
        """Build DATABASE_URL from components if not provided"""
        if v:
            return v
        
        # Build from components
        data = info.data
        host = data.get('POSTGRES_HOST')
        port = data.get('POSTGRES_PORT')
        db = data.get('POSTGRES_DB')
        user = data.get('POSTGRES_USER')
        password = data.get('POSTGRES_PASSWORD')
        
        if not all([host, port, db, user, password]):
            raise ValueError(
                "Either DATABASE_URL must be provided, or all of "
                "POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD"
            )
        
        # URL-encode username and password to handle special characters
        encoded_user = quote_plus(str(user))
        encoded_password = quote_plus(str(password))
        
        return f"postgresql://{encoded_user}:{encoded_password}@{host}:{port}/{db}"
    
    @field_validator('REDIS_URL')
    @classmethod
    def build_redis_url(cls, v: Optional[str], info: ValidationInfo) -> str:
        """Build REDIS_URL from components if not provided"""
        if v:
            return v
        
        # Build from components
        data = info.data
        host = data.get('redis_host', 'redis')
        port = data.get('redis_port', 6379)
        
        return f"redis://{host}:{port}/0"
    
    @field_validator('DOCS_ALLOWED_IPS', mode='before')
    @classmethod
    def parse_docs_ips(cls, v):
        """Parse DOCS_ALLOWED_IPS from JSON string or list"""
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse DOCS_ALLOWED_IPS as JSON: {v}, using default")
                return ["127.0.0.1"]
        return v if v else ["127.0.0.1"]
    
    @field_validator('ALERT_EMAIL_RECIPIENTS', mode='before')
    @classmethod
    def parse_alert_recipients(cls, v):
        """Parse ALERT_EMAIL_RECIPIENTS from JSON string or list"""
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse ALERT_EMAIL_RECIPIENTS as JSON: {v}, using empty list")
                return []
        return v if v else []

settings = Settings()

# Вычисляемые константы
JWT_EXPIRATION_DELTA = timedelta(seconds=settings.JWT_EXPIRATION_SECONDS)
REFRESH_TOKEN_EXPIRATION_DELTA = timedelta(days=settings.REFRESH_TOKEN_EXPIRATION_DAYS)
OTP_EXPIRATION_DELTA = timedelta(seconds=settings.OTP_EXPIRATION_SECONDS)