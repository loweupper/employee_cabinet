"""
Security anomaly detection and login attempt tracking
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import redis.asyncio as redis
import logging
import json

from core.monitoring.alerts import create_alert, AlertSeverity, AlertType

logger = logging.getLogger("app")


class LoginAttemptTracker:
    """
    Track login attempts and detect security anomalies
    Uses Redis for distributed tracking across multiple app instances
    """
    
    def __init__(self, redis_client: redis.Redis):
        """
        Initialize login attempt tracker
        
        Args:
            redis_client: Async Redis client
        """
        self.redis = redis_client
        self.brute_force_threshold = 5  # Failed attempts before alert
        self.brute_force_window_minutes = 5  # Time window for counting
        self.new_ip_retention_days = 30  # Track IPs for 30 days
        
        logger.info("LoginAttemptTracker initialized")
    
    async def record_attempt(self, email: str, ip: str, success: bool, user_id: Optional[int] = None) -> None:
        """
        Record login attempt and check for anomalies
        
        Args:
            email: User email attempting login
            ip: IP address of login attempt
            success: Whether login was successful
            user_id: User ID if login succeeded
        """
        timestamp = datetime.utcnow().isoformat()
        
        # Record metrics
        from core.monitoring.metrics import record_auth_attempt
        record_auth_attempt(email, success)
        
        if success:
            # Clear failed attempts on successful login
            await self._clear_failed_attempts(email, ip)
            
            # Check if this is a new IP for the user
            is_new_ip = await self.is_new_ip_for_user(email, ip)
            if is_new_ip and user_id:
                # Log warning and create alert
                logger.warning({
                    "event": "new_ip_login",
                    "email": email,
                    "ip": ip,
                    "user_id": user_id
                })
                
                await create_alert(
                    severity=AlertSeverity.MEDIUM,
                    alert_type=AlertType.NEW_IP_LOGIN,
                    message=f"User {email} logged in from new IP address",
                    user_id=user_id,
                    ip_address=ip,
                    details={
                        "email": email,
                        "timestamp": timestamp
                    }
                )
            
            # Store successful login IP
            await self._record_user_ip(email, ip)
        else:
            # Record failed attempt
            await self._record_failed_attempt(email, ip, timestamp)
            
            # Check for brute force
            is_brute_force = await self.check_brute_force(ip)
            if is_brute_force:
                logger.warning({
                    "event": "brute_force_detected",
                    "email": email,
                    "ip": ip
                })
                
                await create_alert(
                    severity=AlertSeverity.HIGH,
                    alert_type=AlertType.BRUTE_FORCE_ATTEMPT,
                    message=f"Brute force attack detected from IP {ip}",
                    user_id=None,
                    ip_address=ip,
                    details={
                        "email": email,
                        "failed_attempts": await self.get_failed_attempts_count(ip),
                        "timestamp": timestamp
                    }
                )
            
            # Check for multiple failed logins for this user
            user_failed_count = await self.get_failed_attempts(email, minutes=5)
            if user_failed_count >= self.brute_force_threshold:
                await create_alert(
                    severity=AlertSeverity.HIGH,
                    alert_type=AlertType.MULTIPLE_FAILED_LOGINS,
                    message=f"Multiple failed login attempts for {email}",
                    user_id=None,
                    ip_address=ip,
                    details={
                        "email": email,
                        "failed_attempts": user_failed_count,
                        "time_window_minutes": 5,
                        "timestamp": timestamp
                    }
                )
    
    async def check_brute_force(self, ip: str) -> bool:
        """
        Check if IP is performing brute force attack
        
        Args:
            ip: IP address to check
            
        Returns:
            True if brute force detected, False otherwise
        """
        count = await self.get_failed_attempts_count(ip)
        return count >= self.brute_force_threshold
    
    async def get_failed_attempts_count(self, ip: str) -> int:
        """
        Get count of failed attempts from an IP in the last 5 minutes
        
        Args:
            ip: IP address to check
            
        Returns:
            Number of failed attempts
        """
        key = f"failed_attempts:ip:{ip}"
        attempts_json = await self.redis.get(key)
        
        if not attempts_json:
            return 0
        
        try:
            attempts = json.loads(attempts_json)
            cutoff = (datetime.utcnow() - timedelta(minutes=self.brute_force_window_minutes)).isoformat()
            
            # Count attempts within window
            recent = [a for a in attempts if a['timestamp'] >= cutoff]
            return len(recent)
        except Exception as e:
            logger.error(f"Error counting failed attempts: {e}")
            return 0
    
    async def get_failed_attempts(self, email: str, minutes: int = 5) -> int:
        """
        Get recent failed attempts for a user
        
        Args:
            email: User email
            minutes: Time window in minutes
            
        Returns:
            Number of failed attempts in time window
        """
        key = f"failed_attempts:email:{email}"
        attempts_json = await self.redis.get(key)
        
        if not attempts_json:
            return 0
        
        try:
            attempts = json.loads(attempts_json)
            cutoff = (datetime.utcnow() - timedelta(minutes=minutes)).isoformat()
            
            # Count attempts within window
            recent = [a for a in attempts if a['timestamp'] >= cutoff]
            return len(recent)
        except Exception as e:
            logger.error(f"Error counting failed attempts for user: {e}")
            return 0
    
    async def is_new_ip_for_user(self, email: str, ip: str) -> bool:
        """
        Check if this is a new IP for user (not seen in last 30 days)
        
        Args:
            email: User email
            ip: IP address
            
        Returns:
            True if IP is new, False if seen before
        """
        key = f"user_ips:{email}"
        ips_json = await self.redis.get(key)
        
        if not ips_json:
            return True
        
        try:
            ips = json.loads(ips_json)
            return ip not in ips
        except Exception as e:
            logger.error(f"Error checking IP history: {e}")
            return False
    
    async def check_suspicious_activity(self, email: str, ip: str) -> Dict[str, Any]:
        """
        Check for various suspicious activities
        
        Args:
            email: User email
            ip: IP address
            
        Returns:
            Dictionary with suspicious activity indicators
        """
        return {
            "brute_force": await self.check_brute_force(ip),
            "multiple_failed_logins": await self.get_failed_attempts(email, 5) >= self.brute_force_threshold,
            "new_ip": await self.is_new_ip_for_user(email, ip),
            "ip_failed_attempts": await self.get_failed_attempts_count(ip),
            "user_failed_attempts": await self.get_failed_attempts(email, 5)
        }
    
    async def _record_failed_attempt(self, email: str, ip: str, timestamp: str):
        """Record a failed login attempt"""
        # Record by IP
        ip_key = f"failed_attempts:ip:{ip}"
        await self._append_attempt(ip_key, {"email": email, "timestamp": timestamp})
        
        # Record by email
        email_key = f"failed_attempts:email:{email}"
        await self._append_attempt(email_key, {"ip": ip, "timestamp": timestamp})
    
    async def _append_attempt(self, key: str, attempt: Dict):
        """Append an attempt to the list in Redis"""
        attempts_json = await self.redis.get(key)
        
        if attempts_json:
            try:
                attempts = json.loads(attempts_json)
            except Exception:
                attempts = []
        else:
            attempts = []
        
        # Add new attempt
        attempts.append(attempt)
        
        # Keep only last 100 attempts or attempts within window
        cutoff = (datetime.utcnow() - timedelta(minutes=self.brute_force_window_minutes * 2)).isoformat()
        attempts = [a for a in attempts if a['timestamp'] >= cutoff][-100:]
        
        # Store back
        await self.redis.set(
            key,
            json.dumps(attempts),
            ex=self.brute_force_window_minutes * 60 * 2  # Expire after 2x window
        )
    
    async def _clear_failed_attempts(self, email: str, ip: str):
        """Clear failed attempts after successful login"""
        email_key = f"failed_attempts:email:{email}"
        ip_key = f"failed_attempts:ip:{ip}"
        
        await self.redis.delete(email_key)
        await self.redis.delete(ip_key)
    
    async def _record_user_ip(self, email: str, ip: str):
        """Record IP address for user"""
        key = f"user_ips:{email}"
        ips_json = await self.redis.get(key)
        
        if ips_json:
            try:
                ips = json.loads(ips_json)
            except Exception:
                ips = []
        else:
            ips = []
        
        # Add IP if not already present
        if ip not in ips:
            ips.append(ip)
        
        # Keep last 10 IPs
        ips = ips[-10:]
        
        # Store with 30 day expiration
        await self.redis.set(
            key,
            json.dumps(ips),
            ex=self.new_ip_retention_days * 24 * 60 * 60
        )


# Global instance placeholder (will be initialized in main.py)
login_tracker: Optional[LoginAttemptTracker] = None


def get_login_tracker() -> LoginAttemptTracker:
    """Get the global login tracker instance"""
    if login_tracker is None:
        raise RuntimeError("LoginAttemptTracker not initialized. Call init_login_tracker() first.")
    return login_tracker


async def init_login_tracker(redis_client: redis.Redis):
    """Initialize the global login tracker"""
    global login_tracker
    login_tracker = LoginAttemptTracker(redis_client)
    logger.info("Global LoginAttemptTracker initialized")
