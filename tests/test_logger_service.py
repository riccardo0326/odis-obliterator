"""Unit tests for Structured Logging and Reporting Service (controller/logger_service.py) - TASK-006."""

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path
import time
import pytest

from controller.config import Settings
from controller.logger_service import (
    LoggerService,
    StructuredLogFormatter,
    SummaryReport,
    get_logger_service,
    sanitize_filename,
)
from controller.orchestrator import GFFOrchestrator, TaskStatus


@pytest.fixture
def temp_logs_dir(tmp_path: Path) -> Path:
    """Fixture providing an isolated temporary logs directory."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


@pytest.fixture
def test_settings(temp_logs_dir: Path) -> Settings:
    """Fixture providing Settings configured with temp logs dir."""
    return Settings(logs_dir_override=temp_logs_dir)


class TestSanitizeFilename:
    """Tests for sanitize_filename helper."""

    def test_sanitize_standard_names(self):
        assert sanitize_filename("Check_battery") == "Check_battery"
        assert sanitize_filename("A16_4LA_91____1_518_88_Check_battery") == "A16_4LA_91____1_518_88_Check_battery"
        assert sanitize_filename("test-module-01") == "test-module-01"

    def test_sanitize_special_and_illegal_characters(self):
        assert sanitize_filename("Check / battery : test * ?") == "Check_battery_test"
        assert sanitize_filename("<invalid>|name\"") == "invalid_name"
        assert sanitize_filename("  spaces and symbols @ # $ %  ") == "spaces_and_symbols"

    def test_sanitize_empty_and_fallback(self):
        assert sanitize_filename("") == "unnamed_task"
        assert sanitize_filename("   ") == "unnamed_task"
        assert sanitize_filename("___") == "unnamed_task"
        assert sanitize_filename("***") == "unnamed_task"


class TestSummaryReportModel:
    """Tests for SummaryReport Pydantic model."""

    def test_summary_report_defaults(self):
        report = SummaryReport()
        assert report.total == 0
        assert report.success == 0
        assert report.failed == 0
        assert report.skipped == 0
        assert report.total_blocks_modified == 0
        assert report.start_time is None
        assert report.end_time is None
        assert report.is_completed is False

    def test_summary_report_to_standard_dict(self):
        report = SummaryReport(
            total=842,
            success=839,
            failed=3,
            skipped=0,
            start_time="2026-09-22T15:00:00Z",
            end_time="2026-09-22T18:45:00Z",
            total_blocks_modified=1420,
            session_id="run_2026-09-22_15-00-00",
            blocks_modified_breakdown={"message": 800, "comment": 400, "question": 220},
            is_completed=True,
        )

        std_dict = report.to_standard_dict()
        assert std_dict["total"] == 842
        assert std_dict["success"] == 839
        assert std_dict["failed"] == 3
        assert std_dict["skipped"] == 0
        assert std_dict["start_time"] == "2026-09-22T15:00:00Z"
        assert std_dict["end_time"] == "2026-09-22T18:45:00Z"
        assert std_dict["total_blocks_modified"] == 1420
        assert std_dict["session_id"] == "run_2026-09-22_15-00-00"
        assert std_dict["blocks_modified_breakdown"] == {"message": 800, "comment": 400, "question": 220}
        assert std_dict["is_completed"] is True


class TestLoggerServiceLayoutAndLifecycle:
    """Tests for LoggerService initialization, folder layout, and resource cleanup."""

    def test_init_session_creates_directories_and_log(self, temp_logs_dir: Path, test_settings: Settings):
        service = LoggerService(settings=test_settings, logs_dir=temp_logs_dir)
        session_id = "run_2026-09-22_10-00-00"

        session_dir = service.init_session(session_id)
        assert session_dir.exists()
        assert session_dir.is_dir()

        errors_dir = service.get_errors_dir()
        assert errors_dir.exists()
        assert errors_dir.is_dir()

        log_path = service.get_log_path()
        assert log_path.exists()
        assert log_path.name == "execution.log"

        summary_path = service.get_summary_path()
        assert summary_path == session_dir / "summary.json"

        service.close()

    def test_getters_without_session_raise_error(self, temp_logs_dir: Path, test_settings: Settings):
        service = LoggerService(settings=test_settings, logs_dir=temp_logs_dir)
        assert service.is_initialized is False

        with pytest.raises(ValueError, match="No session ID specified or initialized"):
            service.get_session_dir()

        with pytest.raises(ValueError, match="No session ID specified or initialized"):
            service.get_errors_dir()

        with pytest.raises(ValueError, match="No session ID specified or initialized"):
            service.get_log_path()

        with pytest.raises(ValueError, match="No session ID specified or initialized"):
            service.get_summary_path()

    def test_context_manager(self, temp_logs_dir: Path, test_settings: Settings):
        session_id = "run_context_mgr"
        with LoggerService(session_id=session_id, settings=test_settings, logs_dir=temp_logs_dir) as service:
            service.info("Testing inside context manager")
            assert service.is_initialized is True

        # After exiting context manager, handler should be closed
        assert service._file_handler is None

    def test_switch_session_closes_previous(self, temp_logs_dir: Path, test_settings: Settings):
        service = LoggerService(settings=test_settings, logs_dir=temp_logs_dir)
        service.init_session("run_session_one")
        service.info("Message for session 1")

        log1 = service.get_log_path("run_session_one")
        assert log1.exists()

        service.init_session("run_session_two")
        service.info("Message for session 2")

        log2 = service.get_log_path("run_session_two")
        assert log2.exists()
        assert log1 != log2

        content1 = log1.read_text(encoding="utf-8")
        content2 = log2.read_text(encoding="utf-8")
        assert "Message for session 1" in content1
        assert "Message for session 2" in content2
        assert "Message for session 2" not in content1

        service.close()


class TestLoggerServiceLoggingMethods:
    """Tests for structured and level-based logging to execution.log."""

    def test_logging_levels_and_formatting(self, temp_logs_dir: Path, test_settings: Settings):
        session_id = "run_log_levels"
        service = LoggerService(session_id=session_id, settings=test_settings, logs_dir=temp_logs_dir)

        service.debug("Debug event", task_id="GFF_001")
        service.info("Info event", task_id="GFF_001")
        service.warning("Warning event", task_id="GFF_002")
        service.error("Error event", task_id="GFF_003")

        service.close()

        log_content = service.get_log_path(session_id).read_text(encoding="utf-8")
        lines = [line for line in log_content.splitlines() if line.strip()]

        assert len(lines) == 4
        assert "[DEBUG  ] [session=run_log_levels task=GFF_001] Debug event" in lines[0]
        assert "[INFO   ] [session=run_log_levels task=GFF_001] Info event" in lines[1]
        assert "[WARNING] [session=run_log_levels task=GFF_002] Warning event" in lines[2]
        assert "[ERROR  ] [session=run_log_levels task=GFF_003] Error event" in lines[3]

    def test_structured_workflow_events(self, temp_logs_dir: Path, test_settings: Settings):
        session_id = "run_workflow_events"
        service = LoggerService(session_id=session_id, settings=test_settings, logs_dir=temp_logs_dir)

        # 1. Session start
        service.log_session_start(
            session_id=session_id,
            total_gff=2,
            gff_names=["Func_A", "Func_B"],
            resumed=False,
        )

        # 2. Task start
        service.log_task_start("GFF_001", "Func_A")

        # 3. Task success
        service.log_task_complete(
            task_id="GFF_001",
            task_name="Func_A",
            status="SUCCESS",
            blocks_modified={"message": 1, "comment": 1, "question": 0},
            duration_seconds=14.5,
        )

        # 4. Task failure with screenshot
        service.log_task_start("GFF_002", "Func_B")
        service.log_task_complete(
            task_id="GFF_002",
            task_name="Func_B",
            status="FAILED",
            duration_seconds=6.2,
            error_details="Validation popup modal encountered",
            error_screenshot_path="logs/run_workflow_events/errors/Func_B_20260922.png",
        )

        # 5. Session end
        service.log_session_end(
            {
                "total": 2,
                "success": 1,
                "failed": 1,
                "skipped": 0,
                "total_blocks_modified": 2,
            }
        )

        service.close()

        log_content = service.get_log_path(session_id).read_text(encoding="utf-8")
        assert "BATCH SESSION STARTED" in log_content
        assert "Starting task GFF_001: Func_A" in log_content
        assert "Task GFF_001 (Func_A) SUCCESS (duration: 14.50s)" in log_content
        assert "Task GFF_002 (Func_B) FAILED (duration: 6.20s)" in log_content
        assert "Validation popup modal encountered" in log_content
        assert "BATCH SESSION COMPLETED" in log_content


class TestSummaryJsonReporting:
    """Tests for summary.json writing, updating, and reading."""

    def test_write_and_read_summary_from_model(self, temp_logs_dir: Path, test_settings: Settings):
        session_id = "run_sum_model"
        service = LoggerService(session_id=session_id, settings=test_settings, logs_dir=temp_logs_dir)

        report = SummaryReport(
            total=10,
            success=8,
            failed=1,
            skipped=1,
            start_time="2026-09-22T10:00:00Z",
            end_time="2026-09-22T10:15:00Z",
            total_blocks_modified=15,
            session_id=session_id,
        )

        path = service.write_summary(report)
        assert path.exists()
        assert path == service.get_summary_path()

        data = service.read_summary()
        assert data is not None
        assert data["total"] == 10
        assert data["success"] == 8
        assert data["failed"] == 1
        assert data["skipped"] == 1
        assert data["total_blocks_modified"] == 15
        assert data["start_time"] == "2026-09-22T10:00:00Z"

        service.close()

    def test_write_summary_from_dict(self, temp_logs_dir: Path, test_settings: Settings):
        session_id = "run_sum_dict"
        service = LoggerService(session_id=session_id, settings=test_settings, logs_dir=temp_logs_dir)

        payload = {
            "total": 5,
            "success": 5,
            "failed": 0,
            "skipped": 0,
            "start_time": "2026-09-22T12:00:00Z",
            "end_time": "2026-09-22T12:05:00Z",
            "total_blocks_modified": 7,
        }

        path = service.write_summary(payload)
        assert path.exists()

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["total"] == 5
        assert data["success"] == 5
        assert data["total_blocks_modified"] == 7

        service.close()

    def test_read_summary_missing_returns_none(self, temp_logs_dir: Path, test_settings: Settings):
        service = LoggerService(session_id="run_nonexistent", settings=test_settings, logs_dir=temp_logs_dir)
        assert service.read_summary() is None
        service.close()


class TestErrorScreenshotStorage:
    """Tests for saving error screenshots in errors/ directory."""

    def test_save_screenshot_from_raw_bytes(self, temp_logs_dir: Path, test_settings: Settings):
        session_id = "run_scr_bytes"
        service = LoggerService(session_id=session_id, settings=test_settings, logs_dir=temp_logs_dir)

        dummy_png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
        fixed_time = datetime(2026, 9, 22, 14, 30, 45)

        saved_path = service.save_error_screenshot(
            task_name="A16_4LA_91____1_518_88_Check_battery",
            screenshot_data=dummy_png_bytes,
            timestamp=fixed_time,
        )

        assert saved_path.exists()
        assert saved_path.parent == service.get_errors_dir()
        assert saved_path.name == "A16_4LA_91____1_518_88_Check_battery_20260922_143045.png"
        assert saved_path.read_bytes() == dummy_png_bytes

        service.close()

    def test_save_screenshot_from_base64_data_uri(self, temp_logs_dir: Path, test_settings: Settings):
        session_id = "run_scr_b64"
        service = LoggerService(session_id=session_id, settings=test_settings, logs_dir=temp_logs_dir)

        sample_png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        data_uri = f"data:image/png;base64,{sample_png_b64}"

        saved_path = service.save_error_screenshot(
            task_name="Special / Task : Name",
            screenshot_data=data_uri,
        )

        assert saved_path.exists()
        assert saved_path.suffix == ".png"
        assert saved_path.name.startswith("Special_Task_Name_")
        assert len(saved_path.read_bytes()) > 0

        service.close()

    def test_save_screenshot_invalid_data_raises_value_error(self, temp_logs_dir: Path, test_settings: Settings):
        session_id = "run_scr_err"
        service = LoggerService(session_id=session_id, settings=test_settings, logs_dir=temp_logs_dir)

        with pytest.raises(ValueError, match="Screenshot base64 string is empty"):
            service.save_error_screenshot("Task_1", "")

        with pytest.raises(ValueError, match="Failed to decode base64 screenshot"):
            service.save_error_screenshot("Task_1", "not-a-valid-base64-string!@#$")

        service.close()


class TestLoggerServiceThreadSafety:
    """Tests ensuring LoggerService operates reliably under concurrent thread access."""

    def test_concurrent_logging_and_summary_writes(self, temp_logs_dir: Path, test_settings: Settings):
        session_id = "run_concurrent"
        service = LoggerService(session_id=session_id, settings=test_settings, logs_dir=temp_logs_dir)

        thread_count = 10
        iterations_per_thread = 20

        def worker(thread_idx: int):
            for i in range(iterations_per_thread):
                task_id = f"GFF_{thread_idx:02d}_{i:02d}"
                service.info(f"Thread {thread_idx} log step {i}", task_id=task_id)
                service.write_summary(
                    {
                        "total": thread_count * iterations_per_thread,
                        "success": (thread_idx + 1) * (i + 1),
                        "failed": 0,
                        "skipped": 0,
                        "total_blocks_modified": i,
                    }
                )

        with ThreadPoolExecutor(max_workers=thread_count) as executor:
            futures = [executor.submit(worker, idx) for idx in range(thread_count)]
            for f in futures:
                f.result()

        service.close()

        log_path = service.get_log_path(session_id)
        assert log_path.exists()
        lines = [l for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == thread_count * iterations_per_thread

        summary = service.read_summary(session_id)
        assert summary is not None
        assert "total" in summary


class TestIntegrationOrchestratorAndLogger:
    """Integration test verifying GFFOrchestrator generates summary.json, execution.log, and errors/."""

    def test_orchestrator_generates_full_logs_suite(self, temp_logs_dir: Path, test_settings: Settings):
        service = LoggerService(settings=test_settings, logs_dir=temp_logs_dir)
        orchestrator = GFFOrchestrator(
            settings=test_settings,
            logs_dir=temp_logs_dir,
            logger_service=service,
        )

        session_id = "run_integ_test"
        gff_list = ["Function_Alpha", "Function_Beta"]

        # 1. Start session
        session = orchestrator.start_session(
            session_id=session_id,
            gff_list=gff_list,
            force_new=True,
        )

        session_dir = temp_logs_dir / session_id
        assert session_dir.exists()
        assert (session_dir / "execution.log").exists()
        assert (session_dir / "summary.json").exists()
        assert (session_dir / "state.json").exists()

        # Check initial summary
        initial_summary = json.loads((session_dir / "summary.json").read_text(encoding="utf-8"))
        assert initial_summary["total"] == 2
        assert initial_summary["pending"] == 2 if "pending" in initial_summary else initial_summary["total"] == 2
        assert initial_summary["success"] == 0

        # 2. Process first task (Success)
        task1 = orchestrator.get_next_task()
        assert task1.task_id == "GFF_001"
        orchestrator.complete_task(
            task_id="GFF_001",
            status=TaskStatus.SUCCESS,
            blocks_modified={"message": 2, "comment": 1, "question": 0},
            duration_seconds=10.0,
        )

        # Check updated summary after task 1
        summary_after_1 = json.loads((session_dir / "summary.json").read_text(encoding="utf-8"))
        assert summary_after_1["success"] == 1
        assert summary_after_1["total_blocks_modified"] == 3

        # 3. Process second task (Failure with screenshot)
        task2 = orchestrator.get_next_task()
        sample_png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        orchestrator.complete_task(
            task_id="GFF_002",
            status=TaskStatus.FAILED,
            error_details="Block not found on canvas",
            error_screenshot_base64=f"data:image/png;base64,{sample_png_b64}",
            duration_seconds=5.0,
        )

        # 4. Final verification of directory and reports
        final_summary = json.loads((session_dir / "summary.json").read_text(encoding="utf-8"))
        assert final_summary["total"] == 2
        assert final_summary["success"] == 1
        assert final_summary["failed"] == 1
        assert final_summary["total_blocks_modified"] == 3
        assert final_summary["is_completed"] is True

        # Check execution.log contents
        log_content = (session_dir / "execution.log").read_text(encoding="utf-8")
        assert "BATCH SESSION STARTED" in log_content
        assert "Starting task GFF_001: Function_Alpha" in log_content
        assert "Task GFF_001 (Function_Alpha) SUCCESS" in log_content
        assert "Starting task GFF_002: Function_Beta" in log_content
        assert "Task GFF_002 (Function_Beta) FAILED" in log_content
        assert "BATCH SESSION COMPLETED" in log_content

        # Check error screenshot in errors/ folder
        errors_dir = session_dir / "errors"
        assert errors_dir.exists()
        error_files = list(errors_dir.glob("*.png"))
        assert len(error_files) == 1
        assert error_files[0].name.startswith("Function_Beta_")

        service.close()
