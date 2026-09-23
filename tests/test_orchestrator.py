"""Unit tests for GFF Queue Orchestrator (controller/orchestrator.py) - TASK-005."""

import base64
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import pytest
from controller.config import Settings
from controller.orchestrator import (
    GFFOrchestrator,
    GFFTask,
    SessionState,
    SessionSummary,
    TaskStatus,
    generate_session_id,
    load_gff_list_from_file,
    normalize_task_status,
)


@pytest.fixture
def temp_logs_dir(tmp_path: Path) -> Path:
    """Fixture providing a temporary logs directory."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


@pytest.fixture
def sample_gff_file(tmp_path: Path) -> Path:
    """Fixture providing a sample input_gff.txt file."""
    gff_file = tmp_path / "input_gff.txt"
    content = """# Comment line 1
// Comment line 2
A16_4LA_91____1_518_88_Check_battery

LB63x_01____2_100_01_Engine_control
LB63x_02____2_200_02_Brake_system
"""
    gff_file.write_text(content, encoding="utf-8")
    return gff_file


class TestTaskStatusAndModels:
    """Tests for TaskStatus enum and Pydantic models."""

    def test_task_status_enum_values(self):
        assert TaskStatus.PENDING == "PENDING"
        assert TaskStatus.IN_PROGRESS == "IN_PROGRESS"
        assert TaskStatus.SUCCESS == "SUCCESS"
        assert TaskStatus.FAILED == "FAILED"
        assert TaskStatus.SKIPPED == "SKIPPED"

    def test_normalize_task_status(self):
        assert normalize_task_status(TaskStatus.SUCCESS) == TaskStatus.SUCCESS
        assert normalize_task_status("SUCCESS") == TaskStatus.SUCCESS
        assert normalize_task_status("success") == TaskStatus.SUCCESS
        assert normalize_task_status("completed") == TaskStatus.SUCCESS
        assert normalize_task_status("FAILED") == TaskStatus.FAILED
        assert normalize_task_status("failed") == TaskStatus.FAILED
        assert normalize_task_status("PENDING") == TaskStatus.PENDING
        assert normalize_task_status("SKIPPED") == TaskStatus.SKIPPED

        with pytest.raises(ValueError, match="Invalid task status"):
            normalize_task_status("INVALID_STATUS")

    def test_gff_task_defaults_and_properties(self):
        task = GFFTask(task_id="GFF_001", name="Test_function")
        assert task.status == TaskStatus.PENDING
        assert task.started_at is None
        assert task.completed_at is None
        assert task.duration_seconds is None
        assert task.total_blocks_modified == 0
        assert task.blocks_modified == {"message": 0, "comment": 0, "question": 0}

        task.blocks_modified = {"message": 2, "comment": 1, "question": 3}
        assert task.total_blocks_modified == 6

    def test_session_state_properties(self):
        task1 = GFFTask(task_id="GFF_001", name="Task 1", status=TaskStatus.SUCCESS)
        task1.blocks_modified = {"message": 2, "comment": 1, "question": 0}
        task2 = GFFTask(task_id="GFF_002", name="Task 2", status=TaskStatus.FAILED)
        task3 = GFFTask(task_id="GFF_003", name="Task 3", status=TaskStatus.PENDING)
        task4 = GFFTask(task_id="GFF_004", name="Task 4", status=TaskStatus.IN_PROGRESS)

        state = SessionState(
            session_id="run_2026-09-22_10-00-00",
            total_gff=4,
            tasks=[task1, task2, task3, task4],
        )

        assert state.pending_count == 1
        assert state.in_progress_count == 1
        assert state.success_count == 1
        assert state.failed_count == 1
        assert state.skipped_count == 0
        assert state.total_blocks_modified == 3

        summary = state.get_summary()
        assert summary.total == 4
        assert summary.pending == 1
        assert summary.in_progress == 1
        assert summary.success == 1
        assert summary.failed == 1
        assert summary.total_blocks_modified == 3


class TestGFFFileLoading:
    """Tests for loading GFF names from input files."""

    def test_load_gff_list_from_file_valid(self, sample_gff_file: Path):
        items = load_gff_list_from_file(sample_gff_file)
        assert len(items) == 3
        assert items[0] == "A16_4LA_91____1_518_88_Check_battery"
        assert items[1] == "LB63x_01____2_100_01_Engine_control"
        assert items[2] == "LB63x_02____2_200_02_Brake_system"

    def test_load_gff_list_from_missing_file(self, tmp_path: Path):
        missing = tmp_path / "nonexistent.txt"
        items = load_gff_list_from_file(missing)
        assert items == []

    def test_generate_session_id_format(self):
        sid = generate_session_id()
        assert sid.startswith("run_")
        assert len(sid) >= len("run_YYYY-MM-DD_HH-mm-ss")


class TestGFFOrchestrator:
    """Tests for GFFOrchestrator session lifecycle, queue management, and persistence."""

    def test_start_session_with_explicit_list(self, temp_logs_dir: Path):
        settings = Settings(logs_dir_override=temp_logs_dir)
        orchestrator = GFFOrchestrator(settings=settings, logs_dir=temp_logs_dir)

        gff_list = ["Function_A", "Function_B", "Function_C"]
        session = orchestrator.start_session(
            session_id="run_test_01",
            gff_list=gff_list,
            force_new=True,
        )

        assert session.session_id == "run_test_01"
        assert session.total_gff == 3
        assert len(session.tasks) == 3
        assert session.tasks[0].task_id == "GFF_001"
        assert session.tasks[0].name == "Function_A"
        assert session.tasks[1].task_id == "GFF_002"
        assert session.tasks[2].task_id == "GFF_003"
        assert session.pending_count == 3

        # Verify state file written to disk
        state_file = temp_logs_dir / "run_test_01" / "state.json"
        assert state_file.exists()

    def test_start_session_from_file(self, temp_logs_dir: Path, sample_gff_file: Path):
        settings = Settings(logs_dir_override=temp_logs_dir)
        orchestrator = GFFOrchestrator(settings=settings, logs_dir=temp_logs_dir)

        session = orchestrator.start_session(
            input_file=sample_gff_file,
            force_new=True,
        )

        assert session.total_gff == 3
        assert session.tasks[0].name == "A16_4LA_91____1_518_88_Check_battery"

    def test_get_next_task_and_completion_lifecycle(self, temp_logs_dir: Path):
        settings = Settings(logs_dir_override=temp_logs_dir)
        orchestrator = GFFOrchestrator(settings=settings, logs_dir=temp_logs_dir)

        gff_list = ["Task_One", "Task_Two"]
        orchestrator.start_session(session_id="run_lifecycle", gff_list=gff_list, force_new=True)

        # 1. Dispatch first task
        task1 = orchestrator.get_next_task()
        assert task1 is not None
        assert task1.task_id == "GFF_001"
        assert task1.name == "Task_One"
        assert task1.status == TaskStatus.IN_PROGRESS
        assert task1.started_at is not None

        # 2. Complete first task
        completed1 = orchestrator.complete_task(
            task_id="GFF_001",
            status="SUCCESS",
            blocks_modified={"message": 1, "comment": 0, "question": 2},
            duration_seconds=12.5,
        )
        assert completed1.status == TaskStatus.SUCCESS
        assert completed1.duration_seconds == 12.5
        assert completed1.total_blocks_modified == 3

        # 3. Dispatch second task
        task2 = orchestrator.get_next_task()
        assert task2 is not None
        assert task2.task_id == "GFF_002"
        assert task2.name == "Task_Two"
        assert task2.status == TaskStatus.IN_PROGRESS

        # 4. Fail second task
        completed2 = orchestrator.complete_task(
            task_id="GFF_002",
            status="FAILED",
            error_details="Modal dialog timed out",
            duration_seconds=5.0,
        )
        assert completed2.status == TaskStatus.FAILED
        assert completed2.error_details == "Modal dialog timed out"

        # 5. Check queue is now exhausted
        task3 = orchestrator.get_next_task()
        assert task3 is None

        # 6. Verify session completion status
        current_sess = orchestrator.get_current_session()
        assert current_sess.is_completed is True
        assert current_sess.pending_count == 0
        assert current_sess.success_count == 1
        assert current_sess.failed_count == 1

    def test_complete_task_with_error_screenshot(self, temp_logs_dir: Path):
        settings = Settings(logs_dir_override=temp_logs_dir)
        orchestrator = GFFOrchestrator(settings=settings, logs_dir=temp_logs_dir)

        orchestrator.start_session(session_id="run_screenshot", gff_list=["Task_Error"], force_new=True)
        task = orchestrator.get_next_task()

        # Generate sample 1x1 PNG base64
        sample_png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        data_uri = f"data:image/png;base64,{sample_png_b64}"

        completed = orchestrator.complete_task(
            task_id=task.task_id,
            status=TaskStatus.FAILED,
            error_details="Validation popup appeared",
            error_screenshot_base64=data_uri,
        )

        assert completed.error_screenshot_path is not None
        saved_path = Path(completed.error_screenshot_path)
        assert saved_path.exists()
        assert saved_path.suffix == ".png"

    def test_complete_task_invalid_id_raises_key_error(self, temp_logs_dir: Path):
        settings = Settings(logs_dir_override=temp_logs_dir)
        orchestrator = GFFOrchestrator(settings=settings, logs_dir=temp_logs_dir)
        orchestrator.start_session(session_id="run_err", gff_list=["Task_A"], force_new=True)

        with pytest.raises(KeyError, match="Task with ID 'GFF_999' not found"):
            orchestrator.complete_task(task_id="GFF_999", status="SUCCESS")

    def test_complete_task_without_session_raises_value_error(self, temp_logs_dir: Path):
        orchestrator = GFFOrchestrator(logs_dir=temp_logs_dir)
        with pytest.raises(ValueError, match="No active session"):
            orchestrator.complete_task(task_id="GFF_001", status="SUCCESS")

    def test_resume_crashed_session(self, temp_logs_dir: Path):
        settings = Settings(logs_dir_override=temp_logs_dir)
        orchestrator1 = GFFOrchestrator(settings=settings, logs_dir=temp_logs_dir)

        gff_list = ["Task_A", "Task_B", "Task_C"]
        orchestrator1.start_session(session_id="run_crash_test", gff_list=gff_list, force_new=True)

        # Complete Task A
        t1 = orchestrator1.get_next_task()
        orchestrator1.complete_task(task_id=t1.task_id, status=TaskStatus.SUCCESS)

        # Start Task B (simulating crash while in progress)
        t2 = orchestrator1.get_next_task()
        assert t2.name == "Task_B"
        assert t2.status == TaskStatus.IN_PROGRESS

        # Simulate fresh process startup / restart
        orchestrator2 = GFFOrchestrator(settings=settings, logs_dir=temp_logs_dir)
        resumed_session = orchestrator2.start_session(
            session_id="run_crash_test",
            resume=True,
            force_new=False,
        )

        # Task B should have been reset from IN_PROGRESS to PENDING
        task_b = orchestrator2.get_task("GFF_002")
        assert task_b.status == TaskStatus.PENDING
        assert task_b.started_at is None

        # Next dispatched task should be Task B again
        next_t = orchestrator2.get_next_task()
        assert next_t.task_id == "GFF_002"
        assert next_t.name == "Task_B"

    def test_find_latest_session_state(self, temp_logs_dir: Path):
        orchestrator = GFFOrchestrator(logs_dir=temp_logs_dir)

        orchestrator.start_session(session_id="run_2026-09-20_10-00-00", gff_list=["Task1"], force_new=True)
        orchestrator.start_session(session_id="run_2026-09-22_12-00-00", gff_list=["Task2"], force_new=True)

        latest = orchestrator.find_latest_session_state()
        assert latest is not None
        assert "run_2026-09-22_12-00-00" in str(latest)

    def test_thread_safety_concurrent_queue_access(self, temp_logs_dir: Path):
        settings = Settings(logs_dir_override=temp_logs_dir)
        orchestrator = GFFOrchestrator(settings=settings, logs_dir=temp_logs_dir)

        task_count = 30
        gff_list = [f"Function_{i:03d}" for i in range(1, task_count + 1)]
        orchestrator.start_session(session_id="run_threaded", gff_list=gff_list, force_new=True)

        dispatched_tasks = []

        def worker_fetch_and_complete():
            while True:
                task = orchestrator.get_next_task()
                if task is None:
                    break
                dispatched_tasks.append(task.task_id)
                orchestrator.complete_task(
                    task_id=task.task_id,
                    status=TaskStatus.SUCCESS,
                    blocks_modified={"message": 1, "comment": 0, "question": 0},
                    duration_seconds=0.1,
                )

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(worker_fetch_and_complete) for _ in range(5)]
            for f in futures:
                f.result()

        assert len(dispatched_tasks) == task_count
        assert len(set(dispatched_tasks)) == task_count  # No duplicates dispatched
        assert orchestrator.get_current_session().is_completed is True
        assert orchestrator.get_current_session().success_count == task_count
