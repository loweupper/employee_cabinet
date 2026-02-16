"""
Encryption utilities for sensitive data protection.

This module provides functions for encrypting and decrypting sensitive data
using Fernet symmetric encryption (AES-128 in CBC mode).
"""

from cryptography.fernet import Fernet, InvalidToken
from base64 import urlsafe_b64encode
import hashlib
import logging
from typing import Optional
from core.config import settings

logger = logging.getLogger(__name__)


def get_encryption_key() -> bytes:
    """
    Derive encryption key from SECRET_KEY.
    
    Uses PBKDF2 to derive a stable 32-byte key from the SECRET_KEY setting.
    This ensures the encryption key is deterministic and based on the app's secret.
    
    Returns:
        bytes: 32-byte encryption key suitable for Fernet
    """
    # Derive a stable key from SECRET_KEY using SHA256
    key_material = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    # Fernet requires a base64-encoded 32-byte key
    return urlsafe_b64encode(key_material)


def encrypt_data(data: str) -> Optional[str]:
    """
    Encrypt sensitive data using Fernet symmetric encryption.
    
    Args:
        data: Plain text string to encrypt
        
    Returns:
        Encrypted data as a base64-encoded string, or None if encryption fails
        
    Example:
        >>> encrypted = encrypt_data("sensitive information")
        >>> print(encrypted)
        'gAAAAABh...'
    """
    if not data:
        return None
        
    try:
        fernet = Fernet(get_encryption_key())
        encrypted_bytes = fernet.encrypt(data.encode())
        return encrypted_bytes.decode()
    except Exception as e:
        logger.error(f"Failed to encrypt data: {e}")
        return None


def decrypt_data(encrypted_data: str) -> Optional[str]:
    """
    Decrypt data that was encrypted with encrypt_data().
    
    Args:
        encrypted_data: Base64-encoded encrypted string
        
    Returns:
        Decrypted plain text string, or None if decryption fails
        
    Example:
        >>> decrypted = decrypt_data(encrypted)
        >>> print(decrypted)
        'sensitive information'
    """
    if not encrypted_data:
        return None
        
    try:
        fernet = Fernet(get_encryption_key())
        decrypted_bytes = fernet.decrypt(encrypted_data.encode())
        return decrypted_bytes.decode()
    except InvalidToken:
        logger.error("Failed to decrypt data: Invalid token or key")
        return None
    except Exception as e:
        logger.error(f"Failed to decrypt data: {e}")
        return None


def is_encrypted(data: str) -> bool:
    """
    Check if data appears to be encrypted (basic heuristic).
    
    Args:
        data: String to check
        
    Returns:
        True if data appears to be Fernet-encrypted, False otherwise
        
    Note:
        This is a simple heuristic based on Fernet token format.
        It checks if the string starts with "gAAAAA" which is common for Fernet tokens.
    """
    if not data or not isinstance(data, str):
        return False
    
    # Fernet tokens start with version byte (0x80) which becomes 'gAAAAA' in base64
    return data.startswith('gAAAAA')
