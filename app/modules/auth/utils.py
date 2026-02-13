import secrets
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from passlib.context import CryptContext
from core.config import settings, JWT_EXPIRATION_DELTA, REFRESH_TOKEN_EXPIRATION_DELTA

# ===================================
# Контекст для хэширования паролей
# ===================================
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ===================================
# Функции для работы с паролями
# ===================================
def hash_password(password: str) -> str:
    """Хэш пароля с использованием bcrypt"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверка пароля"""
    return pwd_context.verify(plain_password, hashed_password)


# ===================================
# Функции для работы с токенами
# ===================================
def create_access_token(user_id: int, role: str) -> tuple[str, datetime]:
    """
    Создать JWT access token.
    
    Returns:
        tuple[str, datetime]: (token, expiration_time)
    """
    now = datetime.now(timezone.utc)
    expires_at = now + JWT_EXPIRATION_DELTA
    
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": expires_at
    }
    
    token = jwt.encode(
        payload,
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    
    return token, expires_at


def create_refresh_token() -> tuple[str, str, datetime]:
    """
    Создать refresh token.
    
    Returns:
        tuple[str, str, datetime]: (token, token_hash, expiration_time)
    """
    now = datetime.now(timezone.utc)
    expires_at = now + REFRESH_TOKEN_EXPIRATION_DELTA
    
    # Генерируем случайный токен
    token = secrets.token_urlsafe(64)
    
    # Хэшируем токен для хранения в БД
    token_hash = hash_refresh_token(token)
    
    return token, token_hash, expires_at


def hash_refresh_token(token: str) -> str:
    """Хэширует refresh token для хранения в БД"""
    return hmac.new(
        settings.SECRET_KEY.encode(),
        token.encode(),
        hashlib.sha256
    ).hexdigest()


def verify_refresh_token(token: str, stored_hash: str) -> bool:
    """Проверяет refresh token"""
    token_hash = hash_refresh_token(token)
    return hmac.compare_digest(token_hash, stored_hash)


def decode_token(token: str) -> dict:
    """
    Декодировать JWT access token.
    
    Raises:
        JWTError: если токен невалиден
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError as e:
        raise JWTError(f"Invalid token: {str(e)}")


# ===================================
# Функции для OTP
# ===================================
def generate_otp(length: int = None) -> str:
    """Генерирует OTP код"""
    length = length or settings.OTP_LENGTH
    return ''.join(str(secrets.randbelow(10)) for _ in range(length))


def hash_otp(code: str) -> str:
    """Хэширует OTP код для хранения в БД"""
    return hmac.new(
        settings.SECRET_KEY.encode(),
        code.encode(),
        hashlib.sha256
    ).hexdigest()


def verify_otp(code: str, stored_hash: str) -> bool:
    """Проверяет OTP код"""
    code_hash = hash_otp(code)
    return hmac.compare_digest(code_hash, stored_hash)


# ===================================
# Утилиты для ошибок и ответов
# ===================================
def get_error_id() -> str:
    """Генерирует уникальный ID для ошибки (для трейса)"""
    return secrets.token_hex(4)