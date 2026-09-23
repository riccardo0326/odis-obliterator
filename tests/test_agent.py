"""Unit tests for WorkerAgent (worker/agent.py) - TASK-009."""

from unittest.mock import MagicMock, patch
import pytest

from controller.config import Settings
from worker.agent import WorkerAgent, main
from worker.workflow_runner import (
    ControllerClient,
    WorkflowExecutionResult,
    WorkflowRunner,
    WorkflowStep,
)


class TestWorkerAgentUnit:
    """Unit tests for WorkerAgent methods and lifecycle."""

    def setup_method(self):
        self.mock_client = MagicMock(spec=ControllerClient)
        self.mock_client.base_url = "http://127.0.0.1:8000"
        self.mock_runner = MagicMock(spec=WorkflowRunner)
        self.settings = Settings(dry_run=True, worker_poll_interval=0.01)

        self.agent = WorkerAgent(
            settings=self.settings,
            controller_client=self.mock_client,
            workflow_runner=self.mock_runner,
            dry_run=True,
            poll_interval=0.01,
        )

    def test_agent_initialization(self):
        assert self.agent.dry_run is True
        assert self.agent.poll_interval == 0.01
        assert self.agent.is_running is False
        assert self.agent.tasks_processed == 0
        assert self.agent.tasks_succeeded == 0
        assert self.agent.tasks_failed == 0

    def test_verify_connectivity_success(self):
        self.mock_client.check_health.return_value = {
            "status": "ok",
            "kelpie": "connected",
            "model": "gemini-3.7-flash",
        }
        res = self.agent.verify_connectivity()
        assert res["status"] == "ok"
        self.mock_client.check_health.assert_called_once()

    def test_verify_connectivity_failure_raises(self):
        self.mock_client.check_health.side_effect = ConnectionError("Connection refused")
        with pytest.raises(ConnectionError):
            self.agent.verify_connectivity()

    def test_poll_and_execute_next_empty_queue(self):
        self.mock_client.get_next_task.return_value = None
        result = self.agent.poll_and_execute_next()
        assert result is None
        assert self.agent.tasks_processed == 0
        self.mock_runner.run_task.assert_not_called()

    def test_poll_and_execute_next_success(self):
        self.mock_client.get_next_task.return_value = {
            "task_id": "GFF_001",
            "name": "A16_4LA_91____1_518_88_Check_battery",
        }
        exec_result = WorkflowExecutionResult(
            task_id="GFF_001",
            gff_name="A16_4LA_91____1_518_88_Check_battery",
            status="SUCCESS",
            steps_completed=[WorkflowStep.STEP_0_HOME, WorkflowStep.STEP_14_CLOSE_OBJECT_RETURN_HOME],
            blocks_detected=2,
            blocks_modified={"message": 1, "comment": 1, "question": 0},
            duration_seconds=5.2,
        )
        self.mock_runner.run_task.return_value = exec_result

        result = self.agent.poll_and_execute_next()
        assert result is not None
        assert result.task_id == "GFF_001"
        assert result.status == "SUCCESS"
        assert self.agent.tasks_processed == 1
        assert self.agent.tasks_succeeded == 1
        assert self.agent.tasks_failed == 0
        assert self.agent.total_blocks_modified == 2

        self.mock_runner.run_task.assert_called_once_with(
            task_id="GFF_001", gff_name="A16_4LA_91____1_518_88_Check_battery"
        )
        self.mock_client.complete_task.assert_called_once()

    def test_poll_and_execute_next_failure(self):
        self.mock_client.get_next_task.return_value = {
            "task_id": "GFF_002",
            "name": "Failing_GFF",
        }
        exec_result = WorkflowExecutionResult(
            task_id="GFF_002",
            gff_name="Failing_GFF",
            status="FAILED",
            steps_completed=[WorkflowStep.STEP_0_HOME],
            blocks_detected=0,
            blocks_modified={"message": 0, "comment": 0, "question": 0},
            duration_seconds=2.1,
            error_details="Window not found",
        )
        self.mock_runner.run_task.return_value = exec_result

        result = self.agent.poll_and_execute_next()
        assert result is not None
        assert result.status == "FAILED"
        assert self.agent.tasks_processed == 1
        assert self.agent.tasks_succeeded == 0
        assert self.agent.tasks_failed == 1

        self.mock_client.complete_task.assert_called_once_with(
            task_id="GFF_002",
            status="FAILED",
            blocks_modified={"message": 0, "comment": 0, "question": 0},
            duration_seconds=2.1,
            error_details="Window not found",
            error_screenshot_base64=None,
        )

    def test_run_batch_completes_when_queue_empty(self):
        # 2 tasks then empty
        self.mock_client.get_next_task.side_effect = [
            {"task_id": "GFF_001", "name": "Func_1"},
            {"task_id": "GFF_002", "name": "Func_2"},
            None,
        ]
        self.mock_runner.run_task.return_value = WorkflowExecutionResult(
            task_id="GFF_X",
            gff_name="Func_X",
            status="SUCCESS",
            blocks_modified={"message": 1, "comment": 0, "question": 0},
        )

        summary = self.agent.run(stop_on_empty_queue=True)
        assert summary["tasks_processed"] == 2
        assert summary["tasks_succeeded"] == 2
        assert summary["tasks_failed"] == 0
        assert summary["total_blocks_modified"] == 2
        assert summary["dry_run"] is True

    def test_run_batch_respects_max_tasks(self):
        self.mock_client.get_next_task.return_value = {"task_id": "GFF_001", "name": "Func_1"}
        self.mock_runner.run_task.return_value = WorkflowExecutionResult(
            task_id="GFF_001",
            gff_name="Func_1",
            status="SUCCESS",
            blocks_modified={"message": 1, "comment": 0, "question": 0},
        )

        summary = self.agent.run(max_tasks=1)
        assert summary["tasks_processed"] == 1

    def test_consecutive_errors_stops_agent(self):
        self.agent.max_consecutive_errors = 3
        self.mock_client.get_next_task.side_effect = ConnectionError("Network down")

        summary = self.agent.run()
        assert summary["tasks_processed"] == 0
        assert self.agent.consecutive_errors >= 3
        assert self.agent.is_running is False


class TestAgentCLI:
    """Tests for WorkerAgent CLI entrypoint."""

    @patch("worker.agent.WorkerAgent")
    @patch("sys.argv", ["agent.py", "--health-only", "--controller-url", "http://192.168.1.50:8000"])
    def test_cli_health_only(self, mock_agent_class):
        mock_instance = MagicMock()
        mock_instance.verify_connectivity.return_value = {"status": "ok"}
        mock_agent_class.return_value = mock_instance

        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
        mock_instance.verify_connectivity.assert_called_once()
