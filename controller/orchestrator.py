"""GFF Queue Orchestrator and Session Management for ODIS Obliterator (TASK-005).

Manages diagnostic function (GFF) task queues, execution lifecycles,
checkpointing, crash recovery, and state persistence for distributed batch processing.
"""

from datetime import datetime, timezone
from enum import Enum
import json
import logging
import os
from pathlib import Path
import re
import threading
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field

from controller.config import Settings, get_settings
from controller.logger_service import LoggerService, get_logger_service

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """Lifecycle states of a diagnostic GFF task."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


def normalize_task_status(value: Any) -> TaskStatus:
    """Normalize string or TaskStatus to canonical TaskStatus enum.

    Args:
        value: Input status (string or TaskStatus).

    Returns:
        Canonical TaskStatus enum.

    Raises:
        ValueError: If status is unrecognized.
    """
    if isinstance(value, TaskStatus):
        return value
    if isinstance(value, str):
        cleaned = value.strip().upper()
        if cleaned == "COMPLETED":
            return TaskStatus.SUCCESS
        if cleaned in TaskStatus.__members__:
            return TaskStatus[cleaned]
    raise ValueError(f"Invalid task status: {value}")


class GFFTask(BaseModel):
    """Single diagnostic object / GFF processing unit."""

    task_id: str = Field(..., description="Unique task identifier (e.g. GFF_001, GFF_042).")
    name: str = Field(..., description="Diagnostic object / GFF function name.")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="Current lifecycle state.")
    started_at: Optional[str] = Field(default=None, description="ISO timestamp when task processing began.")
    completed_at: Optional[str] = Field(default=None, description="ISO timestamp when task finished.")
    duration_seconds: Optional[float] = Field(default=None, description="Total execution duration in seconds.")
    blocks_modified: Dict[str, int] = Field(
        default_factory=lambda: {"message": 0, "comment": 0, "question": 0},
        description="Count of modified blocks by category.",
    )
    error_details: Optional[str] = Field(default=None, description="Detailed error or failure description.")
    error_screenshot_path: Optional[str] = Field(default=None, description="Path to saved error screenshot.")
    retry_count: int = Field(default=0, ge=0, description="Number of retry attempts.")

    @property
    def total_blocks_modified(self) -> int:
        """Total number of modified blocks across all categories."""
        return sum(self.blocks_modified.values())


class SessionSummary(BaseModel):
    """High-level summary metrics of a batch processing session."""

    session_id: str = Field(..., description="Unique session run identifier.")
    total: int = Field(default=0, ge=0, description="Total number of GFF tasks in batch.")
    pending: int = Field(default=0, ge=0, description="Count of pending tasks.")
    in_progress: int = Field(default=0, ge=0, description="Count of currently executing tasks.")
    success: int = Field(default=0, ge=0, description="Count of successfully completed tasks.")
    failed: int = Field(default=0, ge=0, description="Count of failed tasks.")
    skipped: int = Field(default=0, ge=0, description="Count of skipped tasks.")
    start_time: Optional[str] = Field(default=None, description="ISO start timestamp of the session.")
    end_time: Optional[str] = Field(default=None, description="ISO end timestamp of the session.")
    total_blocks_modified: int = Field(default=0, ge=0, description="Total blocks sanitized across all tasks.")
    is_completed: bool = Field(default=False, description="Whether all tasks have finished.")


class SessionState(BaseModel):
    """Complete serializable state of an orchestration session."""

    session_id: str = Field(..., description="Unique run identifier (e.g. run_2026-09-22_15-00-00).")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Session creation timestamp.",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Last state update timestamp.",
    )
    total_gff: int = Field(default=0, ge=0, description="Total number of tasks in batch.")
    tasks: List[GFFTask] = Field(default_factory=list, description="Ordered list of GFF tasks.")
    active_task_id: Optional[str] = Field(default=None, description="ID of currently executing task.")
    is_completed: bool = Field(default=False, description="Whether all tasks have reached a terminal state.")

    @property
    def pending_count(self) -> int:
        """Count of tasks in PENDING state."""
        return sum(1 for t in self.tasks if t.status == TaskStatus.PENDING)

    @property
    def in_progress_count(self) -> int:
        """Count of tasks in IN_PROGRESS state."""
        return sum(1 for t in self.tasks if t.status == TaskStatus.IN_PROGRESS)

    @property
    def success_count(self) -> int:
        """Count of tasks in SUCCESS state."""
        return sum(1 for t in self.tasks if t.status == TaskStatus.SUCCESS)

    @property
    def failed_count(self) -> int:
        """Count of tasks in FAILED state."""
        return sum(1 for t in self.tasks if t.status == TaskStatus.FAILED)

    @property
    def skipped_count(self) -> int:
        """Count of tasks in SKIPPED state."""
        return sum(1 for t in self.tasks if t.status == TaskStatus.SKIPPED)

    @property
    def total_blocks_modified(self) -> int:
        """Total count of sanitized blocks across all tasks."""
        return sum(t.total_blocks_modified for t in self.tasks)

    def get_summary(self) -> SessionSummary:
        """Generate summary metrics representation."""
        start_ts = self.created_at
        end_ts = self.updated_at if self.is_completed else None
        return SessionSummary(
            session_id=self.session_id,
            total=len(self.tasks),
            pending=self.pending_count,
            in_progress=self.in_progress_count,
            success=self.success_count,
            failed=self.failed_count,
            skipped=self.skipped_count,
            start_time=start_ts,
            end_time=end_ts,
            total_blocks_modified=self.total_blocks_modified,
            is_completed=self.is_completed,
        )


def generate_session_id() -> str:
    """Generate timestamped session ID matching format: run_YYYY-MM-DD_HH-mm-ss."""
    return datetime.now().strftime("run_%Y-%m-%d_%H-%M-%S")


def load_gff_list_from_file(filepath: Path) -> List[str]:
    """Load GFF function names from a text file (one per line).

    Ignores empty lines, whitespace, and comment lines starting with '#' or '//'.

    Args:
        filepath: Path to the input GFF text file.

    Returns:
        List of non-empty GFF function name strings.
    """
    if not filepath.exists():
        logger.warning(f"GFF input file not found at: {filepath}")
        return []

    gff_names: List[str] = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            cleaned = line.strip()
            if not cleaned or cleaned.startswith("#") or cleaned.startswith("//"):
                continue
            gff_names.append(cleaned)

    return gff_names


class GFFOrchestrator:
    """Thread-safe orchestrator managing GFF batch queue, execution, and state persistence."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        logs_dir: Optional[Path] = None,
        logger_service: Optional[LoggerService] = None,
    ):
        """Initialize GFFOrchestrator.

        Args:
            settings: Optional Settings instance (defaults to global settings).
            logs_dir: Optional custom logs directory.
            logger_service: Optional LoggerService instance.
        """
        self.settings = settings or get_settings()
        self.logs_dir = logs_dir or self.settings.logs_dir
        self.logger_service = logger_service or LoggerService(
            settings=self.settings,
            logs_dir=self.logs_dir,
        )
        self.current_session: Optional[SessionState] = None
        self._lock = threading.RLock()

    def get_session_dir(self, session_id: str) -> Path:
        """Return the directory path for the given session ID."""
        return self.logs_dir / session_id

    def get_errors_dir(self, session_id: str) -> Path:
        """Return the error screenshots directory path for the given session ID."""
        return self.get_session_dir(session_id) / "errors"

    def get_state_file_path(self, session_id: str) -> Path:
        """Return the state.json checkpoint path for the given session ID."""
        return self.get_session_dir(session_id) / "state.json"

    def find_latest_session_state(self) -> Optional[Path]:
        """Search logs directory for the most recent session state file.

        Returns:
            Path to latest state.json if found, else None.
        """
        if not self.logs_dir.exists():
            return None

        state_files: List[Path] = []
        for session_dir in self.logs_dir.iterdir():
            if session_dir.is_dir() and session_dir.name.startswith("run_"):
                state_file = session_dir / "state.json"
                if state_file.exists():
                    state_files.append(state_file)

        if not state_files:
            return None

        # Sort by directory modification time descending
        state_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return state_files[0]

    def load_state(self, filepath: Path) -> SessionState:
        """Load and parse SessionState from a checkpoint file.

        Args:
            filepath: Path to state.json file.

        Returns:
            Parsed SessionState instance.
        """
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return SessionState.model_validate(data)

    def save_state(self, session_state: Optional[SessionState] = None) -> Path:
        """Atomically persist session state to state.json.

        Args:
            session_state: State to persist (defaults to current_session).

        Returns:
            Path to saved state file.

        Raises:
            ValueError: If no session is active.
        """
        with self._lock:
            state = session_state or self.current_session
            if state is None:
                raise ValueError("Cannot save state: No active session.")

            session_dir = self.get_session_dir(state.session_id)
            session_dir.mkdir(parents=True, exist_ok=True)
            errors_dir = self.get_errors_dir(state.session_id)
            errors_dir.mkdir(parents=True, exist_ok=True)

            state_path = self.get_state_file_path(state.session_id)
            temp_path = session_dir / f"state_{os.getpid()}_{threading.get_ident()}.tmp"

            state.updated_at = datetime.now(timezone.utc).isoformat()
            state_json = state.model_dump_json(indent=2)

            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(state_json)

            # Atomic replace with retry for Windows file systems
            for attempt in range(5):
                try:
                    os.replace(temp_path, state_path)
                    break
                except (PermissionError, OSError) as err:
                    if attempt == 4:
                        # Fallback direct write if replace fails repeatedly
                        with open(state_path, "w", encoding="utf-8") as f:
                            f.write(state_json)
                        if temp_path.exists():
                            try:
                                temp_path.unlink()
                            except OSError:
                                pass
                    else:
                        import time
                        time.sleep(0.01 * (attempt + 1))

            # Automatically update summary.json
            try:
                self.logger_service.write_summary(state, session_id=state.session_id)
            except Exception as exc:
                logger.warning(f"Failed to update summary.json for session {state.session_id}: {exc}")

            return state_path

    def start_session(
        self,
        session_id: Optional[str] = None,
        gff_list: Optional[List[str]] = None,
        input_file: Optional[Union[str, Path]] = None,
        resume: bool = True,
        force_new: bool = False,
    ) -> SessionState:
        """Start a new processing session or resume an existing session.

        Args:
            session_id: Optional explicit session identifier.
            gff_list: Optional explicit list of GFF function names.
            input_file: Optional custom path to input GFF text file.
            resume: If True, attempt to resume from existing state if available.
            force_new: If True, force creation of a brand new session.

        Returns:
            SessionState instance representing active session.
        """
        with self._lock:
            # 1. Check if resume is requested and feasible
            if resume and not force_new:
                target_state_file: Optional[Path] = None

                if session_id is not None:
                    candidate = self.get_state_file_path(session_id)
                    if candidate.exists():
                        target_state_file = candidate
                elif self.current_session is not None:
                    # Current in-memory session is active
                    target_state_file = self.get_state_file_path(self.current_session.session_id)
                else:
                    target_state_file = self.find_latest_session_state()

                if target_state_file and target_state_file.exists():
                    logger.info(f"Resuming existing session from checkpoint: {target_state_file}")
                    state = self.load_state(target_state_file)

                    # Reset any crashed IN_PROGRESS tasks back to PENDING
                    for task in state.tasks:
                        if task.status == TaskStatus.IN_PROGRESS:
                            logger.info(f"Resetting interrupted task {task.task_id} ({task.name}) to PENDING")
                            task.status = TaskStatus.PENDING
                            task.started_at = None

                    state.active_task_id = None
                    self.current_session = state
                    self.logger_service.init_session(state.session_id)
                    self.logger_service.log_session_start(
                        session_id=state.session_id,
                        total_gff=state.total_gff,
                        gff_names=[t.name for t in state.tasks],
                        resumed=True,
                    )
                    self.save_state()
                    return self.current_session

            # 2. Create a new session
            new_session_id = session_id or generate_session_id()

            # Determine GFF items
            items: List[str] = []
            if gff_list is not None:
                items = [name.strip() for name in gff_list if name.strip()]
            else:
                target_input_path = Path(input_file) if input_file else self.settings.input_gff_path
                items = load_gff_list_from_file(target_input_path)

            tasks: List[GFFTask] = []
            pad_width = max(3, len(str(len(items))))
            for idx, name in enumerate(items, start=1):
                task_id_str = f"GFF_{str(idx).zfill(pad_width)}"
                tasks.append(
                    GFFTask(
                        task_id=task_id_str,
                        name=name,
                        status=TaskStatus.PENDING,
                    )
                )

            session_state = SessionState(
                session_id=new_session_id,
                total_gff=len(tasks),
                tasks=tasks,
                is_completed=(len(tasks) == 0),
            )

            self.current_session = session_state
            self.logger_service.init_session(new_session_id)
            self.logger_service.log_session_start(
                session_id=new_session_id,
                total_gff=len(tasks),
                gff_names=[t.name for t in tasks],
                resumed=False,
            )
            self.save_state()
            logger.info(f"Initialized new session '{new_session_id}' with {len(tasks)} GFF tasks.")
            return self.current_session

    def get_next_task(self) -> Optional[GFFTask]:
        """Fetch the next pending task from the queue and set state to IN_PROGRESS.

        If no session is active, automatically attempts to start/resume one.

        Returns:
            GFFTask instance if available, or None if queue is empty.
        """
        with self._lock:
            if self.current_session is None:
                self.start_session(resume=True)

            assert self.current_session is not None

            for task in self.current_session.tasks:
                if task.status == TaskStatus.PENDING:
                    task.status = TaskStatus.IN_PROGRESS
                    task.started_at = datetime.now(timezone.utc).isoformat()
                    self.current_session.active_task_id = task.task_id
                    self.save_state()
                    self.logger_service.log_task_start(task.task_id, task.name)
                    logger.info(f"Dispatched task {task.task_id}: {task.name}")
                    return task

            # No pending tasks left
            all_terminal = all(
                t.status in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.SKIPPED)
                for t in self.current_session.tasks
            )
            if all_terminal:
                self.current_session.is_completed = True
                self.current_session.active_task_id = None
                self.save_state()
                self.logger_service.log_session_end(self.current_session.get_summary())

            return None

    def complete_task(
        self,
        task_id: str,
        status: Union[TaskStatus, str],
        blocks_modified: Optional[Dict[str, int]] = None,
        duration_seconds: Optional[float] = None,
        error_details: Optional[str] = None,
        error_screenshot_base64: Optional[str] = None,
    ) -> GFFTask:
        """Mark a task as completed with status, metrics, and error info.

        Args:
            task_id: Target task identifier.
            status: Terminal status (SUCCESS, FAILED, SKIPPED).
            blocks_modified: Optional count of modified blocks.
            duration_seconds: Execution duration.
            error_details: Error message/stack trace if failed.
            error_screenshot_base64: Optional base64 encoded error screenshot.

        Returns:
            Updated GFFTask instance.

        Raises:
            ValueError: If no session is active.
            KeyError: If task_id is not found in current session.
        """
        with self._lock:
            if self.current_session is None:
                raise ValueError("Cannot complete task: No active session.")

            target_task: Optional[GFFTask] = None
            for task in self.current_session.tasks:
                if task.task_id == task_id:
                    target_task = task
                    break

            if target_task is None:
                raise KeyError(f"Task with ID '{task_id}' not found in active session.")

            norm_status = normalize_task_status(status)
            target_task.status = norm_status
            target_task.completed_at = datetime.now(timezone.utc).isoformat()

            if duration_seconds is not None:
                target_task.duration_seconds = max(0.0, float(duration_seconds))
            elif target_task.started_at:
                try:
                    start_dt = datetime.fromisoformat(target_task.started_at)
                    end_dt = datetime.fromisoformat(target_task.completed_at)
                    target_task.duration_seconds = round((end_dt - start_dt).total_seconds(), 2)
                except Exception:
                    pass

            if blocks_modified is not None:
                target_task.blocks_modified = {
                    "message": int(blocks_modified.get("message", 0)),
                    "comment": int(blocks_modified.get("comment", 0)),
                    "question": int(blocks_modified.get("question", 0)),
                }

            if error_details:
                target_task.error_details = str(error_details)

            # Save error screenshot if provided
            if error_screenshot_base64:
                try:
                    screenshot_path = self.logger_service.save_error_screenshot(
                        task_name=target_task.name,
                        screenshot_data=error_screenshot_base64,
                        session_id=self.current_session.session_id,
                    )
                    target_task.error_screenshot_path = str(screenshot_path)
                except Exception as exc:
                    logger.error(f"Failed to save error screenshot for task {task_id}: {exc}")

            if self.current_session.active_task_id == task_id:
                self.current_session.active_task_id = None

            # Check if all tasks in session are now finished
            all_done = all(
                t.status in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.SKIPPED)
                for t in self.current_session.tasks
            )
            if all_done:
                self.current_session.is_completed = True

            self.save_state()
            self.logger_service.log_task_complete(
                task_id=task_id,
                task_name=target_task.name,
                status=norm_status.value,
                blocks_modified=target_task.blocks_modified,
                duration_seconds=target_task.duration_seconds,
                error_details=target_task.error_details,
                error_screenshot_path=target_task.error_screenshot_path,
            )
            if all_done:
                self.logger_service.log_session_end(self.current_session.get_summary())

            logger.info(
                f"Task {task_id} ({target_task.name}) completed with status {norm_status.value}. "
                f"Blocks modified: {target_task.blocks_modified}"
            )
            return target_task

    def get_task(self, task_id: str) -> Optional[GFFTask]:
        """Lookup a task by ID in the current session.

        Args:
            task_id: Task identifier.

        Returns:
            GFFTask if found, else None.
        """
        with self._lock:
            if self.current_session is None:
                return None
            for task in self.current_session.tasks:
                if task.task_id == task_id:
                    return task
            return None

    def get_current_session(self) -> Optional[SessionState]:
        """Return the active SessionState instance."""
        with self._lock:
            return self.current_session

    def reset_session(self) -> None:
        """Clear active in-memory session reference."""
        with self._lock:
            self.current_session = None
