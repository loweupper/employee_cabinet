"""
Password hashing and validation utilities using bcrypt.

This module provides secure password hashing and verification using bcrypt
with proper salt rounds for security.
"""

import re
import bcrypt
from typing import Tuple, List


def hash_password(password: str, rounds: int = 12) -> str:
    """
    Hash password using bcrypt with configurable salt rounds.
    
    Args:
        password: Plain text password to hash
        rounds: Number of salt rounds (12-14 recommended, default=12)
        
    Returns:
        Hashed password as a string
        
    Example:
        >>> hashed = hash_password("my_secure_password")
        >>> print(hashed)
        '$2b$12$...'
    """
    if not password:
        raise ValueError("Password cannot be empty")
    
    # Generate salt with specified rounds
    salt = bcrypt.gensalt(rounds=rounds)
    
    # Hash the password
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its bcrypt hash.
    
    Args:
        plain_password: Plain text password to verify
        hashed_password: Bcrypt hash to verify against
        
    Returns:
        True if password matches, False otherwise
        
    Example:
        >>> hashed = hash_password("my_password")
        >>> verify_password("my_password", hashed)
        True
        >>> verify_password("wrong_password", hashed)
        False
    """
    if not plain_password or not hashed_password:
        return False
    
    try:
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except Exception:
        return False


def validate_password_strength(password: str) -> Tuple[bool, List[str]]:
    """
    Validate password strength according to security best practices.
    
    Requirements:
    - At least 8 characters long
    - Contains at least one uppercase letter
    - Contains at least one lowercase letter
    - Contains at least one digit
    - Contains at least one special character
    
    Args:
        password: Password to validate
        
    Returns:
        Tuple of (is_valid, list_of_errors)
        
    Example:
        >>> valid, errors = validate_password_strength("WeakPass")
        >>> print(valid, errors)
        False ['Password must be at least 8 characters', ...]
    """
    errors = []
    
    if len(password) < 8:
        errors.append("Password must be at least 8 characters long")
    
    if not re.search(r'[A-Z]', password):
        errors.append("Password must contain at least one uppercase letter")
    
    if not re.search(r'[a-z]', password):
        errors.append("Password must contain at least one lowercase letter")
    
    if not re.search(r'\d', password):
        errors.append("Password must contain at least one digit")
    
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        errors.append("Password must contain at least one special character")
    
    return len(errors) == 0, errors


def check_password_common_patterns(password: str) -> Tuple[bool, List[str]]:
    """
    Check for common weak password patterns.
    
    Args:
        password: Password to check
        
    Returns:
        Tuple of (is_safe, list_of_warnings)
    """
    warnings = []
    
    # Common weak patterns
    common_passwords = [
        'password', 'Password123', '12345678', 'qwerty',
        'abc123', 'password1', 'admin', 'letmein'
    ]
    
    # Check against common passwords (case-insensitive)
    if password.lower() in [p.lower() for p in common_passwords]:
        warnings.append("Password is too common and easily guessable")
    
    # Check for repeated characters
    if re.search(r'(.)\1{2,}', password):
        warnings.append("Password contains repeated characters")
    
    # Check for sequential numbers
    if re.search(r'(012|123|234|345|456|567|678|789)', password):
        warnings.append("Password contains sequential numbers")
    
    # Check for sequential letters
    if re.search(r'(abc|bcd|cde|def|efg|fgh)', password.lower()):
        warnings.append("Password contains sequential letters")
    
    return len(warnings) == 0, warnings


def get_password_requirements() -> str:
    """
    Get a user-friendly description of password requirements.
    
    Returns:
        String describing password requirements
    """
    return (
        "Password must:\n"
        "- Be at least 8 characters long\n"
        "- Contain at least one uppercase letter (A-Z)\n"
        "- Contain at least one lowercase letter (a-z)\n"
        "- Contain at least one digit (0-9)\n"
        "- Contain at least one special character (!@#$%^&*(),.?\":{}|<>)\n"
        "- Not be a common or easily guessable password"
    )
