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


# ============================================================
#  RotatingFileHandler with GZIP compression
# ============================================================

class RotatingFileHandlerWithCompression(RotatingFileHandler):
    """
    Rotating file handler that compresses old log files
    """

    def doRollover(self):
        # Close current file
        if self.stream:
            self.stream.close()
            self.stream = None

        # Rotate files
        if self.backupCount > 0:
            for i in range(self.backupCount - 1, 0, -1):
                sfn = self.rotation_filename(f"{self.baseFilename}.{i}")
                dfn = self.rotation_filename(f"{self.baseFilename}.{i + 1}")

                if os.path.exists(sfn):
                    # Compress if not already compressed
                    if not sfn.endswith(".gz"):
                        compressed_sfn = sfn + ".gz"
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
        """Compress a file using gzip"""
        try:
            with open(source, "rb") as f_in:
                with gzip.open(dest, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)

            os.remove(source)
            logging.debug(f"Compressed log file: {source} -> {dest}")

        except Exception as e:
            logging.error(f"Failed to compress log file {source}: {e}")


# ============================================================
#  Setup log handlers for all categories
# ============================================================

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

    base = Path(base_dir)

    app_dir = base / "app"
    audit_dir = base / "audit"
    security_dir = base / "security"
    system_dir = base / "system"

    for d in [app_dir, audit_dir, security_dir, system_dir]:
        d.mkdir(parents=True, exist_ok=True)

    handlers = {}

    # -------------------------
    # APP LOG
    # -------------------------
    app_handler = (
        RotatingFileHandlerWithCompression(str(app_dir / "app.log"), maxBytes=max_bytes, backupCount=backup_count)
        if enable_compression else
        RotatingFileHandler(str(app_dir / "app.log"), maxBytes=max_bytes, backupCount=backup_count)
    )
    app_handler.setFormatter(EnhancedJSONFormatter())
    app_handler.setLevel(logging.INFO)
    app_handler.addFilter(LoggerNameFilter("app"))
    handlers["app"] = app_handler

    # -------------------------
    # AUDIT LOG
    # -------------------------
    audit_handler = (
        RotatingFileHandlerWithCompression(str(audit_dir / "audit.log"), maxBytes=max_bytes, backupCount=backup_count)
        if enable_compression else
        RotatingFileHandler(str(audit_dir / "audit.log"), maxBytes=max_bytes, backupCount=backup_count)
    )
    audit_handler.setFormatter(EnhancedJSONFormatter())
    audit_handler.setLevel(logging.INFO)
    audit_handler.addFilter(LoggerNameFilter("audit"))
    handlers["audit"] = audit_handler

    # -------------------------
    # SECURITY LOG
    # -------------------------
    security_handler = (
        RotatingFileHandlerWithCompression(str(security_dir / "security.log"), maxBytes=max_bytes, backupCount=backup_count)
        if enable_compression else
        RotatingFileHandler(str(security_dir / "security.log"), maxBytes=max_bytes, backupCount=backup_count)
    )
    security_handler.setFormatter(EnhancedJSONFormatter())
    security_handler.setLevel(logging.WARNING)
    security_handler.addFilter(LoggerNameFilter("security"))
    handlers["security"] = security_handler

    # -------------------------
    # SYSTEM LOG
    # -------------------------
    system_handler = (
        RotatingFileHandlerWithCompression(str(system_dir / "system.log"), maxBytes=max_bytes, backupCount=backup_count)
        if enable_compression else
        RotatingFileHandler(str(system_dir / "system.log"), maxBytes=max_bytes, backupCount=backup_count)
    )
    system_handler.setFormatter(EnhancedJSONFormatter())
    system_handler.setLevel(logging.INFO)
    system_handler.addFilter(LoggerNameFilter("system"))
    handlers["system"] = system_handler

    return handlers
