"""
Audit logging functionality for database operations.

This module provides audit logging capabilities to track database operations
for security and compliance purposes.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import json
from pathlib import Path

logger = logging.getLogger(__name__)

# Audit log file location
AUDIT_LOG_DIR = Path("/var/log/employee_cabinet")
AUDIT_LOG_FILE = AUDIT_LOG_DIR / "audit.log"


async def log_audit_event(
    user_id: Optional[int],
    action: str,
    table_name: str,
    record_id: Optional[int] = None,
    changes: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    additional_info: Optional[Dict[str, Any]] = None
) -> None:
    """
    Log database audit events for security and compliance.
    
    Args:
        user_id: ID of the user performing the action (None for system actions)
        action: Type of action (CREATE, UPDATE, DELETE, READ, LOGIN, LOGOUT, etc.)
        table_name: Name of the database table affected
        record_id: ID of the record affected (if applicable)
        changes: Dictionary containing before/after values for updates
        ip_address: IP address of the user
        additional_info: Any additional context information
        
    Example:
        >>> await log_audit_event(
        ...     user_id=123,
        ...     action="UPDATE",
        ...     table_name="users",
        ...     record_id=456,
        ...     changes={"email": {"old": "old@example.com", "new": "new@example.com"}},
        ...     ip_address="192.168.1.100"
        ... )
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    
    audit_entry = {
        "timestamp": timestamp,
        "user_id": user_id,
        "action": action,
        "table_name": table_name,
        "record_id": record_id,
        "ip_address": ip_address,
        "changes": changes,
        "additional_info": additional_info
    }
    
    try:
        # Create audit log directory if it doesn't exist
        AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        
        # Write to audit log file
        with open(AUDIT_LOG_FILE, "a") as f:
            f.write(json.dumps(audit_entry) + "\n")
        
        # Also log to application logger for immediate visibility
        logger.info(
            f"AUDIT: {action} on {table_name}"
            f"{f' (record_id={record_id})' if record_id else ''} "
            f"by user_id={user_id} from {ip_address}"
        )
        
    except PermissionError:
        # If we can't write to /var/log, fall back to local directory
        fallback_log = Path("./audit.log")
        with open(fallback_log, "a") as f:
            f.write(json.dumps(audit_entry) + "\n")
        logger.warning(f"Could not write to {AUDIT_LOG_FILE}, using {fallback_log}")
        
    except Exception as e:
        # Always log audit failures - this is critical for security
        logger.error(f"Failed to write audit log: {e}", exc_info=True)


def log_audit_event_sync(
    user_id: Optional[int],
    action: str,
    table_name: str,
    record_id: Optional[int] = None,
    changes: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    additional_info: Optional[Dict[str, Any]] = None
) -> None:
    """
    Synchronous version of log_audit_event for non-async contexts.
    
    Args:
        Same as log_audit_event
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    
    audit_entry = {
        "timestamp": timestamp,
        "user_id": user_id,
        "action": action,
        "table_name": table_name,
        "record_id": record_id,
        "ip_address": ip_address,
        "changes": changes,
        "additional_info": additional_info
    }
    
    try:
        # Create audit log directory if it doesn't exist
        AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        
        # Write to audit log file
        with open(AUDIT_LOG_FILE, "a") as f:
            f.write(json.dumps(audit_entry) + "\n")
        
        # Also log to application logger
        logger.info(
            f"AUDIT: {action} on {table_name}"
            f"{f' (record_id={record_id})' if record_id else ''} "
            f"by user_id={user_id} from {ip_address}"
        )
        
    except PermissionError:
        # If we can't write to /var/log, fall back to local directory
        fallback_log = Path("./audit.log")
        with open(fallback_log, "a") as f:
            f.write(json.dumps(audit_entry) + "\n")
        logger.warning(f"Could not write to {AUDIT_LOG_FILE}, using {fallback_log}")
        
    except Exception as e:
        logger.error(f"Failed to write audit log: {e}", exc_info=True)


async def log_login_event(
    user_id: int,
    ip_address: str,
    success: bool,
    reason: Optional[str] = None
) -> None:
    """
    Log authentication/login events.
    
    Args:
        user_id: ID of the user attempting login
        ip_address: IP address of the login attempt
        success: Whether the login was successful
        reason: Reason for failure (if applicable)
    """
    action = "LOGIN_SUCCESS" if success else "LOGIN_FAILURE"
    additional_info = {"reason": reason} if reason else None
    
    await log_audit_event(
        user_id=user_id,
        action=action,
        table_name="users",
        record_id=user_id,
        ip_address=ip_address,
        additional_info=additional_info
    )
