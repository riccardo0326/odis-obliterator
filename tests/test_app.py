"""API endpoint and integration tests for FastAPI Controller (controller/app.py) - TASK-005."""

import base64
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from controller.app import create_app, get_kelpie_client, get_orchestrator, get_vision_engine
from controller.config import Settings
from controller.kelpie_client import KelpieClient, KelpieError, KelpieRequestError
from controller.orchestrator import GFFOrchestrator, TaskStatus
from controller.vision_engine import (
    BlockType,
    CanvasAnalysisResponse,
    DetectedBlock,
    PopupDetectionResult,
    PopupType,
    VisionEngine,
)


@pytest.fixture
def temp_logs_dir(tmp_path: Path) -> Path:
    """Fixture providing temporary logs directory."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


@pytest.fixture
def test_app_and_client(temp_logs_dir: Path):
    """Fixture providing configured FastAPI TestClient with isolated test environment."""
    test_settings = Settings(
        logs_dir_override=temp_logs_dir,
        target_keyword="Lamborghini",
        kelpie_model="gemini-3.7-flash",
    )

    test_orchestrator = GFFOrchestrator(settings=test_settings, logs_dir=temp_logs_dir)
    mock_kelpie = MagicMock(spec=KelpieClient)
    mock_kelpie.check_health.return_value = {
        "status": "ok",
        "kelpie": "connected",
        "model": "gemini-3.7-flash",
    }
    mock_vision_engine = MagicMock(spec=VisionEngine)

    app = create_app(settings=test_settings)

    # Override dependencies
    app.dependency_overrides[get_orchestrator] = lambda: test_orchestrator
    app.dependency_overrides[get_kelpie_client] = lambda: mock_kelpie
    app.dependency_overrides[get_vision_engine] = lambda: mock_vision_engine

    client = TestClient(app)
    return {
        "app": app,
        "client": client,
        "orchestrator": test_orchestrator,
        "mock_kelpie": mock_kelpie,
        "mock_vision_engine": mock_vision_engine,
        "logs_dir": temp_logs_dir,
    }


class TestRootAndDocs:
    """Tests for root, OpenAPI docs, and static endpoints."""

    def test_root_endpoint(self, test_app_and_client):
        client = test_app_and_client["client"]
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "ODIS Obliterator Controller"
        assert data["version"] == "1.0.0"
        assert data["docs"] == "/docs"

    def test_openapi_schema(self, test_app_and_client):
        client = test_app_and_client["client"]
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert "paths" in schema
        assert "/api/v1/health" in schema["paths"]
        assert "/api/v1/session/start" in schema["paths"]
        assert "/api/v1/tasks/next" in schema["paths"]
        assert "/api/v1/vision/analyze-canvas" in schema["paths"]
        assert "/api/v1/text/clean" in schema["paths"]
        assert "/api/v1/tasks/complete" in schema["paths"]

    def test_docs_ui(self, test_app_and_client):
        client = test_app_and_client["client"]
        response = client.get("/docs")
        assert response.status_code == 200
        assert "swagger-ui" in response.text.lower()


class TestHealthEndpoint:
    """Tests for /api/v1/health endpoint."""

    def test_health_ok(self, test_app_and_client):
        client = test_app_and_client["client"]
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["kelpie"] == "connected"
        assert data["model"] == "gemini-3.7-flash"
        assert data["session_active"] is False

    def test_health_degraded_when_kelpie_unreachable(self, test_app_and_client):
        client = test_app_and_client["client"]
        mock_kelpie = test_app_and_client["mock_kelpie"]
        mock_kelpie.check_health.return_value = {
            "status": "error",
            "kelpie": "unreachable",
            "error": "Connection refused",
        }

        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["kelpie"] == "unreachable"


class TestSessionEndpoints:
    """Tests for /api/v1/session/start and /api/v1/session/status."""

    def test_session_start_with_gff_list(self, test_app_and_client):
        client = test_app_and_client["client"]
        payload = {
            "session_id": "run_test_session_01",
            "gff_list": ["GFF_Func_1", "GFF_Func_2", "GFF_Func_3"],
            "force_new": True,
        }
        response = client.post("/api/v1/session/start", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "run_test_session_01"
        assert data["total_gff"] == 3
        assert data["pending"] == 3
        assert data["completed"] == 0
        assert data["failed"] == 0

    def test_session_status_summary(self, test_app_and_client):
        client = test_app_and_client["client"]
        orchestrator = test_app_and_client["orchestrator"]

        # Before any session
        response = client.get("/api/v1/session/status")
        assert response.status_code == 404

        # Start session
        orchestrator.start_session(session_id="run_summary_test", gff_list=["Task_A", "Task_B"], force_new=True)

        response = client.get("/api/v1/session/status")
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "run_summary_test"
        assert data["total"] == 2
        assert data["pending"] == 2
        assert data["success"] == 0
        assert data["is_completed"] is False


class TestTasksLifecycleEndpoints:
    """Tests for /api/v1/tasks/next, /api/v1/tasks/complete, and /api/v1/tasks/{task_id}."""

    def test_tasks_next_and_exhaustion(self, test_app_and_client):
        client = test_app_and_client["client"]
        orchestrator = test_app_and_client["orchestrator"]

        orchestrator.start_session(session_id="run_tasks_test", gff_list=["Func_X", "Func_Y"], force_new=True)

        # 1. Fetch first task
        resp1 = client.get("/api/v1/tasks/next")
        assert resp1.status_code == 200
        task1_data = resp1.json()
        assert task1_data["task_id"] == "GFF_001"
        assert task1_data["name"] == "Func_X"

        # 2. Fetch second task
        resp2 = client.get("/api/v1/tasks/next")
        assert resp2.status_code == 200
        task2_data = resp2.json()
        assert task2_data["task_id"] == "GFF_002"
        assert task2_data["name"] == "Func_Y"

        # 3. Fetch when no pending tasks remain
        resp3 = client.get("/api/v1/tasks/next")
        assert resp3.status_code == 204

    def test_tasks_complete_success(self, test_app_and_client):
        client = test_app_and_client["client"]
        orchestrator = test_app_and_client["orchestrator"]

        orchestrator.start_session(session_id="run_comp_test", gff_list=["Func_Success"], force_new=True)
        task = orchestrator.get_next_task()

        payload = {
            "task_id": task.task_id,
            "status": "SUCCESS",
            "blocks_modified": {"message": 2, "comment": 1, "question": 0},
            "duration_seconds": 14.2,
        }
        response = client.post("/api/v1/tasks/complete", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "recorded"
        assert data["task_id"] == "GFF_001"
        assert data["task_status"] == "SUCCESS"
        assert data["remaining"] == 0
        assert data["session_completed"] is True

    def test_tasks_complete_failure_with_screenshot(self, test_app_and_client):
        client = test_app_and_client["client"]
        orchestrator = test_app_and_client["orchestrator"]

        orchestrator.start_session(session_id="run_fail_test", gff_list=["Func_Fail"], force_new=True)
        task = orchestrator.get_next_task()

        sample_png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

        payload = {
            "task_id": task.task_id,
            "status": "FAILED",
            "error_details": "Element not clickable",
            "error_screenshot_base64": f"data:image/png;base64,{sample_png_b64}",
            "duration_seconds": 8.0,
        }
        response = client.post("/api/v1/tasks/complete", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["task_status"] == "FAILED"

    def test_tasks_complete_not_found_returns_404(self, test_app_and_client):
        client = test_app_and_client["client"]
        orchestrator = test_app_and_client["orchestrator"]
        orchestrator.start_session(session_id="run_404_test", gff_list=["Func_1"], force_new=True)

        payload = {
            "task_id": "GFF_999",
            "status": "SUCCESS",
        }
        response = client.post("/api/v1/tasks/complete", json=payload)
        assert response.status_code == 404

    def test_tasks_complete_invalid_status_returns_400(self, test_app_and_client):
        client = test_app_and_client["client"]
        orchestrator = test_app_and_client["orchestrator"]
        orchestrator.start_session(session_id="run_bad_stat", gff_list=["Func_1"], force_new=True)

        payload = {
            "task_id": "GFF_001",
            "status": "INVALID_STATUS_CODE",
        }
        response = client.post("/api/v1/tasks/complete", json=payload)
        assert response.status_code == 400

    def test_get_task_by_id(self, test_app_and_client):
        client = test_app_and_client["client"]
        orchestrator = test_app_and_client["orchestrator"]
        orchestrator.start_session(session_id="run_by_id", gff_list=["Func_Target"], force_new=True)

        # Existing task
        resp = client.get("/api/v1/tasks/GFF_001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "GFF_001"
        assert data["name"] == "Func_Target"
        assert data["status"] == "PENDING"

        # Non-existing task
        resp_404 = client.get("/api/v1/tasks/GFF_999")
        assert resp_404.status_code == 404


class TestTextCleanEndpoint:
    """Tests for /api/v1/text/clean endpoint."""

    def test_clean_text_with_target_keyword(self, test_app_and_client):
        client = test_app_and_client["client"]
        payload = {
            "block_type": "MESSAGE",
            "raw_text": "- Ignore the event memory Lamborghini entry\n\n@[std]AU00003_Ende",
        }
        response = client.post("/api/v1/text/clean", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["modified"] is True
        assert data["cleaned_text"] == "- Ignore the event memory entry\n\n@[std]AU00003_Ende"
        assert data["occurrences_removed"] == 1

    def test_clean_text_preserves_dynamic_variables(self, test_app_and_client):
        client = test_app_and_client["client"]
        payload = {
            "block_type": "QUESTION",
            "raw_text": "Is Lamborghini %str_Bauteil% installed correctly?",
        }
        response = client.post("/api/v1/text/clean", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["modified"] is True
        assert data["cleaned_text"] == "Is %str_Bauteil% installed correctly?"

    def test_clean_text_already_clean(self, test_app_and_client):
        client = test_app_and_client["client"]
        payload = {
            "block_type": "COMMENT",
            "raw_text": "1 = static error, 2 = dynamic error",
        }
        response = client.post("/api/v1/text/clean", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["modified"] is False
        assert data["cleaned_text"] == "1 = static error, 2 = dynamic error"
        assert data["occurrences_removed"] == 0


class TestVisionEndpoints:
    """Tests for /api/v1/vision/analyze-canvas and /api/v1/vision/detect-popup."""

    def test_analyze_canvas_endpoint(self, test_app_and_client):
        client = test_app_and_client["client"]
        mock_vision = test_app_and_client["mock_vision_engine"]

        mock_vision.analyze_canvas.return_value = CanvasAnalysisResponse(
            blocks=[
                DetectedBlock(type=BlockType.MESSAGE, relative_x=0.45, relative_y=0.32, label="Msg 1"),
                DetectedBlock(type=BlockType.QUESTION, relative_x=0.55, relative_y=0.60, label="Quest 1"),
            ],
            task_id="GFF_001",
            total_detected=2,
            execution_time_seconds=0.85,
        )

        payload = {
            "task_id": "GFF_001",
            "image_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            "canvas_bbox": {"x": 500, "y": 100, "width": 1400, "height": 900},
        }

        response = client.post("/api/v1/vision/analyze-canvas", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["total_detected"] == 2
        assert len(data["blocks"]) == 2
        assert data["blocks"][0]["type"] == "MESSAGE"
        assert data["blocks"][1]["type"] == "QUESTION"

    def test_analyze_canvas_gateway_error(self, test_app_and_client):
        client = test_app_and_client["client"]
        mock_vision = test_app_and_client["mock_vision_engine"]
        mock_vision.analyze_canvas.side_effect = KelpieRequestError("Gateway timeout", status_code=504)

        payload = {
            "image_base64": "dummy_b64",
        }
        response = client.post("/api/v1/vision/analyze-canvas", json=payload)
        assert response.status_code == 502
        assert "Kelpie gateway error" in response.json()["detail"]

    def test_detect_popup_endpoint(self, test_app_and_client):
        client = test_app_and_client["client"]
        mock_vision = test_app_and_client["mock_vision_engine"]

        mock_vision.detect_popup.return_value = PopupDetectionResult(
            detected=True,
            popup_type=PopupType.VALIDATION_ERROR,
            title="Validation error",
            message="Dialog validation failed. Please enter correct data.",
            ok_button_relative_x=0.52,
            ok_button_relative_y=0.60,
        )

        payload = {
            "image_base64": "dummy_screenshot_b64",
        }
        response = client.post("/api/v1/vision/detect-popup", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["detected"] is True
        assert data["popup_type"] == "VALIDATION_ERROR"
        assert data["ok_button_relative_x"] == 0.52


class TestEndToEndBatchWorkflow:
    """Full end-to-end integration simulation test across API endpoints."""

    def test_full_batch_simulation(self, test_app_and_client):
        client = test_app_and_client["client"]

        # 1. Health check
        health_resp = client.get("/api/v1/health")
        assert health_resp.status_code == 200

        # 2. Start session with 2 GFFs
        start_payload = {
            "session_id": "run_e2e_simulation",
            "gff_list": [
                "A16_4LA_91____1_518_88_Check_battery",
                "LB63x_01____2_100_01_Engine_control",
            ],
            "force_new": True,
        }
        start_resp = client.post("/api/v1/session/start", json=start_payload)
        assert start_resp.status_code == 200
        assert start_resp.json()["total_gff"] == 2
        assert start_resp.json()["pending"] == 2

        # 3. Worker polls for first task
        next1 = client.get("/api/v1/tasks/next")
        assert next1.status_code == 200
        task1 = next1.json()
        assert task1["task_id"] == "GFF_001"
        assert task1["name"] == "A16_4LA_91____1_518_88_Check_battery"

        # 4. Worker cleans text block
        clean_resp = client.post(
            "/api/v1/text/clean",
            json={
                "block_type": "MESSAGE",
                "raw_text": "- Ignore the Lamborghini event memory entry\n@[std]AU00003_Ende",
            },
        )
        assert clean_resp.status_code == 200
        clean_data = clean_resp.json()
        assert clean_data["modified"] is True

        # 5. Worker completes task 1
        comp1 = client.post(
            "/api/v1/tasks/complete",
            json={
                "task_id": "GFF_001",
                "status": "SUCCESS",
                "blocks_modified": {"message": 1, "comment": 0, "question": 0},
                "duration_seconds": 15.5,
            },
        )
        assert comp1.status_code == 200
        assert comp1.json()["remaining"] == 1
        assert comp1.json()["session_completed"] is False

        # 6. Worker polls for second task
        next2 = client.get("/api/v1/tasks/next")
        assert next2.status_code == 200
        task2 = next2.json()
        assert task2["task_id"] == "GFF_002"

        # 7. Worker completes task 2
        comp2 = client.post(
            "/api/v1/tasks/complete",
            json={
                "task_id": "GFF_002",
                "status": "SUCCESS",
                "blocks_modified": {"message": 0, "comment": 1, "question": 1},
                "duration_seconds": 22.0,
            },
        )
        assert comp2.status_code == 200
        assert comp2.json()["remaining"] == 0
        assert comp2.json()["session_completed"] is True

        # 8. Worker polls again -> 204 No Content
        next3 = client.get("/api/v1/tasks/next")
        assert next3.status_code == 204

        # 9. Check session summary
        summary_resp = client.get("/api/v1/session/status")
        assert summary_resp.status_code == 200
        summary = summary_resp.json()
        assert summary["total"] == 2
        assert summary["success"] == 2
        assert summary["failed"] == 0
        assert summary["pending"] == 0
        assert summary["total_blocks_modified"] == 3
        assert summary["is_completed"] is True
