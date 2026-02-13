import logging
from redis import Redis
from fastapi import HTTPException, status
from modules.auth.utils import get_error_id

logger = logging.getLogger(__name__)


class BruteForceProtection:
    """
    Защита от брутфорса с использованием Redis.
    
    Поддерживает разные сценарии:
    - Логин (email + IP)
    - OTP верификация (email + purpose)
    - Регистрация (IP)
    - Сброс пароля (email)
    """

    def __init__(self, redis: Redis):
        self.redis = redis

    # ===================================
    # Логин (email + IP)
    # ===================================
    def check_login_attempts(self, email: str, ip_address: str = None) -> bool:
        """
        Проверить есть ли блокировка на логин.
        
        Ключ: login_attempts:{email}:{ip}
        Лимит: 5 попыток за 15 минут
        Блокировка: 15 минут
        
        Returns:
            bool: True если блокирован, False если разрешено
        """
        key = self._build_key("login", email, ip_address)
        attempts = self.redis.get(key)
        
        if attempts and int(attempts) >= 5:
            return True
        return False

    def record_failed_login(self, email: str, ip_address: str = None):
        """Записать неудачную попытку логина"""
        key = self._build_key("login", email, ip_address)
        self.redis.incr(key)
        self.redis.expire(key, 900)  # 15 минут
        
        attempts = int(self.redis.get(key))
        logger.warning(
            f"Failed login attempt for {email} from {ip_address or 'unknown'} "
            f"(attempt {attempts}/5)"
        )

    def clear_login_attempts(self, email: str, ip_address: str = None):
        """Сбросить счётчик при успешном логине"""
        key = self._build_key("login", email, ip_address)
        self.redis.delete(key)

    # ===================================
    # OTP верификация (email + purpose)
    # ===================================
    def check_otp_attempts(self, email: str, purpose: str) -> bool:
        """
        Проверить есть ли блокировка на OTP верификацию.
        
        Ключ: otp_verify_attempts:{email}:{purpose}
        Лимит: 5 попыток за 15 минут
        Блокировка: 15 минут
        
        Returns:
            bool: True если блокирован, False если разрешено
        """
        key = self._build_key("otp_verify", email, purpose)
        attempts = self.redis.get(key)
        
        if attempts and int(attempts) >= 5:
            return True
        return False

    def record_failed_otp(self, email: str, purpose: str):
        """Записать неудачную попытку ввода OTP"""
        key = self._build_key("otp_verify", email, purpose)
        self.redis.incr(key)
        self.redis.expire(key, 900)  # 15 минут
        
        attempts = int(self.redis.get(key))
        logger.warning(
            f"Failed OTP verification for {email} (purpose: {purpose}) "
            f"(attempt {attempts}/5)"
        )

    def clear_otp_attempts(self, email: str, purpose: str):
        """Сбросить счётчик при успешной верификации OTP"""
        key = self._build_key("otp_verify", email, purpose)
        self.redis.delete(key)

    # ===================================
    # OTP запрос (rate limiting)
    # ===================================
    def check_otp_request_rate(self, email: str, purpose: str, max_requests: int = 3) -> bool:
        """
        Проверить rate limiting на запрос OTP кода.
        
        Ключ: otp_request:{email}:{purpose}
        Лимит: 3 запроса за 1 час
        
        Returns:
            bool: True если превышен лимит, False если разрешено
        """
        key = self._build_key("otp_request", email, purpose)
        requests = self.redis.get(key)
        
        if requests and int(requests) >= max_requests:
            return True
        return False

    def record_otp_request(self, email: str, purpose: str):
        """Записать запрос OTP кода"""
        key = self._build_key("otp_request", email, purpose)
        self.redis.incr(key)
        self.redis.expire(key, 3600)  # 1 час

    def get_otp_request_count(self, email: str, purpose: str) -> int:
        """Получить количество запросов OTP"""
        key = self._build_key("otp_request", email, purpose)
        count = self.redis.get(key)
        return int(count) if count else 0

    # ===================================
    # Регистрация (IP)
    # ===================================
    def check_registration_attempts(self, ip_address: str = None) -> bool:
        """
        Проверить есть ли блокировка на регистрацию.
        
        Ключ: register_attempts:{ip}
        Лимит: 10 попыток за 1 час
        Блокировка: 1 час
        
        Returns:
            bool: True если блокирован, False если разрешено
        """
        key = self._build_key("register", ip_address)
        attempts = self.redis.get(key)
        
        if attempts and int(attempts) >= 10:
            return True
        return False

    def record_registration_attempt(self, ip_address: str = None):
        """Записать попытку регистрации"""
        key = self._build_key("register", ip_address)
        self.redis.incr(key)
        self.redis.expire(key, 3600)  # 1 час

    # ===================================
    # Сброс пароля (email)
    # ===================================
    def check_password_reset_attempts(self, email: str) -> bool:
        """
        Проверить rate limiting на сброс пароля.
        
        Ключ: password_reset:{email}
        Лимит: 3 попыток за 1 час
        
        Returns:
            bool: True если превышен лимит, False если разрешено
        """
        key = self._build_key("password_reset", email)
        attempts = self.redis.get(key)
        
        if attempts and int(attempts) >= 3:
            return True
        return False

    def record_password_reset_attempt(self, email: str):
        """Записать попытку сброса пароля"""
        key = self._build_key("password_reset", email)
        self.redis.incr(key)
        self.redis.expire(key, 3600)  # 1 час

    # ===================================
    # Получение оставшегося времени блокировки
    # ===================================
    def get_remaining_block_time(self, key: str) -> int:
        """Получить оставшееся время блокировки в секундах"""
        ttl = self.redis.ttl(key)
        return max(ttl, 0)

    def get_login_block_time(self, email: str, ip_address: str = None) -> int:
        """Получить оставшееся время блокировки логина"""
        key = self._build_key("login", email, ip_address)
        return self.get_remaining_block_time(key)

    # ===================================
    # Вспомогательные методы
    # ===================================
    @staticmethod
    def _build_key(*parts) -> str:
        """Построить Redis ключ из частей"""
        filtered = [str(p) for p in parts if p is not None]
        return ":".join(filtered)

    def get_all_attempts(self, email: str) -> dict:
        """
        Получить все попытки для пользователя
        (для отладки и мониторинга)
        """
        pattern = f"*:{email}*"
        keys = self.redis.keys(pattern)
        
        attempts = {}
        for key in keys:
            value = self.redis.get(key)
            if value:
                attempts[key.decode() if isinstance(key, bytes) else key] = int(value)
        
        return attempts


# ===================================
# Исключения для брутфорса
# ===================================
class BruteForceException(HTTPException):
    """Base exception for brute force protection"""
    pass


class LoginBruteForcedException(BruteForceException):
    """Too many login attempts"""
    def __init__(self, remaining_time: int = None):
        minutes = remaining_time // 60 if remaining_time else 15
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many login attempts. Try again in {minutes} minutes.",
            headers={"X-Error-ID": get_error_id()}
        )


class OTPBruteForcedException(BruteForceException):
    """Too many OTP verification attempts"""
    def __init__(self, remaining_time: int = None):
        minutes = remaining_time // 60 if remaining_time else 15
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many OTP attempts. Try again in {minutes} minutes.",
            headers={"X-Error-ID": get_error_id()}
        )


class OTPRateLimitException(BruteForceException):
    """OTP request rate limit exceeded"""
    def __init__(self, retry_after: int = None):
        minutes = retry_after // 60 if retry_after else 20
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many OTP requests. Try again in {minutes} minutes.",
            headers={"X-Error-ID": get_error_id(), "Retry-After": str(retry_after or 3600)}
        )


class RegistrationBruteForcedException(BruteForceException):
    """Too many registration attempts from IP"""
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many registration attempts from this IP. Try again later.",
            headers={"X-Error-ID": get_error_id()}
        )


class PasswordResetRateLimitException(BruteForceException):
    """Password reset rate limit exceeded"""
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many password reset requests. Try again later.",
            headers={"X-Error-ID": get_error_id()}
        )