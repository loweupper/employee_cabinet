"""
Custom log handlers for enhanced logging
"""
import logging
import os
from logging.handlers import RotatingFileHandler
import gzip
import shutil
from pathlib import Path
from datetime import datetime


class SecurityLogHandler(logging.Handler):
    """
    Handler for security-specific events
    Writes to a separate security.log file
    """
    
    def __init__(self, log_dir: str = "logs", filename: str = "security.log", 
                 max_bytes: int = 10485760, backup_count: int = 30):
        """
        Initialize security log handler
        
        Args:
            log_dir: Directory for log files
            filename: Security log filename
            max_bytes: Maximum log file size (default 10MB)
            backup_count: Number of backup files to keep
        """
        super().__init__()
        
        # Create logs directory if it doesn't exist
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Create rotating file handler
        log_path = self.log_dir / filename
        self.file_handler = RotatingFileHandler(
            str(log_path),
            maxBytes=max_bytes,
            backupCount=backup_count
        )
        
        # Set formatter
        from core.logging.formatters import EnhancedJSONFormatter
        self.file_handler.setFormatter(EnhancedJSONFormatter())
    
    def emit(self, record):
        """Emit a log record to the security log file"""
        try:
            self.file_handler.emit(record)
        except Exception as e:
            self.handleError(record)


class RotatingFileHandlerWithCompression(RotatingFileHandler):
    """
    Rotating file handler that compresses old log files
    """
    
    def __init__(self, filename, mode='a', maxBytes=0, backupCount=0, 
                 encoding=None, delay=False):
        """
        Initialize handler with compression
        
        Args:
            filename: Log file path
            mode: File mode
            maxBytes: Maximum file size before rotation
            backupCount: Number of backup files
            encoding: File encoding
            delay: Delay file opening
        """
        super().__init__(filename, mode, maxBytes, backupCount, encoding, delay)
    
    def doRollover(self):
        """
        Do a rollover and compress the rotated file
        """
        # Close current file
        if self.stream:
            self.stream.close()
            self.stream = None
        
        # Rotate files
        if self.backupCount > 0:
            for i in range(self.backupCount - 1, 0, -1):
                sfn = self.rotation_filename("%s.%d" % (self.baseFilename, i))
                dfn = self.rotation_filename("%s.%d" % (self.baseFilename, i + 1))
                
                # Compress if exists
                if os.path.exists(sfn):
                    # Check if already compressed
                    if not sfn.endswith('.gz'):
                        compressed_sfn = sfn + '.gz'
                        self._compress_file(sfn, compressed_sfn)
                        sfn = compressed_sfn
                    
                    if os.path.exists(dfn):
                        os.remove(dfn)
                    os.rename(sfn, dfn)
            
            # Rotate current file to .1
            dfn = self.rotation_filename(self.baseFilename + ".1")
            if os.path.exists(dfn):
                os.remove(dfn)
            
            if os.path.exists(self.baseFilename):
                os.rename(self.baseFilename, dfn)
        
        # Open new log file
        if not self.delay:
            self.stream = self._open()
    
    def _compress_file(self, source: str, dest: str):
        """
        Compress a file using gzip
        
        Args:
            source: Source file path
            dest: Destination compressed file path
        """
        try:
            with open(source, 'rb') as f_in:
                with gzip.open(dest, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            # Remove original file after successful compression
            os.remove(source)
            
            logging.debug(f"Compressed log file: {source} -> {dest}")
        except Exception as e:
            logging.error(f"Failed to compress log file {source}: {e}")


def setup_log_handlers(
    log_dir: str = "logs",
    max_bytes: int = 10485760,  # 10MB
    backup_count: int = 30,
    enable_compression: bool = True
) -> dict:
    """
    Setup custom log handlers
    
    Args:
        log_dir: Directory for log files
        max_bytes: Maximum log file size
        backup_count: Number of backup files
        enable_compression: Enable log compression
        
    Returns:
        Dictionary of configured handlers
    """
    # Create log directory
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    handlers = {}
    
    # Security handler
    security_handler = SecurityLogHandler(
        log_dir=log_dir,
        filename="security.log",
        max_bytes=max_bytes,
        backup_count=backup_count
    )
    security_handler.setLevel(logging.WARNING)
    handlers['security'] = security_handler
    
    # Application handler with compression
    if enable_compression:
        app_handler = RotatingFileHandlerWithCompression(
            str(log_path / "app.log"),
            maxBytes=max_bytes,
            backupCount=backup_count
        )
    else:
        app_handler = RotatingFileHandler(
            str(log_path / "app.log"),
            maxBytes=max_bytes,
            backupCount=backup_count
        )
    
    from core.logging.formatters import EnhancedJSONFormatter
    app_handler.setFormatter(EnhancedJSONFormatter())
    app_handler.setLevel(logging.INFO)
    handlers['app'] = app_handler
    
    # Audit handler
    if enable_compression:
        audit_handler = RotatingFileHandlerWithCompression(
            str(log_path / "audit.log"),
            maxBytes=max_bytes,
            backupCount=backup_count
        )
    else:
        audit_handler = RotatingFileHandler(
            str(log_path / "audit.log"),
            maxBytes=max_bytes,
            backupCount=backup_count
        )
    
    audit_handler.setFormatter(EnhancedJSONFormatter())
    audit_handler.setLevel(logging.INFO)
    handlers['audit'] = audit_handler
    
    return handlers
