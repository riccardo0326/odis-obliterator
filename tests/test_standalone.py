"""Unit tests for the standalone local batch runner (TASK-013)."""

from pathlib import Path
import json
from unittest.mock import MagicMock

import pytest

from controller.config import Settings
from controller.logger_service import LoggerService
from controller.orchestrator import GFFOrchestrator, TaskStatus
from worker.standalone import StandaloneOptions, StandaloneRunner, build_parser
from worker.workflow_runner import WorkflowExecutionResult


def make_settings(tmp_path: Path) -> Settings:
    """Create isolated settings for a test session."""
    return Settings(
        base_dir=tmp_path,
        logs_dir_override=tmp_path / "logs",
        assets_dir_override=tmp_path / "assets",
    )


def make_workflow(status: str = "SUCCESS") -> MagicMock:
    """Create a deterministic workflow double."""
    workflow = MagicMock()
    workflow.run_task.side_effect = lambda task_id, gff_name: WorkflowExecutionResult(
        task_id=task_id,
        gff_name=gff_name,
        status=status,
        blocks_detected=1,
        blocks_modified={"message": 1, "comment": 0, "question": 0},
        duration_seconds=0.01,
    )
    return workflow


def make_runner(tmp_path: Path, input_file: Path, workflow: MagicMock, **kwargs) -> StandaloneRunner:
    """Build a runner with real persistence and an injected workflow."""
    settings = make_settings(tmp_path)
    logger_service = LoggerService(settings=settings, logs_dir=settings.logs_dir)
    orchestrator = GFFOrchestrator(
        settings=settings,
        logs_dir=settings.logs_dir,
        logger_service=logger_service,
    )
    return StandaloneRunner(
        settings=settings,
        options=StandaloneOptions(input_file=input_file, **kwargs),
        orchestrator=orchestrator,
        workflow_runner=workflow,
        logger_service=logger_service,
    )


class TestStandaloneRunner:
    """Tests for local batch execution and checkpoint behavior."""

    def test_dry_run_batch_writes_state_log_and_summary(self, tmp_path):
        input_file = tmp_path / "input_gff.txt"
        input_file.write_text("# comment\nGFF_A\n\nGFF_B\n", encoding="utf-8")
        workflow = make_workflow()
        runner = make_runner(tmp_path, input_file, workflow, dry_run=True)

        state = runner.run()

        assert state.is_completed is True
        assert state.success_count == 2
        assert workflow.run_task.call_count == 2
        session_dir = tmp_path / "logs" / state.session_id
        assert (session_dir / "state.json").exists()
        assert (session_dir / "execution.log").exists()
        assert (session_dir / "summary.json").exists()

    def test_max_tasks_leaves_remaining_queue_pending(self, tmp_path):
        input_file = tmp_path / "input_gff.txt"
        input_file.write_text("GFF_A\nGFF_B\nGFF_C\n", encoding="utf-8")
        workflow = make_workflow()
        runner = make_runner(tmp_path, input_file, workflow, dry_run=True, max_tasks=1)

        state = runner.run()

        assert state.is_completed is False
        assert state.success_count == 1
        assert state.pending_count == 2
        assert workflow.run_task.call_count == 1

    def test_empty_input_creates_completed_empty_report(self, tmp_path):
        input_file = tmp_path / "input_gff.txt"
        input_file.write_text("# no executable tasks\n", encoding="utf-8")
        runner = make_runner(tmp_path, input_file, make_workflow(), dry_run=True)

        state = runner.run()

        assert state.is_completed is True
        assert state.total_gff == 0
        summary = json.loads((tmp_path / "logs" / state.session_id / "summary.json").read_text())
        assert summary["total"] == 0
        assert summary["success"] == 0
        assert summary["is_completed"] is True

    def test_failed_workflow_is_recorded_in_report(self, tmp_path):
        input_file = tmp_path / "input_gff.txt"
        input_file.write_text("GFF_FAILED\n", encoding="utf-8")
        workflow = make_workflow(status="FAILED")
        runner = make_runner(tmp_path, input_file, workflow, dry_run=True)

        state = runner.run()

        assert state.failed_count == 1
        assert state.tasks[0].status == TaskStatus.FAILED
        summary = json.loads((tmp_path / "logs" / state.session_id / "summary.json").read_text())
        assert summary["failed"] == 1
        assert summary["is_completed"] is True

    def test_execution_log_contains_task_events(self, tmp_path):
        input_file = tmp_path / "input_gff.txt"
        input_file.write_text("GFF_LOG\n", encoding="utf-8")
        runner = make_runner(tmp_path, input_file, make_workflow(), dry_run=True)

        state = runner.run()

        log_text = (tmp_path / "logs" / state.session_id / "execution.log").read_text(encoding="utf-8")
        assert "BATCH SESSION STARTED" in log_text
        assert "Starting task GFF_001" in log_text
        assert "GFF_001 (GFF_LOG) SUCCESS" in log_text

    def test_resume_skips_successful_tasks(self, tmp_path):
        input_file = tmp_path / "input_gff.txt"
        input_file.write_text("GFF_A\nGFF_B\n", encoding="utf-8")

        first_workflow = make_workflow()
        first_runner = make_runner(tmp_path, input_file, first_workflow, dry_run=True, max_tasks=1)
        first_state = first_runner.run()

        second_workflow = make_workflow()
        second_runner = make_runner(tmp_path, input_file, second_workflow, dry_run=True)
        second_state = second_runner.run()

        assert second_state.is_completed is True
        assert second_state.success_count == 2
        assert second_workflow.run_task.call_count == 1
        assert second_workflow.run_task.call_args.args[0] == "GFF_002"
        assert first_state.session_id == second_state.session_id

    def test_interrupt_preserves_in_progress_task_for_resume(self, tmp_path):
        input_file = tmp_path / "input_gff.txt"
        input_file.write_text("GFF_A\n", encoding="utf-8")
        interrupted_workflow = MagicMock()
        interrupted_workflow.run_task.side_effect = KeyboardInterrupt
        runner = make_runner(tmp_path, input_file, interrupted_workflow, dry_run=True)

        interrupted_state = runner.run()

        assert interrupted_state.is_completed is False
        assert interrupted_state.tasks[0].status == TaskStatus.IN_PROGRESS
        assert interrupted_state.active_task_id == "GFF_001"

        resumed_workflow = make_workflow()
        resumed_runner = make_runner(tmp_path, input_file, resumed_workflow, dry_run=True)
        resumed_state = resumed_runner.run()

        assert resumed_state.is_completed is True
        assert resumed_workflow.run_task.call_count == 1


class TestStandaloneCli:
    """Tests for argparse options without starting a workflow."""

    def test_parser_supports_dry_run_and_options(self):
        args = build_parser().parse_args(
            ["--dry-run", "-i", "custom.txt", "-n", "3", "--force-new", "-v"]
        )

        assert args.dry_run is True
        assert args.input_file == Path("custom.txt")
        assert args.max_tasks == 3
        assert args.force_new is True
        assert args.verbose is True

    def test_parser_supports_live_alias(self):
        args = build_parser().parse_args(["--live"])
        assert args.live is True
        assert args.dry_run is False

    def test_runner_rejects_invalid_max_tasks(self, tmp_path):
        with pytest.raises(ValueError, match="max_tasks"):
            make_runner(
                tmp_path,
                tmp_path / "input.txt",
                make_workflow(),
                max_tasks=0,
            )
