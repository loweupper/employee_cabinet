"""
Custom log handlers for enhanced logging
"""
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler
from core.logging.formatters import EnhancedJSONFormatter
import gzip
import shutil
import os


class RotatingFileHandlerWithCompression(RotatingFileHandler):
    """Rotating file handler that compresses old log files"""

    def doRollover(self):
        if self.stream:
            self.stream.close()
            self.stream = None

        if self.backupCount > 0:
            for i in range(self.backupCount - 1, 0, -1):
                sfn = self.rotation_filename(f"{self.baseFilename}.{i}")
                dfn = self.rotation_filename(f"{self.baseFilename}.{i + 1}")

                if os.path.exists(sfn):
                    if not sfn.endswith(".gz"):
                        compressed_sfn = sfn + ".gz"
                        self._compress_file(sfn, compressed_sfn)
                        sfn = compressed_sfn

                    if os.path.exists(dfn):
                        os.remove(dfn)
                    os.rename(sfn, dfn)

            dfn = self.rotation_filename(self.baseFilename + ".1")
            if os.path.exists(dfn):
                os.remove(dfn)
            if os.path.exists(self.baseFilename):
                os.rename(self.baseFilename, dfn)

        if not self.delay:
            self.stream = self._open()

    def _compress_file(self, source: str, dest: str):
        try:
            with open(source, "rb") as f_in:
                with gzip.open(dest, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            os.remove(source)
        except Exception as e:
            logging.error(f"Failed to compress {source}: {e}")


class LoggerNameFilter(logging.Filter):
    def __init__(self, logger_name: str):
        super().__init__()
        self.logger_name = logger_name

    def filter(self, record: logging.LogRecord) -> bool:
        return record.name == self.logger_name


def setup_log_handlers(
    base_dir: str = "/app/logs",
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 30,
    enable_compression: bool = True
) -> dict:
    """Настройка обработчиков для 3 логгеров (app, security, system)"""
    
    base = Path(base_dir)
    
    # Создаём папки
    for d in ["app", "security", "system"]:
        (base / d).mkdir(parents=True, exist_ok=True)
    
    handlers = {}
    handler_class = RotatingFileHandlerWithCompression if enable_compression else RotatingFileHandler
    
    # App logger
    app_handler = handler_class(str(base / "app" / "app.log"), maxBytes=max_bytes, backupCount=backup_count)
    app_handler.setFormatter(EnhancedJSONFormatter())
    app_handler.setLevel(logging.INFO)
    app_handler.addFilter(LoggerNameFilter("app"))
    handlers["app"] = app_handler
    
    # Security logger
    security_handler = handler_class(str(base / "security" / "security.log"), maxBytes=max_bytes, backupCount=backup_count)
    security_handler.setFormatter(EnhancedJSONFormatter())
    security_handler.setLevel(logging.WARNING)
    security_handler.addFilter(LoggerNameFilter("security"))
    handlers["security"] = security_handler
    
    # System logger
    system_handler = handler_class(str(base / "system" / "system.log"), maxBytes=max_bytes, backupCount=backup_count)
    system_handler.setFormatter(EnhancedJSONFormatter())
    system_handler.setLevel(logging.INFO)
    system_handler.addFilter(LoggerNameFilter("system"))
    handlers["system"] = system_handler
    
    return handlers