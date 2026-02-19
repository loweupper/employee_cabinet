"""
Enhanced JSON formatters for structured logging
"""
import logging
import socket
import json
from datetime import datetime
import pytz
from typing import Optional
from core.config import settings
import traceback

class EnhancedJSONFormatter(logging.Formatter):
    """
    Унифицированный JSON-форматтер для всех логов.
    Добавляет:
    - timestamp (ISO8601)
    - event_type (имя логгера)
    - service
    - hostname
    - request_id, session_id, user_id
    - ip, user_agent
    - extra (как вложенный объект)
    """

    def __init__(self, environment: str = "development", include_trace: bool = True):
        super().__init__()
        self.environment = environment
        self.include_trace = include_trace

    def format(self, record: logging.LogRecord) -> str:
        # Moscow time
        moscow_tz = pytz.timezone("Europe/Moscow")
        dt = datetime.fromtimestamp(record.created, tz=pytz.utc).astimezone(moscow_tz)

        log_data = {
            "timestamp": dt.isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event_type": record.name,  # app / audit / system / security
            "environment": self.environment,
            "service": settings.APP_NAME,
            "hostname": socket.gethostname(),
        }

        # Основные поля
        for field in ["event", "request_id", "session_id", "user_id", "ip", "user_agent"]:
            value = getattr(record, field, None)
            if value is not None:
                log_data[field] = value

        # Техническая информация
        log_data["module"] = record.module
        log_data["function"] = record.funcName
        log_data["line"] = record.lineno

        # Сообщение
        if isinstance(record.msg, dict):
            log_data["extra"] = record.msg
        else:
            log_data["message"] = record.getMessage()

        # Исключения
        if record.exc_info:
            exc_type = record.exc_info[0].__name__ if record.exc_info[0] else None
            exc_msg = str(record.exc_info[1]) if record.exc_info[1] else None

            log_data["exception"] = {
                "type": exc_type,
                "message": exc_msg,
            }

            if self.include_trace:
                log_data["exception"]["traceback"] = self.formatException(record.exc_info)

        # Stack info
        if record.stack_info and self.include_trace:
            log_data["stack_info"] = record.stack_info

        return json.dumps(log_data, ensure_ascii=False, default=str)



class CompactJSONFormatter(logging.Formatter):
    """
    Compact JSON formatter for production use
    Excludes detailed trace information to reduce log size
    """
    
    def __init__(self, environment: str = "production"):
        """
        Initialize compact JSON formatter
        
        Args:
            environment: Environment name
        """
        super().__init__()
        self.environment = environment
    
    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as compact JSON
        
        Args:
            record: Log record to format
            
        Returns:
            JSON formatted log string
        """
        # Convert time to Moscow timezone
        moscow_tz = pytz.timezone('Europe/Moscow')
        dt = datetime.fromtimestamp(record.created, tz=pytz.utc)
        moscow_time = dt.astimezone(moscow_tz)
        
        # Compact log data
        log_data = {
            "ts": moscow_time.isoformat(),
            "lvl": record.levelname[0],  # First letter only (I, W, E, D)
            "logger": record.name,
            "env": self.environment,
        }
        
        # Add request_id if present
        if hasattr(record, 'request_id'):
            log_data["req_id"] = record.request_id
        
        # Add user_id if present
        if hasattr(record, 'user_id'):
            log_data["user"] = record.user_id
        
        # Handle message
        if isinstance(record.msg, dict):
            log_data.update(record.msg)
        else:
            log_data["msg"] = record.getMessage()
        
        # Add exception type only (no traceback)
        if record.exc_info and record.exc_info[0]:
            log_data["exc"] = record.exc_info[0].__name__
        
        return json.dumps(log_data, ensure_ascii=False, separators=(',', ':'), default=str)


class DevelopmentFormatter(logging.Formatter):
    """
    Human-readable formatter for development
    Color-coded and easy to read
    """
    
    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
        'RESET': '\033[0m'        # Reset
    }
    
    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record for development
        
        Args:
            record: Log record to format
            
        Returns:
            Formatted log string with colors
        """
        # Get color for level
        color = self.COLORS.get(record.levelname, '')
        reset = self.COLORS['RESET']
        
        # Format timestamp
        timestamp = datetime.fromtimestamp(record.created).strftime('%H:%M:%S.%f')[:-3]
        
        # Format message
        if isinstance(record.msg, dict):
            message = json.dumps(record.msg, indent=2, ensure_ascii=False)
        else:
            message = record.getMessage()
        
        # Build log line
        parts = [
            f"{color}{timestamp}{reset}",
            f"{color}[{record.levelname:8}]{reset}",
            f"{record.name}:",
            message
        ]
        
        # Add request_id if present
        if hasattr(record, 'request_id'):
            parts.insert(3, f"[{record.request_id[:8]}]")
        
        log_line = " ".join(parts)
        
        # Add exception if present
        if record.exc_info:
            log_line += f"\n{self.formatException(record.exc_info)}"
        
        return log_line


def get_formatter(
    format_type: str = "json",
    environment: str = "development",
    include_trace: bool = True
) -> logging.Formatter:
    """
    Get appropriate formatter based on configuration
    
    Args:
        format_type: Type of formatter (json, compact, development)
        environment: Environment name
        include_trace: Include exception traces
        
    Returns:
        Configured formatter
    """
    if format_type == "compact":
        return CompactJSONFormatter(environment=environment)
    elif format_type == "development":
        return DevelopmentFormatter()
    else:  # json (default)
        return EnhancedJSONFormatter(
            environment=environment,
            include_trace=include_trace
        )
