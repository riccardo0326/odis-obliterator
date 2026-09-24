"""Integration tests & Dry-Run batch validation for ODIS Obliterator (TASK-009).

Validates end-to-end distributed workflow execution in DRY_RUN mode between
Controller (FastAPI / Orchestrator / AI Gateway / Logger) and Worker (Agent / WorkflowRunner / UIDriver).
"""

from datetime import datetime
import json
from pathlib import Path
from typing import Dict, List
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from controller.app import create_app, get_kelpie_client, get_orchestrator, get_vision_engine
from controller.config import Settings
from controller.kelpie_client import KelpieClient
from controller.logger_service import LoggerService
from controller.orchestrator import GFFOrchestrator, TaskStatus
from controller.text_cleaner import TextCleaner
from controller.vision_engine import (
    BlockType,
    CanvasAnalysisResponse,
    CanvasBoundingBox,
    DetectedBlock,
    PopupDetectionResult,
    PopupType,
    VisionEngine,
)
from worker.agent import WorkerAgent
from worker.screen_capture import ScreenCapture
from worker.ui_driver import BackendAdapter, UIActionType, UIDriver
from worker.workflow_runner import (
    ControllerClient,
    WorkflowCoordinates,
    WorkflowExecutionResult,
    WorkflowRunner,
    WorkflowStep,
)


@pytest.fixture
def dry_run_environment(tmp_path: Path):
    """Fixture providing an isolated Controller + Worker environment for Dry-Run testing."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        dry_run=True,
        logs_dir_override=logs_dir,
        data_dir_override=data_dir,
        target_keyword="Lamborghini",
        version_comment="Removed Lamborghini labels",
        worker_poll_interval=0.01,
        action_delay=0.0,
    )

    # 1. Controller Components
    logger_service = LoggerService(settings=settings, logs_dir=logs_dir)
    orchestrator = GFFOrchestrator(
        settings=settings,
        logs_dir=logs_dir,
        logger_service=logger_service,
    )
    mock_kelpie = MagicMock(spec=KelpieClient)
    mock_kelpie.check_health.return_value = {
        "status": "ok",
        "kelpie": "connected",
        "model": "gemini-3.7-flash",
    }
    mock_vision = MagicMock(spec=VisionEngine)
    mock_vision.analyze_canvas.return_value = CanvasAnalysisResponse(
        blocks=[],
        task_id="default_task",
        total_detected=0,
    )
    mock_vision.detect_popup.return_value = PopupDetectionResult(detected=False, popup_type=PopupType.NONE)

    # FastAPI App
    app = create_app(settings=settings)
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    app.dependency_overrides[get_kelpie_client] = lambda: mock_kelpie
    app.dependency_overrides[get_vision_engine] = lambda: mock_vision

    client = TestClient(app)

    # 2. Worker UI Components
    mock_backend = MagicMock(spec=BackendAdapter)
    ui_driver = UIDriver(dry_run=True, action_delay=0.0, backend=mock_backend)

    mock_screen_capture = MagicMock(spec=ScreenCapture)
    mock_screen_capture.capture_as_base64.return_value = (
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    mock_screen_capture.get_screen_size.return_value = (1920, 1080)

    # 3. Custom ControllerClient that bridges requests directly to TestClient
    class TestClientBridge(ControllerClient):
        def __init__(self, test_client: TestClient):
            super().__init__(base_url="http://testserver", timeout=10.0)
            self._test_client = test_client

        def check_health(self):
            resp = self._test_client.get("/api/v1/health")
            resp.raise_for_status()
            return resp.json()

        def start_session(self, session_id=None, gff_list=None, input_file=None, resume=True, force_new=False):
            payload = {
                "session_id": session_id,
                "gff_list": gff_list,
                "input_file": input_file,
                "resume": resume,
                "force_new": force_new,
            }
            resp = self._test_client.post("/api/v1/session/start", json=payload)
            resp.raise_for_status()
            return resp.json()

        def get_next_task(self):
            resp = self._test_client.get("/api/v1/tasks/next")
            if resp.status_code == 204:
                return None
            resp.raise_for_status()
            return resp.json()

        def get_session_status(self):
            resp = self._test_client.get("/api/v1/session/status")
            resp.raise_for_status()
            return resp.json()

        def clean_text(self, raw_text, block_type=None, target_keyword=None):
            payload = {
                "raw_text": raw_text,
                "block_type": block_type,
                "target_keyword": target_keyword,
            }
            resp = self._test_client.post("/api/v1/text/clean", json=payload)
            resp.raise_for_status()
            from controller.text_cleaner import TextCleanResponse
            return TextCleanResponse.model_validate(resp.json())

        def analyze_canvas(self, image_base64, canvas_bbox=None, task_id=None):
            payload = {
                "task_id": task_id,
                "image_base64": image_base64,
                "canvas_bbox": canvas_bbox.model_dump() if canvas_bbox else None,
            }
            resp = self._test_client.post("/api/v1/vision/analyze-canvas", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return [DetectedBlock.model_validate(b) for b in data.get("blocks", [])]

        def complete_task(self, task_id, status, blocks_modified=None, duration_seconds=None, error_details=None, error_screenshot_base64=None):
            payload = {
                "task_id": task_id,
                "status": status,
                "blocks_modified": blocks_modified,
                "duration_seconds": duration_seconds,
                "error_details": error_details,
                "error_screenshot_base64": error_screenshot_base64,
            }
            resp = self._test_client.post("/api/v1/tasks/complete", json=payload)
            resp.raise_for_status()
            return resp.json()

    controller_client = TestClientBridge(client)

    return {
        "settings": settings,
        "logs_dir": logs_dir,
        "data_dir": data_dir,
        "orchestrator": orchestrator,
        "logger_service": logger_service,
        "mock_vision": mock_vision,
        "mock_backend": mock_backend,
        "ui_driver": ui_driver,
        "screen_capture": mock_screen_capture,
        "controller_client": controller_client,
        "fastapi_client": client,
    }


class TestDryRunBatchExecution:
    """Core acceptance test for TASK-009: 3-GFF Dry-Run batch session execution."""

    def test_three_gff_dry_run_batch_success(self, dry_run_environment):
        """Execute a full batch of 3 GFF functions in Dry-Run mode and verify all criteria."""
        env = dry_run_environment
        controller_client = env["controller_client"]
        ui_driver = env["ui_driver"]
        mock_backend = env["mock_backend"]
        mock_vision = env["mock_vision"]
        logs_dir = env["logs_dir"]

        # 3 Diagnostic functions to process
        gff_batch = [
            "A16_4LA_91____1_518_88_Check_battery",
            "LB63x_01____2_100_01_Engine_control",
            "AU58x_09____3_400_12_Transmission_check",
        ]

        # Configure Vision Engine mock to return specific target blocks per task
        def mock_analyze(image, canvas_bbox=None, task_id=None):
            if task_id == "GFF_001":
                return CanvasAnalysisResponse(
                    blocks=[
                        DetectedBlock(type=BlockType.MESSAGE, relative_x=0.45, relative_y=0.30, label="Message GFF1"),
                        DetectedBlock(type=BlockType.COMMENT, relative_x=0.50, relative_y=0.50, label="Comment GFF1"),
                        DetectedBlock(type=BlockType.QUESTION, relative_x=0.60, relative_y=0.70, label="Question GFF1"),
                    ],
                    task_id=task_id,
                    total_detected=3,
                )
            elif task_id == "GFF_002":
                return CanvasAnalysisResponse(
                    blocks=[
                        DetectedBlock(type=BlockType.MESSAGE, relative_x=0.40, relative_y=0.35, label="Message GFF2"),
                        DetectedBlock(type=BlockType.QUESTION, relative_x=0.65, relative_y=0.65, label="Question GFF2"),
                    ],
                    task_id=task_id,
                    total_detected=2,
                )
            else:
                return CanvasAnalysisResponse(
                    blocks=[
                        DetectedBlock(type=BlockType.COMMENT, relative_x=0.50, relative_y=0.55, label="Comment GFF3"),
                    ],
                    task_id=task_id,
                    total_detected=1,
                )

        mock_vision.analyze_canvas.side_effect = mock_analyze

        # Text supplier simulating real ODIS block contents with target keyword and inviolable tags
        def text_supplier(block: DetectedBlock) -> str:
            if block.type == BlockType.MESSAGE:
                return "- Check the Lamborghini event memory entry.\n\n@[std]AU00003_Ende"
            elif block.type == BlockType.QUESTION:
                return "Is the Lamborghini component %str_Bauteil% connected properly?"
            else:
                return "Lamborghini specific diagnostic comment: check %str_Steuergeraet%"

        # Set up WorkflowRunner and WorkerAgent
        runner = WorkflowRunner(
            settings=env["settings"],
            ui_driver=ui_driver,
            screen_capture=env["screen_capture"],
            controller_client=controller_client,
            dry_run=True,
            action_delay=0.0,
            text_supplier=text_supplier,
        )

        agent = WorkerAgent(
            settings=env["settings"],
            controller_client=controller_client,
            workflow_runner=runner,
            dry_run=True,
            poll_interval=0.01,
        )

        # 1. Initialize Controller Session with the 3 GFFs
        session_id = "run_test_dry_run_3gff"
        start_res = controller_client.start_session(
            session_id=session_id,
            gff_list=gff_batch,
            force_new=True,
        )
        assert start_res["session_id"] == session_id
        assert start_res["total_gff"] == 3
        assert start_res["pending"] == 3

        # 2. Run WorkerAgent batch loop
        agent_summary = agent.run(max_tasks=3)

        # 3. Verify Worker Agent Execution Metrics
        assert agent_summary["dry_run"] is True
        assert agent_summary["tasks_processed"] == 3
        assert agent_summary["tasks_succeeded"] == 3
        assert agent_summary["tasks_failed"] == 0
        # GFF1: 3 blocks, GFF2: 2 blocks, GFF3: 1 block = 6 total blocks modified
        assert agent_summary["total_blocks_modified"] == 6

        # 4. Verify UIDriver in Dry-Run mode
        # Backend adapter (PyAutoGUI / OS) MUST NEVER have received any real hardware clicks
        mock_backend.click.assert_not_called()
        mock_backend.double_click.assert_not_called()
        mock_backend.right_click.assert_not_called()
        mock_backend.type_text.assert_not_called()
        mock_backend.paste_text.assert_not_called()

        # But UIDriver MUST have recorded action history in memory
        assert len(ui_driver.action_history) > 30
        for action in ui_driver.action_history:
            assert action.dry_run is True

        # 5. Verify all 14 Workflow steps completed for each task
        for task_res in agent.execution_history:
            assert task_res.status == "SUCCESS"
            assert len(task_res.steps_completed) >= 14
            assert WorkflowStep.STEP_0_HOME in task_res.steps_completed
            assert WorkflowStep.STEP_1_OPEN_SEARCH in task_res.steps_completed
            assert WorkflowStep.STEP_2_INPUT_FUNCTION_SEARCH in task_res.steps_completed
            assert WorkflowStep.STEP_12_CLOSE_TEST_MODULE in task_res.steps_completed
            assert WorkflowStep.STEP_13_ENTER_VERSION_COMMENT in task_res.steps_completed
            assert WorkflowStep.STEP_14_CLOSE_OBJECT_RETURN_HOME in task_res.steps_completed

        # 6. Verify Controller Session State via API
        status_res = controller_client.get_session_status()
        assert status_res["total"] == 3
        assert status_res["success"] == 3
        assert status_res["failed"] == 0
        assert status_res["pending"] == 0
        assert status_res["total_blocks_modified"] == 6
        assert status_res["is_completed"] is True

        # 7. Verify Logging Artifacts on Disk
        session_dir = logs_dir / session_id
        assert session_dir.exists()

        summary_file = session_dir / "summary.json"
        assert summary_file.exists()
        with open(summary_file, "r", encoding="utf-8") as f:
            summary_data = json.load(f)
        assert summary_data["total"] == 3
        assert summary_data["success"] == 3
        assert summary_data["failed"] == 0
        assert summary_data["total_blocks_modified"] == 6

        state_file = session_dir / "state.json"
        assert state_file.exists()
        with open(state_file, "r", encoding="utf-8") as f:
            state_data = json.load(f)
        assert len(state_data["tasks"]) == 3
        for t in state_data["tasks"]:
            assert t["status"] == "SUCCESS"
            assert t["duration_seconds"] is not None
            assert t["completed_at"] is not None


class TestDryRunResumeAndRecovery:
    """Tests for session interruption, resume, and error handling in Dry-Run mode."""

    def test_session_resume_after_interruption(self, dry_run_environment):
        """Verify that an interrupted Dry-Run session resumes from the exact checkpoint."""
        env = dry_run_environment
        controller_client = env["controller_client"]
        orchestrator = env["orchestrator"]

        gff_batch = ["Func_A", "Func_B", "Func_C"]
        session_id = "run_resume_test"

        # 1. Start Session
        controller_client.start_session(session_id=session_id, gff_list=gff_batch, force_new=True)

        # 2. Complete Task 1
        t1 = controller_client.get_next_task()
        assert t1["task_id"] == "GFF_001"
        controller_client.complete_task(
            task_id="GFF_001",
            status="SUCCESS",
            blocks_modified={"message": 1, "comment": 0, "question": 0},
            duration_seconds=5.0,
        )

        # 3. Simulate Task 2 being fetched and interrupted mid-way (worker crashed)
        t2 = controller_client.get_next_task()
        assert t2["task_id"] == "GFF_002"
        # Task 2 is now IN_PROGRESS in state.json

        # 4. Simulate Worker Restart: Start session with resume=True
        resume_res = controller_client.start_session(session_id=session_id, resume=True, force_new=False)
        assert resume_res["resumed"] is True

        # Task 2 should have been reset from IN_PROGRESS back to PENDING
        task_resumed = controller_client.get_next_task()
        assert task_resumed["task_id"] == "GFF_002"

        # Complete Task 2
        controller_client.complete_task(
            task_id="GFF_002",
            status="SUCCESS",
            blocks_modified={"message": 0, "comment": 1, "question": 0},
            duration_seconds=6.0,
        )

        # Complete Task 3
        t3 = controller_client.get_next_task()
        assert t3["task_id"] == "GFF_003"
        controller_client.complete_task(
            task_id="GFF_003",
            status="SUCCESS",
            blocks_modified={"message": 0, "comment": 0, "question": 1},
            duration_seconds=4.0,
        )

        # Queue should now be exhausted
        assert controller_client.get_next_task() is None

        # Verify final session summary
        summary = controller_client.get_session_status()
        assert summary["total"] == 3
        assert summary["success"] == 3
        assert summary["pending"] == 0
        assert summary["is_completed"] is True

    def test_dry_run_batch_with_one_failure_continues(self, dry_run_environment):
        """Verify that if one GFF fails, error is recorded with screenshot and batch continues."""
        env = dry_run_environment
        controller_client = env["controller_client"]
        logs_dir = env["logs_dir"]

        gff_batch = ["Func_Good_1", "Func_Broken", "Func_Good_2"]
        session_id = "run_failure_test"

        controller_client.start_session(session_id=session_id, gff_list=gff_batch, force_new=True)

        runner = WorkflowRunner(
            settings=env["settings"],
            ui_driver=env["ui_driver"],
            screen_capture=env["screen_capture"],
            controller_client=controller_client,
            dry_run=True,
            action_delay=0.0,
        )

        # Make Func_Broken fail during step 4
        original_step4 = runner.step_4_select_function_result

        def step4_hook(name):
            if name == "Func_Broken":
                raise TimeoutError("Function row not found in Search Results within 10s")
            return original_step4(name)

        runner.step_4_select_function_result = step4_hook

        agent = WorkerAgent(
            settings=env["settings"],
            controller_client=controller_client,
            workflow_runner=runner,
            dry_run=True,
            poll_interval=0.01,
        )

        summary = agent.run(max_tasks=3)
        assert summary["tasks_processed"] == 3
        assert summary["tasks_succeeded"] == 2
        assert summary["tasks_failed"] == 1

        # Check session status
        sess_status = controller_client.get_session_status()
        assert sess_status["total"] == 3
        assert sess_status["success"] == 2
        assert sess_status["failed"] == 1
        assert sess_status["is_completed"] is True

        # Check that error screenshot folder contains the failure screenshot
        errors_dir = logs_dir / session_id / "errors"
        assert errors_dir.exists()
        error_pngs = list(errors_dir.glob("*.png"))
        assert len(error_pngs) >= 1
        assert any("Func_Broken" in p.name for p in error_pngs)


class TestTextCleanerTagPreservationInDryRun:
    """Verify inviolability of tags and variables during batch sanitization."""

    def test_text_sanitization_invariants(self, dry_run_environment):
        controller_client = dry_run_environment["controller_client"]

        test_cases = [
            (
                "MESSAGE",
                "- Disconnect Lamborghini battery connector\n\n@[std]AU00003_Ende",
                "- Disconnect battery connector\n\n@[std]AU00003_Ende",
            ),
            (
                "QUESTION",
                "Is Lamborghini ECU %str_Steuergeraet% responding?",
                "Is ECU %str_Steuergeraet% responding?",
            ),
            (
                "COMMENT",
                "LAMBORGHINI specific calibration parameter for %str_Bauteil%",
                "Specific calibration parameter for %str_Bauteil%",
            ),
        ]

        for block_type, raw, expected in test_cases:
            res = controller_client.clean_text(raw_text=raw, block_type=block_type)
            assert res.modified is True
            assert res.cleaned_text == expected
            assert "Lamborghini" not in res.cleaned_text
            assert "LAMBORGHINI" not in res.cleaned_text


class TestLiveNetworkHTTPDryRun:
    """Tests full end-to-end HTTP REST communication over live TCP socket simulating Wi-Fi LAN."""

    def test_live_socket_http_batch_dry_run(self, tmp_path: Path):
        import socket
        import threading
        import time
        import uvicorn

        logs_dir = tmp_path / "live_logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        # 1. Find free port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()

        settings = Settings(
            host="127.0.0.1",
            port=port,
            dry_run=True,
            logs_dir_override=logs_dir,
            target_keyword="Lamborghini",
            action_delay=0.0,
        )

        app = create_app(settings=settings)
        mock_vision = MagicMock(spec=VisionEngine)
        mock_vision.analyze_canvas.return_value = CanvasAnalysisResponse(
            blocks=[
                DetectedBlock(type=BlockType.MESSAGE, relative_x=0.45, relative_y=0.30, label="Live Message"),
            ],
            task_id="Live_Task",
            total_detected=1,
        )
        mock_vision.detect_popup.return_value = PopupDetectionResult(detected=False, popup_type=PopupType.NONE)
        app.dependency_overrides[get_vision_engine] = lambda: mock_vision

        server_config = uvicorn.Config(app=app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(server_config)

        # Run uvicorn in daemon thread
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()

        # Wait for server ready
        base_url = f"http://127.0.0.1:{port}"
        client = ControllerClient(base_url=base_url, timeout=5.0)

        server_ready = False
        for _ in range(50):
            try:
                health = client.check_health()
                if health.get("status") in ("ok", "degraded"):
                    server_ready = True
                    break
            except Exception:
                time.sleep(0.05)

        assert server_ready is True, "Live FastAPI server failed to start within timeout"

        try:
            # Configure Mock UI Driver & Runner in Dry Run
            mock_backend = MagicMock(spec=BackendAdapter)
            ui_driver = UIDriver(dry_run=True, action_delay=0.0, backend=mock_backend)
            mock_capture = MagicMock(spec=ScreenCapture)
            mock_capture.capture_as_base64.return_value = (
                "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            )
            mock_capture.get_screen_size.return_value = (1920, 1080)

            runner = WorkflowRunner(
                settings=settings,
                ui_driver=ui_driver,
                screen_capture=mock_capture,
                controller_client=client,
                dry_run=True,
                action_delay=0.0,
                text_supplier=lambda b: "Lamborghini test message",
            )

            agent = WorkerAgent(
                settings=settings,
                controller_client=client,
                workflow_runner=runner,
                dry_run=True,
                poll_interval=0.01,
            )

            # Start session with 3 GFFs over real HTTP REST
            gffs = ["Live_GFF_01", "Live_GFF_02", "Live_GFF_03"]
            session_id = "run_live_tcp_test"
            start_data = client.start_session(session_id=session_id, gff_list=gffs, force_new=True)
            assert start_data["total_gff"] == 3
            assert start_data["pending"] == 3

            # Run agent batch
            summary = agent.run(max_tasks=3)
            assert summary["tasks_processed"] == 3
            assert summary["tasks_succeeded"] == 3
            assert summary["tasks_failed"] == 0
            assert summary["dry_run"] is True

            # Verify session status over HTTP REST
            status = client.get_session_status()
            assert status["total"] == 3
            assert status["success"] == 3
            assert status["pending"] == 0
            assert status["is_completed"] is True

        finally:
            server.should_exit = True
            server_thread.join(timeout=3.0)


class TestEdgeCasesAndRecoveryInDryRun:
    """Tests for edge cases, error recovery, input files, and task limits in Dry-Run mode."""

    def test_dry_run_with_empty_canvas_no_target_blocks(self, dry_run_environment):
        """Verify workflow completes gracefully when no target blocks are detected on canvas."""
        env = dry_run_environment
        controller_client = env["controller_client"]
        mock_vision = env["mock_vision"]

        # Vision returns 0 blocks
        mock_vision.analyze_canvas.return_value = CanvasAnalysisResponse(
            blocks=[],
            task_id="Empty_GFF",
            total_detected=0,
        )

        runner = WorkflowRunner(
            settings=env["settings"],
            ui_driver=env["ui_driver"],
            screen_capture=env["screen_capture"],
            controller_client=controller_client,
            dry_run=True,
            action_delay=0.0,
        )

        agent = WorkerAgent(
            settings=env["settings"],
            controller_client=controller_client,
            workflow_runner=runner,
            dry_run=True,
            poll_interval=0.01,
        )

        controller_client.start_session(session_id="run_empty_canvas", gff_list=["Empty_GFF"], force_new=True)
        summary = agent.run(max_tasks=1)

        assert summary["tasks_processed"] == 1
        assert summary["tasks_succeeded"] == 1
        assert summary["total_blocks_modified"] == 0

    def test_dry_run_with_unmodified_text_cancels_dialog(self, dry_run_environment):
        """Verify that blocks without the target keyword are not modified and closed with Cancel."""
        env = dry_run_environment
        controller_client = env["controller_client"]
        mock_vision = env["mock_vision"]

        mock_vision.analyze_canvas.return_value = CanvasAnalysisResponse(
            blocks=[
                DetectedBlock(type=BlockType.MESSAGE, relative_x=0.45, relative_y=0.30, label="Neutral text"),
            ],
            task_id="Neutral_GFF",
            total_detected=1,
        )

        runner = WorkflowRunner(
            settings=env["settings"],
            ui_driver=env["ui_driver"],
            screen_capture=env["screen_capture"],
            controller_client=controller_client,
            dry_run=True,
            action_delay=0.0,
            text_supplier=lambda b: "Standard neutral diagnostic instruction without target word.",
        )

        agent = WorkerAgent(
            settings=env["settings"],
            controller_client=controller_client,
            workflow_runner=runner,
            dry_run=True,
            poll_interval=0.01,
        )

        controller_client.start_session(session_id="run_neutral_text", gff_list=["Neutral_GFF"], force_new=True)
        summary = agent.run(max_tasks=1)

        assert summary["tasks_processed"] == 1
        assert summary["tasks_succeeded"] == 1
        assert summary["total_blocks_modified"] == 0

    def test_dry_run_batch_from_input_file(self, dry_run_environment, tmp_path: Path):
        """Verify batch session initialization directly from an input file path."""
        env = dry_run_environment
        controller_client = env["controller_client"]

        # Create input file
        input_file = tmp_path / "custom_input.txt"
        input_file.write_text("GFF_FILE_1\nGFF_FILE_2\n# Comment line\n\nGFF_FILE_3\n", encoding="utf-8")

        start_res = controller_client.start_session(
            session_id="run_input_file_test",
            input_file=str(input_file),
            force_new=True,
        )

        assert start_res["total_gff"] == 3
        assert start_res["pending"] == 3

    def test_dry_run_max_tasks_limit(self, dry_run_environment):
        """Verify worker stops after max_tasks even when more tasks remain in queue."""
        env = dry_run_environment
        controller_client = env["controller_client"]

        gffs = ["GFF_1", "GFF_2", "GFF_3", "GFF_4", "GFF_5"]
        controller_client.start_session(session_id="run_max_tasks_limit", gff_list=gffs, force_new=True)

        runner = WorkflowRunner(
            settings=env["settings"],
            ui_driver=env["ui_driver"],
            screen_capture=env["screen_capture"],
            controller_client=controller_client,
            dry_run=True,
            action_delay=0.0,
        )

        agent = WorkerAgent(
            settings=env["settings"],
            controller_client=controller_client,
            workflow_runner=runner,
            dry_run=True,
            poll_interval=0.01,
        )

        # Run with max_tasks=2
        summary = agent.run(max_tasks=2)

        assert summary["tasks_processed"] == 2
        assert summary["tasks_succeeded"] == 2

        status = controller_client.get_session_status()
        assert status["total"] == 5
        assert status["success"] == 2
        assert status["pending"] == 3
        assert status["is_completed"] is False


