"""
Log filters for security and PII protection
"""
import logging
import re
from typing import Set, Pattern


class SensitiveDataFilter(logging.Filter):
    """
    Filter to redact sensitive data from log messages
    Removes passwords, tokens, API keys, and other sensitive information
    """
    
    # Patterns for sensitive data
    SENSITIVE_PATTERNS = [
        # Password fields
        (re.compile(r'"password"\s*:\s*"[^"]*"', re.IGNORECASE), '"password": "***REDACTED***"'),
        (re.compile(r"'password'\s*:\s*'[^']*'", re.IGNORECASE), "'password': '***REDACTED***'"),
        (re.compile(r'password=\S+', re.IGNORECASE), 'password=***REDACTED***'),
        
        # Token fields
        (re.compile(r'"token"\s*:\s*"[^"]*"', re.IGNORECASE), '"token": "***REDACTED***"'),
        (re.compile(r"'token'\s*:\s*'[^']*'", re.IGNORECASE), "'token': '***REDACTED***'"),
        (re.compile(r'token=\S+', re.IGNORECASE), 'token=***REDACTED***'),
        
        # Bearer tokens
        (re.compile(r'Bearer\s+[\w\-\.]+', re.IGNORECASE), 'Bearer ***REDACTED***'),
        
        # API keys
        (re.compile(r'"api_key"\s*:\s*"[^"]*"', re.IGNORECASE), '"api_key": "***REDACTED***"'),
        (re.compile(r"'api_key'\s*:\s*'[^']*'", re.IGNORECASE), "'api_key': '***REDACTED***'"),
        (re.compile(r'api_key=\S+', re.IGNORECASE), 'api_key=***REDACTED***'),
        
        # Secret keys
        (re.compile(r'"secret"\s*:\s*"[^"]*"', re.IGNORECASE), '"secret": "***REDACTED***"'),
        (re.compile(r"'secret'\s*:\s*'[^']*'", re.IGNORECASE), "'secret': '***REDACTED***'"),
        
        # Authorization headers
        (re.compile(r'Authorization:\s*\S+', re.IGNORECASE), 'Authorization: ***REDACTED***'),
        
        # Credit card numbers (basic pattern)
        (re.compile(r'\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b'), '****-****-****-****'),
        
        # Social security numbers (US format)
        (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), '***-**-****'),
    ]
    
    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter log record to redact sensitive data
        
        Args:
            record: Log record to filter
            
        Returns:
            True (always pass through, but modify record)
        """
        # Redact sensitive data from message
        if hasattr(record, 'msg'):
            if isinstance(record.msg, str):
                record.msg = self._redact_sensitive_data(record.msg)
            elif isinstance(record.msg, dict):
                record.msg = self._redact_dict(record.msg)
        
        # Redact from args if present
        if hasattr(record, 'args') and record.args:
            if isinstance(record.args, dict):
                record.args = self._redact_dict(record.args)
            elif isinstance(record.args, (list, tuple)):
                record.args = tuple(
                    self._redact_sensitive_data(str(arg)) if isinstance(arg, str) else arg
                    for arg in record.args
                )
        
        return True
    
    def _redact_sensitive_data(self, text: str) -> str:
        """
        Redact sensitive data from text
        
        Args:
            text: Text to redact
            
        Returns:
            Redacted text
        """
        for pattern, replacement in self.SENSITIVE_PATTERNS:
            text = pattern.sub(replacement, text)
        return text
    
    def _redact_dict(self, data: dict) -> dict:
        """
        Redact sensitive data from dictionary
        
        Args:
            data: Dictionary to redact
            
        Returns:
            Redacted dictionary
        """
        redacted = {}
        sensitive_keys = {'password', 'token', 'api_key', 'secret', 'authorization', 'secret_key'}
        
        for key, value in data.items():
            key_lower = key.lower()
            
            if key_lower in sensitive_keys or 'password' in key_lower or 'token' in key_lower:
                redacted[key] = '***REDACTED***'
            elif isinstance(value, dict):
                redacted[key] = self._redact_dict(value)
            elif isinstance(value, str):
                redacted[key] = self._redact_sensitive_data(value)
            else:
                redacted[key] = value
        
        return redacted


class PIIFilter(logging.Filter):
    """
    Filter to mask Personally Identifiable Information (PII)
    Partially masks emails, phone numbers, and other PII
    """
    
    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter log record to mask PII
        
        Args:
            record: Log record to filter
            
        Returns:
            True (always pass through, but modify record)
        """
        # Mask PII in message
        if hasattr(record, 'msg'):
            if isinstance(record.msg, str):
                record.msg = self._mask_pii(record.msg)
            elif isinstance(record.msg, dict):
                record.msg = self._mask_dict(record.msg)
        
        return True
    
    def _mask_pii(self, text: str) -> str:
        """
        Mask PII in text
        
        Args:
            text: Text to mask
            
        Returns:
            Masked text
        """
        # Mask email addresses (keep first character and domain)
        text = re.sub(
            r'\b([a-zA-Z0-9])[a-zA-Z0-9._-]*@([a-zA-Z0-9.-]+)\b',
            r'\1***@\2',
            text
        )
        
        # Mask phone numbers (keep last 4 digits)
        text = re.sub(
            r'\b(\+?\d{1,3}[\s-]?)?\(?\d{3}\)?[\s-]?\d{3}[\s-]?(\d{4})\b',
            r'***-***-\2',
            text
        )
        
        return text
    
    def _mask_dict(self, data: dict) -> dict:
        """
        Mask PII in dictionary
        
        Args:
            data: Dictionary to mask
            
        Returns:
            Masked dictionary
        """
        masked = {}
        
        for key, value in data.items():
            if isinstance(value, dict):
                masked[key] = self._mask_dict(value)
            elif isinstance(value, str):
                # Check if key suggests PII
                if key.lower() in {'email', 'phone', 'telephone', 'mobile'}:
                    if '@' in value:
                        masked[key] = self._mask_email(value)
                    else:
                        masked[key] = self._mask_pii(value)
                else:
                    masked[key] = value
            else:
                masked[key] = value
        
        return masked
    
    def _mask_email(self, email: str) -> str:
        """
        Mask email address
        
        Args:
            email: Email to mask
            
        Returns:
            Masked email (e.g., u***@example.com)
        """
        try:
            if '@' not in email:
                return '***@invalid'
            
            local, domain = email.split('@', 1)
            if len(local) <= 1:
                masked_local = '*'
            else:
                masked_local = local[0] + '***'
            
            return f"{masked_local}@{domain}"
        except Exception:
            return '***@masked'


class SecurityEventFilter(logging.Filter):
    """
    Filter to route security events to separate handler
    Identifies security-related log records
    """
    
    SECURITY_EVENTS = {
        'security_alert',
        'brute_force',
        'failed_login',
        'unauthorized_access',
        'privilege_escalation',
        'suspicious_activity',
        'sql_injection',
        'xss_attempt',
        'account_lockout',
        'new_ip_login',
        'security_event',
    }
    
    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter security events
        
        Args:
            record: Log record to check
            
        Returns:
            True if security event, False otherwise
        """
        # Check if this is a security event
        is_security = False
        
        # Check in message dict
        if isinstance(record.msg, dict):
            event_type = record.msg.get('event', '')
            is_security = any(sec_event in event_type.lower() for sec_event in self.SECURITY_EVENTS)
        
        # Check in message string
        elif isinstance(record.msg, str):
            msg_lower = record.msg.lower()
            is_security = any(sec_event in msg_lower for sec_event in self.SECURITY_EVENTS)
        
        # Mark as security event
        if is_security:
            record.security_event = True
        
        return True


def get_logger(name: str, enable_pii_masking: bool = True, enable_sensitive_redaction: bool = True) -> logging.Logger:
    """
    Get a configured logger with appropriate filters
    
    Args:
        name: Logger name
        enable_pii_masking: Enable PII masking filter
        enable_sensitive_redaction: Enable sensitive data redaction
        
    Returns:
        Configured logger
    """
    logger = logging.getLogger(name)
    
    # Add filters if not already present
    if enable_sensitive_redaction:
        has_sensitive_filter = any(isinstance(f, SensitiveDataFilter) for f in logger.filters)
        if not has_sensitive_filter:
            logger.addFilter(SensitiveDataFilter())
    
    if enable_pii_masking:
        has_pii_filter = any(isinstance(f, PIIFilter) for f in logger.filters)
        if not has_pii_filter:
            logger.addFilter(PIIFilter())
    
    # Add security event filter
    has_security_filter = any(isinstance(f, SecurityEventFilter) for f in logger.filters)
    if not has_security_filter:
        logger.addFilter(SecurityEventFilter())
    
    return logger
