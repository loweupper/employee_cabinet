import logging

from modules.auth.models import LoginAttempt
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from modules.monitoring.service_alerts import AlertService 
from modules.monitoring.models import AlertSeverity, AlertType
from core.config import settings, OTP_EXPIRATION_DELTA
from core.redis import redis_client
from modules.auth.models import User, Session as SessionModel, OTP, UserRole, OTPPurpose
from modules.auth.schemas import (
    UserCreate, UserLogin, UserUpdate,
    ChangePasswordRequest, TokenResponse, UserRead,
    OTPRequest, OTPVerify, PasswordResetRequest, PasswordResetConfirm
)
from modules.auth.utils import (
    hash_password, verify_password,
    create_access_token, create_refresh_token,
    hash_refresh_token,
    hash_otp, verify_otp, generate_otp,
    get_error_id
)
from modules.auth.brute_force import (
    BruteForceProtection,
    LoginBruteForcedException,
    OTPBruteForcedException,
    OTPRateLimitException,
    RegistrationBruteForcedException,
    PasswordResetRateLimitException
)

from modules.auth.models import Session as SessionModel


logger = logging.getLogger("app")

# Инициализируем защиту от брутфорса
brute_force = BruteForceProtection(redis_client)


class AuthService:

    # ============================================================
    # Регистрация
    # ============================================================
    @staticmethod
    def register(data: UserCreate, db: Session, ip_address: str = None) -> UserRead:
        logger.info({"event": "register_start"})
        print(f"Registering user: {data.email} from IP {ip_address}")
        """
        Регистрация нового пользователя.
        
        Args:
            data: UserCreate схема
            db: Database session
            ip_address: IP адрес пользователя (для rate limiting)
        """
        # Проверяем rate limiting по IP
        if brute_force.check_registration_attempts(ip_address):
            print(f"Registration attempt blocked from IP {ip_address}")
            logger.warning({"event": "registration_blocked", "ip_address": ip_address})
            raise RegistrationBruteForcedException()
        
        brute_force.record_registration_attempt(ip_address)

        logger.info({"event": "check_email", "email": data.email.lower(), "ip_address": ip_address})
        # Проверяем email
        existing = db.query(User).filter(User.email == data.email.lower()).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
                headers={"X-Error-ID": get_error_id()}
            )
        logger.info({"event": "register_user", "email": data.email.lower(), "ip_address": ip_address})

        user = User(
            email=data.email.lower(),
            hashed_password=hash_password(data.password),
            role=UserRole.EMPLOYEE,
            is_active=False,  # Требуется активация админом
            first_name=data.first_name,
            last_name=data.last_name,
            middle_name=data.middle_name,
            phone_number=data.phone_number,
            avatar_url=data.avatar_url,
            department=data.department,
            position=data.position,
            location=data.location,
            object_id=data.object_id,
        )
        
        logger.info({"event": "register_user", "email": data.email.lower(), "ip_address": ip_address})

        db.add(user)
        print(f"User {data.email} added to DB session")
        db.commit()
        db.refresh(user)

        logger.info(f"User registered: {user.email} from IP {ip_address}")

        return UserRead.from_orm(user)

    # ============================================================
    # Логин (с защитой от брутфорса)
    # ============================================================
    @staticmethod
    def login(
        data: UserLogin,
        db: Session,
        user_agent: str = None,
        ip_address: str = None
    ) -> TokenResponse:
        """
        Вход в систему с защитой от брутфорса.
        
        Args:
            data: UserLogin схема
            db: Database session
            user_agent: User-Agent из request
            ip_address: IP адрес клиента
        """
        email = data.email.lower()

        # ===== Проверяем блокировку =====
        if brute_force.check_login_attempts(email, ip_address):
            remaining_time = brute_force.get_login_block_time(email, ip_address)
            logger.warning(f"Пользователь {email} заблокирован на {remaining_time} секунд с IP {ip_address}")
            raise LoginBruteForcedException(remaining_time)

        # ===== Проверяем учётные данные =====
        user = db.query(User).filter(User.email == email).first()

        # ===== Неуспешный логин =====
        if not user or not verify_password(data.password, user.hashed_password):

            # Записываем неудачный логин в защиту от брутфорса
            brute_force.record_failed_login(email, ip_address)

            # Записываем попытку
            attempt = LoginAttempt(
                email=email,
                ip_address=ip_address,
                user_id=user.id if user else None,
                success=False
            )
            db.add(attempt)
            db.commit()

            # 1. Считаем количество неудачных попыток за последние 10 минут
            failed_attempts = (
                db.query(LoginAttempt)
                .filter(
                    LoginAttempt.email == email,
                    LoginAttempt.ip_address == ip_address,
                    LoginAttempt.success == False,
                    LoginAttempt.timestamp >= datetime.utcnow() - timedelta(minutes=10)
                )
                .count()
            )

            # Если >= 5 → создаём алерт
            if failed_attempts >= 5:
                AlertService.create_alert(
                    db=db,
                    severity=AlertSeverity.HIGH,
                    type=AlertType.MULTIPLE_FAILED_LOGINS,
                    message=f"Множественные неудачные попытки входа для {email} с IP {ip_address}",
                    ip_address=ip_address,
                    user_id=user.id if user else None,
                    details={"failed_attempts": failed_attempts}
                )
                db.commit()

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Пользователь не найден или пароль неверный",
                headers={"X-Error-ID": get_error_id()}
            ) 


        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Акаунт не активирован. Пожалуйста, дождитесь активации администратором.",
                headers={"X-Error-ID": get_error_id()}
            )

        # ===== Успешный логин — сбрасываем счётчик =====
        brute_force.clear_login_attempts(email, ip_address)
        logger.info(f"User logged in: {user.email} from IP {ip_address}")

        # Записываем успешную попытку
        attempt = LoginAttempt(
            email=email,
            ip_address=ip_address,
            user_id=user.id,
            success=True
        )
        db.add(attempt)
        db.commit()

        # Создаём access token
        access_token, _ = create_access_token(user.id, user.role.value)

        # Создаём refresh token
        refresh_raw, refresh_hash, refresh_expires = create_refresh_token()

        # Сохраняем сессию
        session = SessionModel(
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=refresh_expires,
            user_agent=user_agent,
            ip_address=ip_address,
        )

        db.add(session)
        db.commit()

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_raw,
            expires_in=settings.JWT_EXPIRATION_SECONDS,
            user=UserRead.from_orm(user)
        )

    # ============================================================
    # Refresh token
    # ============================================================
    @staticmethod
    def refresh_token(refresh_token: str, db: Session) -> TokenResponse:
        refresh_hash = hash_refresh_token(refresh_token)

        session = db.query(SessionModel).filter(
            SessionModel.token_hash == refresh_hash,
            SessionModel.is_revoked == False,
            SessionModel.expires_at > datetime.now(timezone.utc)
        ).first()

        if not session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверный или просроченный refresh token",
                headers={"X-Error-ID": get_error_id()}
            )

        user = db.query(User).filter(User.id == session.user_id).first()

        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Пользователь не найден или неактивен",
                headers={"X-Error-ID": get_error_id()}
            )

        # Создаём новый access token
        access_token, _ = create_access_token(user.id, user.role.value)

        # Ротируем refresh token
        new_refresh_raw, new_refresh_hash, new_refresh_expires = create_refresh_token()

        session.token_hash = new_refresh_hash
        session.expires_at = new_refresh_expires
        session.last_used_at = datetime.now(timezone.utc)

        db.commit()

        return TokenResponse(
            access_token=access_token,
            refresh_token=new_refresh_raw,
            expires_in=settings.JWT_EXPIRATION_SECONDS,
            user=UserRead.from_orm(user)
        )

    # ============================================================
    # Logout
    # ============================================================
    @staticmethod
    def logout(user: User, refresh_token: str, db: Session) -> dict:
        if refresh_token:
            refresh_hash = hash_refresh_token(refresh_token)

            session = db.query(SessionModel).filter(
                SessionModel.user_id == user.id,
                SessionModel.token_hash == refresh_hash
            ).first()

            if session:
                session.is_revoked = True
                db.commit()

        return {"message": "Logged out successfully"}

    # ============================================================
    # Смена пароля
    # ============================================================
    @staticmethod
    def change_password(user: User, data: ChangePasswordRequest, db: Session) -> dict:
        if not verify_password(data.current_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Неверный текущий пароль",
                headers={"X-Error-ID": get_error_id()}
            )

        user.hashed_password = hash_password(data.new_password)
        db.commit()

        logger.info(f"Пароль изменён для пользователя: {user.email}")

        return {"message": "Пароль успешно изменён"}

    # ============================================================
    # OTP — запрос (с rate limiting)
    # ============================================================
    @staticmethod
    def request_otp(data: OTPRequest, db: Session) -> dict:
        """
        Запрос OTP кода с rate limiting.
        
        Лимит: 3 запроса в час на email+purpose
        """
        email = data.email.lower()
        purpose = data.purpose.value

        user = db.query(User).filter(User.email == email).first()

        if not user:
            # Не раскрываем существует ли пользователь
            return {"message": "Если email существует, OTP был отправлен"}

        # ===== Проверяем rate limiting =====
        if brute_force.check_otp_request_rate(email, purpose):
            logger.warning(f"OTP request rate limit exceeded for {email} (purpose: {purpose})")
            raise OTPRateLimitException()

        brute_force.record_otp_request(email, purpose)

        # Удаляем старые OTP
        db.query(OTP).filter(
            OTP.user_id == user.id,
            OTP.purpose == OTPPurpose(purpose),
            OTP.used == False
        ).delete()
        db.commit()

        # Генерируем OTP
        code = generate_otp()
        code_hash = hash_otp(code)
        expires_at = datetime.now(timezone.utc) + OTP_EXPIRATION_DELTA

        otp = OTP(
            user_id=user.id,
            code=code_hash,
            purpose=OTPPurpose(purpose),
            expires_at=expires_at,
            used=False,
            attempts=0
        )

        db.add(otp)
        db.commit()

        logger.debug(f"OTP requested for {email} (purpose: {purpose}), code: {code}")
        # TODO: отправить OTP по email

        return {"message": "Если email существует, OTP был отправлен"}

    # ============================================================
    # OTP — верификация (с защитой от брутфорса)
    # ============================================================
    @staticmethod
    def verify_otp(data: OTPVerify, db: Session) -> TokenResponse:
        """
        Верификация OTP кода с защитой от брутфорса.
        
        Лимит: 5 попыток в 15 минут на email+purpose
        """
        email = data.email.lower()

        user = db.query(User).filter(User.email == email).first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Неверный email или код",
                headers={"X-Error-ID": get_error_id()}
            )

        # ===== Получаем активный OTP =====
        otp = db.query(OTP).filter(
            OTP.user_id == user.id,
            OTP.used == False,
            OTP.expires_at > datetime.now(timezone.utc)
        ).order_by(OTP.created_at.desc()).first()

        if not otp:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Неверный или просроченный код",
                headers={"X-Error-ID": get_error_id()}
            )

        purpose = otp.purpose.value

        # ===== Проверяем блокировку =====
        if brute_force.check_otp_attempts(email, purpose):
            remaining_time = brute_force.get_remaining_block_time(
                f"otp_verify:{email}:{purpose}"
            )
            logger.warning(f"OTP verification attempt blocked for {email} (blocked for {remaining_time}s)")
            raise OTPBruteForcedException(remaining_time)

        # ===== Проверяем количество попыток =====
        if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            brute_force.record_failed_otp(email, purpose)
            raise OTPBruteForcedException()

        # ===== Проверяем код =====
        if not verify_otp(data.code, otp.code):
            otp.attempts += 1
            brute_force.record_failed_otp(email, purpose)
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Неверный код",
                headers={"X-Error-ID": get_error_id()}
            )

        # ===== Успешная верификация — сбрасываем счётчик =====
        otp.used = True
        brute_force.clear_otp_attempts(email, purpose)
        db.commit()

        logger.info(f"OTP verified for {email} (purpose: {purpose})")

        # Создаём токены
        access_token, _ = create_access_token(user.id, user.role.value)
        refresh_raw, refresh_hash, refresh_expires = create_refresh_token()

        session = SessionModel(
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=refresh_expires
        )
        db.add(session)
        db.commit()

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_raw,
            expires_in=settings.JWT_EXPIRATION_SECONDS,
            user=UserRead.from_orm(user)
        )

    # ============================================================
    # Сброс пароля — запрос (с rate limiting)
    # ============================================================
    @staticmethod
    def password_reset_request(data: PasswordResetRequest, db: Session) -> dict:
        """
        Запрос на сброс пароля с rate limiting.
        
        Лимит: 3 запроса в час на email
        """
        email = data.email.lower()

        user = db.query(User).filter(User.email == email).first()

        if not user:
            return {"message": "Если email существует, ссылка для сброса пароля была отправлена"}

        # ===== Проверяем rate limiting =====
        if brute_force.check_password_reset_attempts(email):
            logger.warning(f"Password reset rate limit exceeded for {email}")
            raise PasswordResetRateLimitException()

        brute_force.record_password_reset_attempt(email)

        # Удаляем старые OTP
        db.query(OTP).filter(
            OTP.user_id == user.id,
            OTP.purpose == OTPPurpose.PASSWORD_RESET,
            OTP.used == False
        ).delete()
        db.commit()

        # Генерируем OTP
        code = generate_otp()
        code_hash = hash_otp(code)
        expires_at = datetime.now(timezone.utc) + OTP_EXPIRATION_DELTA

        otp = OTP(
            user_id=user.id,
            code=code_hash,
            purpose=OTPPurpose.PASSWORD_RESET,
            expires_at=expires_at,
            used=False,
            attempts=0
        )

        db.add(otp)
        db.commit()

        logger.debug(f"Password reset OTP for {email}, code: {code}")
        # TODO: отправить OTP по email

        return {"message": "Если email существует, ссылка для сброса пароля была отправлена"}

    # ============================================================
    # Сброс пароля — подтверждение (с защитой от брутфорса)
    # ============================================================
    @staticmethod
    def password_reset_confirm(data: PasswordResetConfirm, db: Session) -> dict:
        """
        Подтверждение сброса пароля с защитой от брутфорса.
        
        Лимит: 5 попыток в 15 минут на email
        """
        email = data.email.lower()

        user = db.query(User).filter(User.email == email).first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid email or code",
                headers={"X-Error-ID": get_error_id()}
            )

        # Получаем OTP
        otp = db.query(OTP).filter(
            OTP.user_id == user.id,
            OTP.purpose == OTPPurpose.PASSWORD_RESET,
            OTP.used == False,
            OTP.expires_at > datetime.now(timezone.utc)
        ).first()

        if not otp:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired code",
                headers={"X-Error-ID": get_error_id()}
            )

        purpose = "password_reset"

        # ===== Проверяем блокировку =====
        if brute_force.check_otp_attempts(email, purpose):
            raise OTPBruteForcedException()

        # ===== Проверяем количество попыток =====
        if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            brute_force.record_failed_otp(email, purpose)
            raise OTPBruteForcedException()

        # ===== Проверяем код =====
        if not verify_otp(data.code, otp.code):
            otp.attempts += 1
            brute_force.record_failed_otp(email, purpose)
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid code",
                headers={"X-Error-ID": get_error_id()}
            )

        # ===== Успешное подтверждение =====
        otp.used = True
        user.hashed_password = hash_password(data.new_password)
        brute_force.clear_otp_attempts(email, purpose)
        db.commit()

        logger.info(f"Password reset confirmed for user: {email}")

        return {"message": "Пароль успешно сброшен"}

    # ============================================================
    # Обновление профиля
    # ============================================================
    @staticmethod
    def update_user(user: User, data: UserUpdate, db: Session) -> UserRead:
        for field, value in data.dict(exclude_unset=True).items():
            setattr(user, field, value)

        db.commit()
        db.refresh(user)

        logger.info(f"Профиль пользователя обновлён: {user.email}")

        return UserRead.from_orm(user)

    # ============================================================
    # Отозвать сессию
    # ============================================================
    @staticmethod
    def revoke_session(user_id: int, session_id: int, db: Session) -> dict:
        session = db.query(SessionModel).filter(
            SessionModel.id == session_id,
            SessionModel.user_id == user_id
        ).first()

        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Сессия не найдена",
                headers={"X-Error-ID": get_error_id()}
            )

        session.is_revoked = True
        db.commit()

        logger.info(f"Сессия отозвана: user_id={user_id}, session_id={session_id}")

        return {"message": "Сессия успешно отозвана"}
    

