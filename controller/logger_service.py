"""Structured logging and reporting service for ODIS Obliterator (TASK-006).

Manages batch session logging, chronologically writes operational logs to execution.log,
updates and writes summary.json reports, and stores diagnostic error screenshots
in session-isolated directories under logs/run_YYYY-MM-DD_HH-mm-ss/.
"""

import base64
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import threading
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field

from controller.config import Settings, get_settings

# Module-level logger for internal service messages
_internal_logger = logging.getLogger("controller.logger_service")


def sanitize_filename(name: str) -> str:
    """Sanitize a function name or identifier for safe filesystem usage.

    Replaces non-alphanumeric/hyphen/underscore character sequences with a single underscore,
    preserving existing underscores (such as ____ in standard ODIS GFF naming).

    Args:
        name: Raw identifier or function name.

    Returns:
        Sanitized string safe for Windows and Unix file paths.
    """
    if not name:
        return "unnamed_task"
    sanitized = re.sub(r"[^\w\-]+", "_", name.strip())
    sanitized = sanitized.strip("_")
    return sanitized or "unnamed_task"


class SummaryReport(BaseModel):
    """Structured session summary metrics model matching DESIGN.md specification."""

    total: int = Field(default=0, ge=0, description="Total number of GFF tasks in batch.")
    success: int = Field(default=0, ge=0, description="Count of successfully sanitized tasks.")
    failed: int = Field(default=0, ge=0, description="Count of failed tasks.")
    skipped: int = Field(default=0, ge=0, description="Count of skipped tasks.")
    start_time: Optional[str] = Field(default=None, description="ISO 8601 start timestamp.")
    end_time: Optional[str] = Field(default=None, description="ISO 8601 completion timestamp.")
    total_blocks_modified: int = Field(default=0, ge=0, description="Total count of sanitized blocks.")
    session_id: Optional[str] = Field(default=None, description="Session identifier.")
    blocks_modified_breakdown: Optional[Dict[str, int]] = Field(
        default=None,
        description="Detailed modification counts per block type (message, question, comment).",
    )
    is_completed: bool = Field(default=False, description="Whether the batch execution is completed.")

    def to_standard_dict(self) -> Dict[str, Any]:
        """Export as canonical dictionary matching DESIGN.md Section 5."""
        out: Dict[str, Any] = {
            "total": self.total,
            "success": self.success,
            "failed": self.failed,
            "skipped": self.skipped,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_blocks_modified": self.total_blocks_modified,
        }
        if self.session_id is not None:
            out["session_id"] = self.session_id
        if self.blocks_modified_breakdown is not None:
            out["blocks_modified_breakdown"] = self.blocks_modified_breakdown
        if self.is_completed:
            out["is_completed"] = self.is_completed
        return out


class StructuredLogFormatter(logging.Formatter):
    """Custom formatter producing structured, timestamped log lines for execution.log."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        level = record.levelname.upper().ljust(7)
        task_id = getattr(record, "task_id", None)
        session_id = getattr(record, "session_id", None)

        tags = []
        if session_id:
            tags.append(f"session={session_id}")
        if task_id:
            tags.append(f"task={task_id}")

        tag_str = f" [{' '.join(tags)}]" if tags else ""
        return f"[{timestamp}] [{level}]{tag_str} {record.getMessage()}"


class LoggerService:
    """Thread-safe logging, reporting, and error screenshot management service."""

    def __init__(
        self,
        session_id: Optional[str] = None,
        settings: Optional[Settings] = None,
        logs_dir: Optional[Path] = None,
    ):
        """Initialize LoggerService.

        Args:
            session_id: Optional active session identifier (e.g. run_2026-09-22_15-00-00).
            settings: Application settings instance.
            logs_dir: Base logs directory override.
        """
        self.settings = settings or get_settings()
        self.logs_dir = Path(logs_dir) if logs_dir is not None else self.settings.logs_dir
        self.session_id: Optional[str] = None
        self._file_handler: Optional[logging.FileHandler] = None
        self._session_logger: Optional[logging.Logger] = None
        self._lock = threading.RLock()

        if session_id:
            self.init_session(session_id)

    @property
    def is_initialized(self) -> bool:
        """Whether a session is actively initialized."""
        return self.session_id is not None

    def get_session_dir(self, session_id: Optional[str] = None) -> Path:
        """Return the directory path for the given or current session ID."""
        target_id = session_id or self.session_id
        if not target_id:
            raise ValueError("No session ID specified or initialized.")
        return self.logs_dir / target_id

    def get_errors_dir(self, session_id: Optional[str] = None) -> Path:
        """Return the errors directory path for the given or current session ID."""
        return self.get_session_dir(session_id) / "errors"

    def get_log_path(self, session_id: Optional[str] = None) -> Path:
        """Return the path to execution.log for the given or current session ID."""
        return self.get_session_dir(session_id) / "execution.log"

    def get_summary_path(self, session_id: Optional[str] = None) -> Path:
        """Return the path to summary.json for the given or current session ID."""
        return self.get_session_dir(session_id) / "summary.json"

    def init_session(self, session_id: str) -> Path:
        """Initialize directory layout and file logging handler for a session.

        Creates:
        - `logs/{session_id}/`
        - `logs/{session_id}/errors/`
        - `logs/{session_id}/execution.log` (attaches dedicated handler)

        Args:
            session_id: Session run identifier (e.g. run_2026-09-22_15-00-00).

        Returns:
            Path to the session directory.
        """
        with self._lock:
            if self.session_id == session_id and self._session_logger is not None:
                return self.get_session_dir()

            # Close existing handler if switching sessions
            self.close()

            self.session_id = session_id
            session_dir = self.get_session_dir(session_id)
            errors_dir = self.get_errors_dir(session_id)

            session_dir.mkdir(parents=True, exist_ok=True)
            errors_dir.mkdir(parents=True, exist_ok=True)

            log_file = self.get_log_path(session_id)

            # Setup dedicated session logger
            logger_name = f"odis_session.{session_id}"
            session_logger = logging.getLogger(logger_name)
            session_logger.setLevel(logging.DEBUG)
            session_logger.propagate = False

            # Remove old handlers from logger if any exist
            for handler in list(session_logger.handlers):
                session_logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass

            # Create file handler with UTF-8 encoding
            file_handler = logging.FileHandler(str(log_file), mode="a", encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(StructuredLogFormatter())

            session_logger.addHandler(file_handler)

            self._file_handler = file_handler
            self._session_logger = session_logger

            _internal_logger.debug(f"LoggerService initialized for session: {session_id} -> {session_dir}")
            return session_dir

    def close(self) -> None:
        """Flush and close active logging file handlers."""
        with self._lock:
            if self._file_handler is not None:
                try:
                    self._file_handler.flush()
                    self._file_handler.close()
                except Exception as exc:
                    _internal_logger.warning(f"Error closing log file handler: {exc}")
                if self._session_logger is not None:
                    self._session_logger.removeHandler(self._file_handler)
                self._file_handler = None
            self._session_logger = None

    def __enter__(self) -> "LoggerService":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # --- Core Logging Methods ---

    def log(
        self,
        level: int,
        msg: str,
        task_id: Optional[str] = None,
        **extra_fields: Any,
    ) -> None:
        """Log a message to the session's execution.log.

        Args:
            level: Logging level (logging.INFO, logging.WARNING, etc.).
            msg: Log message string.
            task_id: Optional task identifier context.
            extra_fields: Optional additional key-value attributes.
        """
        with self._lock:
            if self._session_logger is None:
                if self.session_id:
                    self.init_session(self.session_id)
                else:
                    _internal_logger.log(level, msg)
                    return

            extra = {"task_id": task_id, "session_id": self.session_id}
            extra.update(extra_fields)
            self._session_logger.log(level, msg, extra=extra)
            if self._file_handler:
                self._file_handler.flush()

    def info(self, msg: str, task_id: Optional[str] = None, **kwargs) -> None:
        """Log an INFO level message."""
        self.log(logging.INFO, msg, task_id=task_id, **kwargs)

    def warning(self, msg: str, task_id: Optional[str] = None, **kwargs) -> None:
        """Log a WARNING level message."""
        self.log(logging.WARNING, msg, task_id=task_id, **kwargs)

    def error(self, msg: str, task_id: Optional[str] = None, **kwargs) -> None:
        """Log an ERROR level message."""
        self.log(logging.ERROR, msg, task_id=task_id, **kwargs)

    def debug(self, msg: str, task_id: Optional[str] = None, **kwargs) -> None:
        """Log a DEBUG level message."""
        self.log(logging.DEBUG, msg, task_id=task_id, **kwargs)

    # --- Structured Operational Event Logging ---

    def log_session_start(
        self,
        session_id: str,
        total_gff: int,
        gff_names: Optional[List[str]] = None,
        resumed: bool = False,
    ) -> None:
        """Log session initialization or resumption event.

        Args:
            session_id: Session run identifier.
            total_gff: Total count of tasks in queue.
            gff_names: Optional preview list of task names.
            resumed: True if session was restored from checkpoint.
        """
        if not self.is_initialized or self.session_id != session_id:
            self.init_session(session_id)

        action = "RESUMED" if resumed else "STARTED"
        self.info(f"=== BATCH SESSION {action}: {session_id} ===")
        self.info(f"Total GFF functions in batch: {total_gff} (Resumed: {resumed})")
        if gff_names:
            preview_count = min(5, len(gff_names))
            preview_str = ", ".join(gff_names[:preview_count])
            if len(gff_names) > preview_count:
                preview_str += f" ... (+{len(gff_names) - preview_count} more)"
            self.debug(f"Queued GFF items: [{preview_str}]")

    def log_task_start(self, task_id: str, task_name: str) -> None:
        """Log the start of a GFF task execution.

        Args:
            task_id: Unique task identifier (e.g. GFF_001).
            task_name: Diagnostic function name.
        """
        self.info(f"Starting task {task_id}: {task_name}", task_id=task_id)

    def log_task_complete(
        self,
        task_id: str,
        task_name: str,
        status: str,
        blocks_modified: Optional[Dict[str, int]] = None,
        duration_seconds: Optional[float] = None,
        error_details: Optional[str] = None,
        error_screenshot_path: Optional[str] = None,
    ) -> None:
        """Log task completion, failure, or skip with execution metrics.

        Args:
            task_id: Task identifier.
            task_name: Diagnostic function name.
            status: Terminal status ('SUCCESS', 'FAILED', 'SKIPPED').
            blocks_modified: Counts of modified blocks.
            duration_seconds: Execution duration.
            error_details: Failure or error details.
            error_screenshot_path: Path to saved diagnostic screenshot.
        """
        status_norm = str(status).upper()
        duration_str = f" (duration: {duration_seconds:.2f}s)" if duration_seconds is not None else ""

        if status_norm == "SUCCESS":
            blocks_info = f"blocks_modified={blocks_modified}" if blocks_modified is not None else ""
            self.info(
                f"Task {task_id} ({task_name}) SUCCESS{duration_str}. {blocks_info}".strip(),
                task_id=task_id,
            )
        elif status_norm == "FAILED":
            err_msg = f" Error: {error_details}" if error_details else ""
            scr_msg = f" Screenshot: {error_screenshot_path}" if error_screenshot_path else ""
            self.error(
                f"Task {task_id} ({task_name}) FAILED{duration_str}.{err_msg}{scr_msg}",
                task_id=task_id,
            )
        elif status_norm == "SKIPPED":
            reason = f" Reason: {error_details}" if error_details else ""
            self.warning(
                f"Task {task_id} ({task_name}) SKIPPED{duration_str}.{reason}",
                task_id=task_id,
            )
        else:
            self.info(
                f"Task {task_id} ({task_name}) {status_norm}{duration_str}",
                task_id=task_id,
            )

    def log_session_end(self, summary: Union[SummaryReport, BaseModel, Dict[str, Any], Any]) -> None:
        """Log session completion with summary statistics.

        Args:
            summary: Summary report instance, Pydantic model, or dictionary.
        """
        data: Dict[str, Any]
        if isinstance(summary, SummaryReport):
            data = summary.to_standard_dict()
        elif isinstance(summary, BaseModel):
            data = summary.model_dump()
        elif isinstance(summary, dict):
            data = summary
        else:
            data = getattr(summary, "__dict__", {})

        total = data.get("total", 0)
        success = data.get("success", 0)
        failed = data.get("failed", 0)
        skipped = data.get("skipped", 0)
        blocks = data.get("total_blocks_modified", 0)

        self.info("=== BATCH SESSION COMPLETED ===")
        self.info(
            f"Summary: Total={total}, Success={success}, Failed={failed}, "
            f"Skipped={skipped}, Total Blocks Sanitized={blocks}"
        )

    # --- Error Screenshot Storage ---

    def save_error_screenshot(
        self,
        task_name: str,
        screenshot_data: Union[str, bytes],
        timestamp: Optional[datetime] = None,
        session_id: Optional[str] = None,
    ) -> Path:
        """Save a diagnostic error screenshot to the session's errors/ folder.

        File naming convention: `[Nome_Funzione]_[timestamp].png` (e.g. `Check_battery_20260922_150000.png`).

        Args:
            task_name: Diagnostic function name (will be sanitized).
            screenshot_data: Image content as raw bytes or Base64 string (supports data URI scheme).
            timestamp: Optional timestamp for filename (defaults to current UTC/local time).
            session_id: Optional session ID override.

        Returns:
            Resolved Path to the saved screenshot file.

        Raises:
            ValueError: If screenshot_data is empty or invalid.
        """
        with self._lock:
            target_session_id = session_id or self.session_id
            if not target_session_id:
                raise ValueError("Cannot save screenshot: No session initialized.")

            errors_dir = self.get_errors_dir(target_session_id)
            errors_dir.mkdir(parents=True, exist_ok=True)

            # Decode image bytes
            if isinstance(screenshot_data, bytes):
                image_bytes = screenshot_data
            elif isinstance(screenshot_data, str):
                raw_b64 = screenshot_data.strip()
                if not raw_b64:
                    raise ValueError("Screenshot base64 string is empty.")
                if "," in raw_b64:
                    # Strip data URI prefix: data:image/png;base64,...
                    raw_b64 = raw_b64.split(",", 1)[1].strip()
                try:
                    image_bytes = base64.b64decode(raw_b64)
                except Exception as exc:
                    raise ValueError(f"Failed to decode base64 screenshot: {exc}") from exc
            else:
                raise ValueError(f"Unsupported screenshot data type: {type(screenshot_data)}")

            if len(image_bytes) == 0:
                raise ValueError("Screenshot data resulted in 0 bytes.")

            ts = timestamp or datetime.now()
            ts_str = ts.strftime("%Y%m%d_%H%M%S")
            clean_name = sanitize_filename(task_name)
            filename = f"{clean_name}_{ts_str}.png"
            file_path = errors_dir / filename

            # Write file
            with open(file_path, "wb") as f:
                f.write(image_bytes)

            self.debug(f"Saved diagnostic screenshot to: {file_path}")
            return file_path

    # --- Summary Report Generation & Persistence ---

    def write_summary(
        self,
        summary: Union[SummaryReport, Dict[str, Any], Any],
        session_id: Optional[str] = None,
    ) -> Path:
        """Write or update summary.json atomically for the active session.

        Converts SummaryReport, SessionSummary, SessionState, or dict into the standard schema.

        Args:
            summary: Summary data source.
            session_id: Optional session ID override.

        Returns:
            Path to written summary.json file.
        """
        with self._lock:
            target_session_id = session_id or self.session_id
            if not target_session_id:
                raise ValueError("Cannot write summary: No session initialized.")

            session_dir = self.get_session_dir(target_session_id)
            session_dir.mkdir(parents=True, exist_ok=True)
            summary_path = self.get_summary_path(target_session_id)

            # Convert to dictionary matching specification
            summary_dict: Dict[str, Any]
            if isinstance(summary, SummaryReport):
                summary_dict = summary.to_standard_dict()
            elif isinstance(summary, dict):
                summary_dict = dict(summary)
            elif hasattr(summary, "get_summary"):
                # SessionState instance
                sum_obj = summary.get_summary()
                summary_dict = {
                    "total": sum_obj.total,
                    "success": sum_obj.success,
                    "failed": sum_obj.failed,
                    "skipped": sum_obj.skipped,
                    "start_time": sum_obj.start_time,
                    "end_time": sum_obj.end_time,
                    "total_blocks_modified": sum_obj.total_blocks_modified,
                    "session_id": sum_obj.session_id,
                    "is_completed": sum_obj.is_completed,
                }
            elif hasattr(summary, "model_dump"):
                # Pydantic v2 model (e.g. SessionSummary)
                dumped = summary.model_dump()
                summary_dict = {
                    "total": dumped.get("total", 0),
                    "success": dumped.get("success", 0),
                    "failed": dumped.get("failed", 0),
                    "skipped": dumped.get("skipped", 0),
                    "start_time": dumped.get("start_time"),
                    "end_time": dumped.get("end_time"),
                    "total_blocks_modified": dumped.get("total_blocks_modified", 0),
                }
                for extra_k in ("session_id", "is_completed", "blocks_modified_breakdown"):
                    if extra_k in dumped and dumped[extra_k] is not None:
                        summary_dict[extra_k] = dumped[extra_k]
            else:
                raise TypeError(f"Unsupported summary data type: {type(summary)}")

            json_data = json.dumps(summary_dict, indent=2)
            temp_path = session_dir / f"summary_{os.getpid()}_{threading.get_ident()}.tmp"

            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(json_data)

            # Atomic replace with retry for Windows filesystems
            for attempt in range(5):
                try:
                    os.replace(temp_path, summary_path)
                    break
                except (PermissionError, OSError):
                    if attempt == 4:
                        with open(summary_path, "w", encoding="utf-8") as f:
                            f.write(json_data)
                        if temp_path.exists():
                            try:
                                temp_path.unlink()
                            except OSError:
                                pass
                    else:
                        import time
                        time.sleep(0.01 * (attempt + 1))

            return summary_path

    def read_summary(self, session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Read and parse summary.json from disk.

        Args:
            session_id: Optional session ID.

        Returns:
            Dictionary of parsed summary data, or None if summary.json does not exist.
        """
        with self._lock:
            target_session_id = session_id or self.session_id
            if not target_session_id:
                return None

            summary_path = self.get_summary_path(target_session_id)
            if not summary_path.exists():
                return None

            with open(summary_path, "r", encoding="utf-8") as f:
                return json.load(f)


# Global singleton instance
_global_logger_service: Optional[LoggerService] = None


def get_logger_service(
    session_id: Optional[str] = None,
    settings: Optional[Settings] = None,
    logs_dir: Optional[Path] = None,
) -> LoggerService:
    """Dependency provider and factory for LoggerService singleton."""
    global _global_logger_service
    if _global_logger_service is None:
        _global_logger_service = LoggerService(
            session_id=session_id,
            settings=settings,
            logs_dir=logs_dir,
        )
    elif session_id and _global_logger_service.session_id != session_id:
        _global_logger_service.init_session(session_id)

    return _global_logger_service
