from pydantic_settings import BaseSettings
from datetime import timedelta
from pydantic import Field
import os
from typing import Optional

from typing import List


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
    DATABASE_URL: str

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379
    REDIS_URL: str

    # Files
    FILES_PATH: str = "/files"

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



    # ===== CORS =====
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8000"]
    CORS_CREDENTIALS: bool = True
    CORS_METHODS: list[str] = ["*"]
    CORS_HEADERS: list[str] = ["*"]

    # ===================================
    # Swagger UI Security
    # ===================================
    ENABLE_DOCS: bool = True  # ✅ Включить/выключить документацию
    DOCS_REQUIRE_AUTH: bool = True  # ✅ Требовать авторизацию для доступа к /docs
    DOCS_ALLOWED_IPS: List[str] = []  # ✅ Белый список IP
    
     # Environment
    ENVIRONMENT: str = "development"  # development, staging, production
     
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()

# Вычисляемые константы
JWT_EXPIRATION_DELTA = timedelta(seconds=settings.JWT_EXPIRATION_SECONDS)
REFRESH_TOKEN_EXPIRATION_DELTA = timedelta(days=settings.REFRESH_TOKEN_EXPIRATION_DAYS)
OTP_EXPIRATION_DELTA = timedelta(seconds=settings.OTP_EXPIRATION_SECONDS)