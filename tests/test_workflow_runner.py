"""Unit tests for WorkflowRunner and End-to-End 14-Step Automation (TASK-008)."""

from datetime import datetime
from unittest.mock import MagicMock, call, patch
from PIL import Image
import pytest
import requests

from controller.config import Settings
from controller.text_cleaner import TextCleaner, TextCleanResponse
from controller.vision_engine import (
    BlockType,
    CanvasBoundingBox,
    DetectedBlock,
    PopupDetectionResult,
    PopupType,
    VisionEngine,
)
from worker.screen_capture import ScreenCapture, ScreenRegion
from worker.ui_driver import BackendAdapter, UIActionType, UIDriver
from worker.workflow_runner import (
    ControllerClient,
    WorkflowCoordinates,
    WorkflowExecutionResult,
    WorkflowRunner,
    WorkflowStep,
    get_workflow_runner,
)
from worker.local_vision import LocalVisionEngine


# ---------------------------------------------------------------------------
# Test Enums and Configuration Models
# ---------------------------------------------------------------------------

class TestWorkflowModels:
    """Tests for WorkflowStep enum, WorkflowCoordinates, and WorkflowExecutionResult."""

    def test_workflow_steps_enum_members(self):
        assert WorkflowStep.STEP_0_HOME == "STEP_0_HOME"
        assert WorkflowStep.STEP_1_OPEN_SEARCH == "STEP_1_OPEN_SEARCH"
        assert WorkflowStep.STEP_2_INPUT_FUNCTION_SEARCH == "STEP_2_INPUT_FUNCTION_SEARCH"
        assert WorkflowStep.STEP_3_CLOSE_SEARCH_ENDED_POPUP == "STEP_3_CLOSE_SEARCH_ENDED_POPUP"
        assert WorkflowStep.STEP_4_SELECT_FUNCTION_RESULT == "STEP_4_SELECT_FUNCTION_RESULT"
        assert WorkflowStep.STEP_5_SELECT_USAGE_LOCATION == "STEP_5_SELECT_USAGE_LOCATION"
        assert WorkflowStep.STEP_6_OPEN_TEST_SEQUENCE == "STEP_6_OPEN_TEST_SEQUENCE"
        assert WorkflowStep.STEP_7_MINIMIZE_PANELS == "STEP_7_MINIMIZE_PANELS"
        assert WorkflowStep.STEP_8_EXPAND_CANVAS_AND_SCAN == "STEP_8_EXPAND_CANVAS_AND_SCAN"
        assert WorkflowStep.STEP_9_EDIT_MESSAGE_BLOCK == "STEP_9_EDIT_MESSAGE_BLOCK"
        assert WorkflowStep.STEP_10_EDIT_COMMENT_BLOCK == "STEP_10_EDIT_COMMENT_BLOCK"
        assert WorkflowStep.STEP_11_EDIT_QUESTION_BLOCK == "STEP_11_EDIT_QUESTION_BLOCK"
        assert WorkflowStep.STEP_12_CLOSE_TEST_MODULE == "STEP_12_CLOSE_TEST_MODULE"
        assert WorkflowStep.STEP_13_ENTER_VERSION_COMMENT == "STEP_13_ENTER_VERSION_COMMENT"
        assert WorkflowStep.STEP_14_CLOSE_OBJECT_RETURN_HOME == "STEP_14_CLOSE_OBJECT_RETURN_HOME"

    def test_workflow_coordinates_defaults(self):
        coords = WorkflowCoordinates()
        assert coords.toolbar_search_button == (340, 60)
        assert coords.search_dialog_full_text_tab == (620, 240)
        assert coords.search_dialog_input_field == (650, 290)
        assert coords.search_dialog_ok_button == (870, 520)
        assert coords.search_ended_ok_button == (960, 550)
        assert coords.search_results_first_row == (700, 650)
        assert coords.usage_locations_first_item == (750, 420)
        assert coords.usage_locations_ok_button == (980, 680)
        assert coords.tab_object_background == (600, 350)
        assert coords.context_menu_test_sequence == (650, 375)
        assert coords.palette_minimize_button == (1890, 110)
        assert coords.search_results_minimize_button == (1890, 750)
        assert coords.recent_objects_minimize_button == (1890, 920)
        assert coords.test_step_central_column == (400, 300)
        assert coords.canvas_bbox.x == 510
        assert coords.canvas_bbox.y == 120
        assert coords.canvas_bbox.width == 1400
        assert coords.canvas_bbox.height == 900
        assert coords.block_dialog_text_area == (700, 450)
        assert coords.block_dialog_ok_button == (900, 750)
        assert coords.block_dialog_cancel_button == (1000, 750)
        assert coords.test_module_close_x == (520, 90)
        assert coords.save_dialog_save_button == (900, 560)
        assert coords.version_comment_box == (600, 320)
        assert coords.object_tab_close_x == (380, 90)
        assert coords.validation_error_ok_button == (960, 560)

    def test_workflow_execution_result_model(self):
        res = WorkflowExecutionResult(
            task_id="GFF_001",
            gff_name="A16_4LA_91____1_518_88_Check_battery",
            status="SUCCESS",
            steps_completed=[WorkflowStep.STEP_0_HOME, WorkflowStep.STEP_1_OPEN_SEARCH],
            blocks_detected=3,
            blocks_modified={"message": 1, "comment": 1, "question": 0},
            duration_seconds=12.5,
        )
        assert res.task_id == "GFF_001"
        assert res.gff_name == "A16_4LA_91____1_518_88_Check_battery"
        assert res.status == "SUCCESS"
        assert len(res.steps_completed) == 2
        assert res.total_blocks_modified == 2
        assert res.error_details is None


# ---------------------------------------------------------------------------
# Test ControllerClient
# ---------------------------------------------------------------------------

class TestControllerClient:
    """Tests for ControllerClient REST and direct dispatch modes."""

    def test_clean_text_direct_mode(self):
        cleaner = TextCleaner()
        client = ControllerClient(text_cleaner=cleaner)

        resp = client.clean_text(
            raw_text="- Check the Lamborghini vehicle status.\n@[std]AU00003_Ende",
            block_type="MESSAGE",
        )
        assert resp.modified is True
        assert "Lamborghini" not in resp.cleaned_text
        assert "@[std]AU00003_Ende" in resp.cleaned_text

    def test_clean_text_rest_mode(self):
        client = ControllerClient(base_url="http://127.0.0.1:8000")
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "cleaned_text": "Sanitized text",
            "modified": True,
            "occurrences_removed": 1,
        }
        mock_response.raise_for_status.return_value = None

        with patch.object(client.session, "post", return_value=mock_response) as mock_post:
            res = client.clean_text("Raw text with Lamborghini", block_type="MESSAGE")
            assert res.cleaned_text == "Sanitized text"
            assert res.modified is True
            mock_post.assert_called_once()

    def test_analyze_canvas_direct_mode(self):
        mock_vision = MagicMock(spec=VisionEngine)
        mock_vision.analyze_canvas.return_value = MagicMock(
            blocks=[
                DetectedBlock(type=BlockType.MESSAGE, relative_x=0.45, relative_y=0.32, label="Message 1"),
                DetectedBlock(type=BlockType.QUESTION, relative_x=0.55, relative_y=0.65, label="Question 1"),
            ]
        )
        client = ControllerClient(vision_engine=mock_vision)

        blocks = client.analyze_canvas("fake_base64", task_id="GFF_001")
        assert len(blocks) == 2
        assert blocks[0].type == BlockType.MESSAGE
        assert blocks[1].type == BlockType.QUESTION

    def test_detect_popup_direct_mode(self):
        mock_vision = MagicMock(spec=VisionEngine)
        mock_vision.detect_popup.return_value = PopupDetectionResult(
            detected=True,
            popup_type=PopupType.VALIDATION_ERROR,
            title="Validation error",
            ok_button_relative_x=0.5,
            ok_button_relative_y=0.6,
        )
        client = ControllerClient(vision_engine=mock_vision)

        res = client.detect_popup("fake_base64")
        assert res.detected is True
        assert res.popup_type == PopupType.VALIDATION_ERROR
        assert res.title == "Validation error"

    def test_complete_task_rest_call(self):
        client = ControllerClient(base_url="http://127.0.0.1:8000")
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "recorded", "task_id": "GFF_001"}
        mock_response.raise_for_status.return_value = None

        with patch.object(client.session, "post", return_value=mock_response) as mock_post:
            res = client.complete_task(
                task_id="GFF_001",
                status="SUCCESS",
                blocks_modified={"message": 1, "comment": 0, "question": 0},
                duration_seconds=15.2,
            )
            assert res["status"] == "recorded"
            mock_post.assert_called_once()

    def test_check_health(self):
        client = ControllerClient(base_url="http://127.0.0.1:8000")
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "ok", "version": "1.0.0"}
        mock_response.raise_for_status.return_value = None

        with patch.object(client.session, "get", return_value=mock_response) as mock_get:
            res = client.check_health()
            assert res["status"] == "ok"
            mock_get.assert_called_once_with("http://127.0.0.1:8000/api/v1/health", timeout=60.0)

    def test_start_session(self):
        client = ControllerClient(base_url="http://127.0.0.1:8000")
        mock_response = MagicMock()
        mock_response.json.return_value = {"session_id": "run_123", "status": "started"}
        mock_response.raise_for_status.return_value = None

        with patch.object(client.session, "post", return_value=mock_response) as mock_post:
            res = client.start_session(session_id="run_123", gff_list=["fn1"], resume=True, force_new=False)
            assert res["session_id"] == "run_123"
            mock_post.assert_called_once()

    def test_get_next_task_found(self):
        client = ControllerClient(base_url="http://127.0.0.1:8000")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"task_id": "GFF_001", "name": "fn1"}
        mock_response.raise_for_status.return_value = None

        with patch.object(client.session, "get", return_value=mock_response):
            task = client.get_next_task()
            assert task is not None
            assert task["task_id"] == "GFF_001"

    def test_get_next_task_empty_204(self):
        client = ControllerClient(base_url="http://127.0.0.1:8000")
        mock_response = MagicMock()
        mock_response.status_code = 204

        with patch.object(client.session, "get", return_value=mock_response):
            task = client.get_next_task()
            assert task is None

    def test_get_session_status(self):
        client = ControllerClient(base_url="http://127.0.0.1:8000")
        mock_response = MagicMock()
        mock_response.json.return_value = {"total": 5, "success": 3}
        mock_response.raise_for_status.return_value = None

        with patch.object(client.session, "get", return_value=mock_response):
            res = client.get_session_status()
            assert res["total"] == 5

    def test_clean_text_api_failure_fallback(self):
        client = ControllerClient(base_url="http://127.0.0.1:8000")
        with patch.object(client.session, "post", side_effect=requests.RequestException("Connection refused")):
            res = client.clean_text("Lamborghini warning notice", block_type="MESSAGE")
            assert res.modified is True
            assert "Lamborghini" not in res.cleaned_text

    def test_analyze_canvas_rest_mode(self):
        client = ControllerClient(base_url="http://127.0.0.1:8000")
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "blocks": [
                {"type": "MESSAGE", "relative_x": 0.4, "relative_y": 0.3, "label": "Msg 1"}
            ]
        }
        mock_response.raise_for_status.return_value = None

        with patch.object(client.session, "post", return_value=mock_response):
            blocks = client.analyze_canvas("fake_img_b64", canvas_bbox=CanvasBoundingBox(x=0, y=0, width=100, height=100))
            assert len(blocks) == 1
            assert blocks[0].type == BlockType.MESSAGE

    def test_detect_popup_api_failure_fallback(self):
        client = ControllerClient(base_url="http://127.0.0.1:8000")
        with patch.object(client.session, "post", side_effect=requests.RequestException("Timeout")):
            res = client.detect_popup("fake_img_b64")
            assert res.detected is False
            assert res.popup_type == PopupType.NONE

    def test_complete_task_api_failure(self):
        client = ControllerClient(base_url="http://127.0.0.1:8000")
        with patch.object(client.session, "post", side_effect=requests.RequestException("Network down")):
            res = client.complete_task("GFF_001", "SUCCESS")
            assert res["status"] == "unreachable"
            assert "Network down" in res["error"]


# ---------------------------------------------------------------------------
# Test WorkflowRunner Steps in Isolation
# ---------------------------------------------------------------------------

class TestWorkflowRunnerSteps:
    """Detailed unit tests for each individual workflow step."""

    def setup_method(self):
        self.mock_backend = MagicMock(spec=BackendAdapter)
        self.ui_driver = UIDriver(dry_run=True, action_delay=0.0, backend=self.mock_backend)

        # Mock screen capture returning dummy image
        self.mock_capture = MagicMock(spec=ScreenCapture)
        self.dummy_img = Image.new("RGB", (1920, 1080), color=(200, 200, 200))
        self.mock_capture.capture_as_base64.return_value = "data:image/png;base64,dummy_b64"
        self.mock_capture.get_screen_size.return_value = (1920, 1080)

        # Direct text cleaner and mock client
        self.text_cleaner = TextCleaner()
        self.mock_client = ControllerClient(text_cleaner=self.text_cleaner)

        self.coords = WorkflowCoordinates()
        self.runner = WorkflowRunner(
            ui_driver=self.ui_driver,
            screen_capture=self.mock_capture,
            controller_client=self.mock_client,
            coordinates=self.coords,
            dry_run=True,
            action_delay=0.0,
        )

    def test_step_0_ensure_home(self):
        res = self.runner.step_0_ensure_home()
        assert res is True
        assert self.runner.current_step == WorkflowStep.STEP_0_HOME
        assert WorkflowStep.STEP_0_HOME in self.runner.completed_steps

    def test_step_1_open_search(self):
        res = self.runner.step_1_open_search()
        assert res is True
        assert self.runner.current_step == WorkflowStep.STEP_1_OPEN_SEARCH
        assert len(self.ui_driver.action_history) == 2
        # Action 0: Click toolbar search icon
        assert self.ui_driver.action_history[0].params["x"] == self.coords.toolbar_search_button[0]
        assert self.ui_driver.action_history[0].params["y"] == self.coords.toolbar_search_button[1]
        # Action 1: Click Full Text Search tab
        assert self.ui_driver.action_history[1].params["x"] == self.coords.search_dialog_full_text_tab[0]
        assert self.ui_driver.action_history[1].params["y"] == self.coords.search_dialog_full_text_tab[1]

    def test_step_2_input_function_search(self):
        gff_name = "A16_4LA_91____1_518_88_Check_battery"
        res = self.runner.step_2_input_function_search(gff_name)
        assert res is True
        assert self.runner.current_step == WorkflowStep.STEP_2_INPUT_FUNCTION_SEARCH
        # Verify text clear and type was performed
        typed_actions = [a for a in self.ui_driver.action_history if a.action_type == UIActionType.CLEAR_AND_TYPE]
        assert len(typed_actions) == 1
        assert typed_actions[0].params["text"] == gff_name

    def test_step_3_close_search_ended_popup(self):
        res = self.runner.step_3_close_search_ended_popup()
        assert res is True
        assert self.runner.current_step == WorkflowStep.STEP_3_CLOSE_SEARCH_ENDED_POPUP
        click_action = self.ui_driver.action_history[-1]
        assert click_action.params["x"] == self.coords.search_ended_ok_button[0]
        assert click_action.params["y"] == self.coords.search_ended_ok_button[1]

    def test_step_4_select_function_result(self):
        gff_name = "A16_4LA_91____1_518_88_Check_battery"
        res = self.runner.step_4_select_function_result(gff_name)
        assert res is True
        assert self.runner.current_step == WorkflowStep.STEP_4_SELECT_FUNCTION_RESULT
        dbl_click = [a for a in self.ui_driver.action_history if a.action_type == UIActionType.DOUBLE_CLICK][0]
        assert dbl_click.params["x"] == self.coords.search_results_first_row[0]
        assert dbl_click.params["y"] == self.coords.search_results_first_row[1]

    def test_step_5_select_usage_location(self):
        res = self.runner.step_5_select_usage_location()
        assert res is True
        assert self.runner.current_step == WorkflowStep.STEP_5_SELECT_USAGE_LOCATION
        assert len(self.ui_driver.action_history) >= 2

    def test_step_6_open_test_sequence(self):
        res = self.runner.step_6_open_test_sequence()
        assert res is True
        assert self.runner.current_step == WorkflowStep.STEP_6_OPEN_TEST_SEQUENCE
        # Action 0: Right click background
        assert self.ui_driver.action_history[0].action_type == UIActionType.RIGHT_CLICK
        # Action 1: Click Test sequence
        assert self.ui_driver.action_history[1].action_type == UIActionType.CLICK

    def test_step_7_minimize_panels(self):
        res = self.runner.step_7_minimize_panels()
        assert res is True
        assert self.runner.current_step == WorkflowStep.STEP_7_MINIMIZE_PANELS
        # Should click Palette, Search Results, Recently-Used minimize buttons
        assert len(self.ui_driver.action_history) == 3

    def test_step_8_expand_canvas_and_scan(self):
        mock_blocks = [
            DetectedBlock(type=BlockType.MESSAGE, relative_x=0.45, relative_y=0.32, label="Msg"),
            DetectedBlock(type=BlockType.QUESTION, relative_x=0.55, relative_y=0.65, label="Ques"),
        ]
        self.mock_client.analyze_canvas = MagicMock(return_value=mock_blocks)

        blocks = self.runner.step_8_expand_canvas_and_scan(task_id="GFF_001")
        assert len(blocks) == 2
        assert self.runner.current_step == WorkflowStep.STEP_8_EXPAND_CANVAS_AND_SCAN
        self.mock_client.analyze_canvas.assert_called_once()

    def test_step_8_uses_in_process_vision_provider(self):
        """Standalone mode must bypass ControllerClient canvas analysis."""
        self.mock_client.analyze_canvas = MagicMock()
        local_provider = MagicMock(spec=LocalVisionEngine)
        local_provider.analyze_canvas.return_value = MagicMock(
            blocks=[
                DetectedBlock(type=BlockType.COMMENT, relative_x=0.2, relative_y=0.4, label="Comment"),
            ]
        )
        self.runner = WorkflowRunner(
            ui_driver=self.ui_driver,
            screen_capture=self.mock_capture,
            controller_client=self.mock_client,
            vision_provider=local_provider,
            coordinates=self.coords,
            dry_run=True,
            action_delay=0.0,
        )

        blocks = self.runner.step_8_expand_canvas_and_scan(task_id="LOCAL_GFF")

        assert len(blocks) == 1
        assert blocks[0].type == BlockType.COMMENT
        local_provider.analyze_canvas.assert_called_once_with(
            image="data:image/png;base64,dummy_b64",
            canvas_bbox=self.coords.canvas_bbox,
            task_id="LOCAL_GFF",
        )
        self.mock_client.analyze_canvas.assert_not_called()

    def test_step_8_accepts_local_engine_alias(self):
        """The explicit local_vision_engine alias selects the in-process path."""
        self.mock_client.analyze_canvas = MagicMock()
        local_engine = MagicMock(spec=LocalVisionEngine)
        local_engine.analyze_canvas.return_value = [
            DetectedBlock(type=BlockType.MESSAGE, relative_x=0.1, relative_y=0.1)
        ]
        self.runner = WorkflowRunner(
            ui_driver=self.ui_driver,
            screen_capture=self.mock_capture,
            controller_client=self.mock_client,
            local_vision_engine=local_engine,
            coordinates=self.coords,
            dry_run=True,
            action_delay=0.0,
        )

        blocks = self.runner.step_8_expand_canvas_and_scan(task_id="LOCAL_ALIAS_GFF")

        assert len(blocks) == 1
        assert blocks[0].type == BlockType.MESSAGE
        local_engine.analyze_canvas.assert_called_once()
        self.mock_client.analyze_canvas.assert_not_called()

    def test_runner_rejects_two_vision_providers(self):
        """Provider selection is unambiguous."""
        with pytest.raises(ValueError, match="either vision_provider or local_vision_engine"):
            WorkflowRunner(
                ui_driver=self.ui_driver,
                screen_capture=self.mock_capture,
                controller_client=self.mock_client,
                vision_provider=MagicMock(),
                local_vision_engine=MagicMock(spec=LocalVisionEngine),
                coordinates=self.coords,
                dry_run=True,
                action_delay=0.0,
            )

    def test_edit_single_block_message_with_modification(self):
        block = DetectedBlock(
            type=BlockType.MESSAGE,
            relative_x=0.45,
            relative_y=0.32,
            label="Ignore Lamborghini entry",
        )
        self.runner.text_supplier = lambda b: "- Ignore the event memory Lamborghini entry\n\n@[std]AU00003_Ende"

        modified = self.runner.edit_single_block(block)
        assert modified is True
        assert self.runner.modified_blocks_count["message"] == 1

        # Check that clear_and_type was executed with sanitized text
        typed = [a for a in self.ui_driver.action_history if a.action_type == UIActionType.CLEAR_AND_TYPE]
        assert len(typed) == 1
        assert "Lamborghini" not in typed[0].params["text"]
        assert "@[std]AU00003_Ende" in typed[0].params["text"]

    def test_edit_single_block_comment_with_modification(self):
        block = DetectedBlock(
            type=BlockType.COMMENT,
            relative_x=0.5,
            relative_y=0.5,
            label="Lamborghini specific comment",
        )
        self.runner.text_supplier = lambda b: "Lamborghini test step commentary"

        modified = self.runner.edit_single_block(block)
        assert modified is True
        assert self.runner.modified_blocks_count["comment"] == 1

    def test_edit_single_block_question_with_modification(self):
        block = DetectedBlock(
            type=BlockType.QUESTION,
            relative_x=0.6,
            relative_y=0.7,
            label="Question for operator",
        )
        self.runner.text_supplier = lambda b: "Is the Lamborghini component %str_Bauteil% connected?"

        modified = self.runner.edit_single_block(block)
        assert modified is True
        assert self.runner.modified_blocks_count["question"] == 1

        typed = [a for a in self.ui_driver.action_history if a.action_type == UIActionType.CLEAR_AND_TYPE]
        assert len(typed) == 1
        assert "%str_Bauteil%" in typed[0].params["text"]
        assert "Lamborghini" not in typed[0].params["text"]

    def test_edit_single_block_without_modification(self):
        block = DetectedBlock(
            type=BlockType.MESSAGE,
            relative_x=0.4,
            relative_y=0.3,
            label="Clean message",
        )
        self.runner.text_supplier = lambda b: "General diagnostic message without target word"

        modified = self.runner.edit_single_block(block)
        assert modified is False
        assert self.runner.modified_blocks_count["message"] == 0

        # When not modified, Cancel button is clicked
        clicks = [a for a in self.ui_driver.action_history if a.action_type == UIActionType.CLICK]
        assert len(clicks) >= 1
        assert clicks[-1].params["x"] == self.coords.block_dialog_cancel_button[0]

    def test_step_9_to_11_process_blocks(self):
        blocks = [
            DetectedBlock(type=BlockType.MESSAGE, relative_x=0.45, relative_y=0.32, label="Msg"),
            DetectedBlock(type=BlockType.COMMENT, relative_x=0.50, relative_y=0.50, label="Comm"),
            DetectedBlock(type=BlockType.QUESTION, relative_x=0.55, relative_y=0.70, label="Quest"),
        ]
        self.runner.text_supplier = lambda b: f"Lamborghini reference in {b.type.value}"

        counts = self.runner.step_9_to_11_process_blocks(blocks)
        assert counts["message"] == 1
        assert counts["comment"] == 1
        assert counts["question"] == 1
        assert WorkflowStep.STEP_9_EDIT_MESSAGE_BLOCK in self.runner.completed_steps
        assert WorkflowStep.STEP_10_EDIT_COMMENT_BLOCK in self.runner.completed_steps
        assert WorkflowStep.STEP_11_EDIT_QUESTION_BLOCK in self.runner.completed_steps

    def test_step_12_close_test_module(self):
        res = self.runner.step_12_close_test_module()
        assert res is True
        assert self.runner.current_step == WorkflowStep.STEP_12_CLOSE_TEST_MODULE
        # Clicks 'X' and Save
        assert len(self.ui_driver.action_history) == 2
        assert self.ui_driver.action_history[0].params["x"] == self.coords.test_module_close_x[0]
        assert self.ui_driver.action_history[1].params["x"] == self.coords.save_dialog_save_button[0]

    def test_step_13_enter_version_comment(self):
        res = self.runner.step_13_enter_version_comment()
        assert res is True
        assert self.runner.current_step == WorkflowStep.STEP_13_ENTER_VERSION_COMMENT
        typed = [a for a in self.ui_driver.action_history if a.action_type == UIActionType.CLEAR_AND_TYPE]
        assert len(typed) == 1
        assert typed[0].params["text"] == "Removed Lamborghini labels"

    def test_step_14_close_object_return_home(self):
        res = self.runner.step_14_close_object_return_home()
        assert res is True
        assert self.runner.current_step == WorkflowStep.STEP_14_CLOSE_OBJECT_RETURN_HOME
        assert len(self.ui_driver.action_history) == 2
        assert self.ui_driver.action_history[0].params["x"] == self.coords.object_tab_close_x[0]
        assert self.ui_driver.action_history[1].params["x"] == self.coords.save_dialog_save_button[0]

    def test_edit_single_block_live_mode_with_clipboard(self):
        live_driver = UIDriver(dry_run=False, action_delay=0.0, backend=self.mock_backend)
        live_runner = WorkflowRunner(
            ui_driver=live_driver,
            screen_capture=self.mock_capture,
            controller_client=self.mock_client,
            dry_run=False,
            action_delay=0.0,
            text_supplier=None,
        )
        block = DetectedBlock(
            type=BlockType.MESSAGE,
            relative_x=0.45,
            relative_y=0.32,
            label="Original label",
        )
        with patch("pyperclip.paste", return_value="Live text with Lamborghini entry"):
            modified = live_runner.edit_single_block(block)
            assert modified is True
            assert live_runner.modified_blocks_count["message"] == 1

    def test_edit_single_block_live_mode_clipboard_exception(self):
        live_driver = UIDriver(dry_run=False, action_delay=0.0, backend=self.mock_backend)
        live_runner = WorkflowRunner(
            ui_driver=live_driver,
            screen_capture=self.mock_capture,
            controller_client=self.mock_client,
            dry_run=False,
            action_delay=0.0,
            text_supplier=None,
        )
        block = DetectedBlock(
            type=BlockType.MESSAGE,
            relative_x=0.45,
            relative_y=0.32,
            label="Fallback text with Lamborghini",
        )
        with patch("pyperclip.paste", side_effect=RuntimeError("Clipboard unavailable")):
            modified = live_runner.edit_single_block(block)
            assert modified is True
            assert live_runner.modified_blocks_count["message"] == 1


# ---------------------------------------------------------------------------
# Test Validation Error Popup Handling and Emergency Recovery
# ---------------------------------------------------------------------------

class TestEdgeCasesAndRecovery:
    """Tests for popup error handling and safe recovery."""

    def setup_method(self):
        self.mock_backend = MagicMock(spec=BackendAdapter)
        self.ui_driver = UIDriver(dry_run=False, action_delay=0.0, backend=self.mock_backend)
        self.mock_capture = MagicMock(spec=ScreenCapture)
        self.mock_capture.capture_as_base64.return_value = "data:image/png;base64,popup_b64"
        self.mock_capture.get_screen_size.return_value = (1920, 1080)

        self.mock_client = ControllerClient(base_url="http://127.0.0.1:8000")
        self.runner = WorkflowRunner(
            ui_driver=self.ui_driver,
            screen_capture=self.mock_capture,
            controller_client=self.mock_client,
            dry_run=False,
            action_delay=0.0,
        )

    def test_handle_validation_error_popup_detected(self):
        self.mock_client.detect_popup = MagicMock(
            return_value=PopupDetectionResult(
                detected=True,
                popup_type=PopupType.VALIDATION_ERROR,
                title="Validation error",
                message="Dialog validation failed. Please enter correct data.",
                ok_button_relative_x=0.5,
                ok_button_relative_y=0.6,
            )
        )

        res = self.runner.handle_validation_error_popup()
        assert res is True
        # 1920 * 0.5 = 960, 1080 * 0.6 = 648
        self.mock_backend.click.assert_called_once_with(
            x=960, y=648, button="left", clicks=1, interval=0.0
        )

    def test_handle_validation_error_popup_none_detected(self):
        self.mock_client.detect_popup = MagicMock(
            return_value=PopupDetectionResult(detected=False, popup_type=PopupType.NONE)
        )
        res = self.runner.handle_validation_error_popup()
        assert res is False
        self.mock_backend.click.assert_not_called()

    def test_recover_to_home_executes_failsafe_actions(self):
        self.runner.recover_to_home()
        # Should press Escape 3 times
        self.mock_backend.press_key.assert_called_once_with("esc", presses=3, interval=0.1)

    def test_recover_to_home_handles_exceptions_gracefully(self):
        self.mock_backend.press_key.side_effect = RuntimeError("Fatal UI error")
        # Should not raise exception
        self.runner.recover_to_home()


# ---------------------------------------------------------------------------
# Test Full End-to-End Workflow Execution (run_task)
# ---------------------------------------------------------------------------

class TestWorkflowRunnerFullExecution:
    """Tests for complete 14-step workflow run_task execution and error recovery."""

    def setup_method(self):
        self.mock_backend = MagicMock(spec=BackendAdapter)
        self.ui_driver = UIDriver(dry_run=True, action_delay=0.0, backend=self.mock_backend)

        self.mock_capture = MagicMock(spec=ScreenCapture)
        self.mock_capture.capture_as_base64.return_value = "data:image/png;base64,canvas_b64"
        self.mock_capture.get_screen_size.return_value = (1920, 1080)

        self.text_cleaner = TextCleaner()
        self.mock_client = ControllerClient(text_cleaner=self.text_cleaner)

        # Mock analyze_canvas with 3 blocks
        mock_blocks = [
            DetectedBlock(type=BlockType.MESSAGE, relative_x=0.45, relative_y=0.30, label="Message 1"),
            DetectedBlock(type=BlockType.COMMENT, relative_x=0.50, relative_y=0.50, label="Comment 1"),
            DetectedBlock(type=BlockType.QUESTION, relative_x=0.60, relative_y=0.70, label="Question 1"),
        ]
        self.mock_client.analyze_canvas = MagicMock(return_value=mock_blocks)

        self.runner = WorkflowRunner(
            ui_driver=self.ui_driver,
            screen_capture=self.mock_capture,
            controller_client=self.mock_client,
            dry_run=True,
            action_delay=0.0,
            text_supplier=lambda b: f"Lamborghini test entry for {b.type.value}",
        )

    def test_run_task_full_cycle_success(self):
        task_id = "GFF_042"
        gff_name = "A16_4LA_91____1_518_88_Check_battery"

        result = self.runner.run_task(task_id=task_id, gff_name=gff_name)

        assert result.task_id == task_id
        assert result.gff_name == gff_name
        assert result.status == "SUCCESS"
        assert result.blocks_detected == 3
        assert result.blocks_modified["message"] == 1
        assert result.blocks_modified["comment"] == 1
        assert result.blocks_modified["question"] == 1
        assert result.total_blocks_modified == 3
        assert result.duration_seconds >= 0.0

        # All 15 steps (Step 0 through Step 14) should be completed
        expected_steps = [
            WorkflowStep.STEP_0_HOME,
            WorkflowStep.STEP_1_OPEN_SEARCH,
            WorkflowStep.STEP_2_INPUT_FUNCTION_SEARCH,
            WorkflowStep.STEP_3_CLOSE_SEARCH_ENDED_POPUP,
            WorkflowStep.STEP_4_SELECT_FUNCTION_RESULT,
            WorkflowStep.STEP_5_SELECT_USAGE_LOCATION,
            WorkflowStep.STEP_6_OPEN_TEST_SEQUENCE,
            WorkflowStep.STEP_7_MINIMIZE_PANELS,
            WorkflowStep.STEP_8_EXPAND_CANVAS_AND_SCAN,
            WorkflowStep.STEP_9_EDIT_MESSAGE_BLOCK,
            WorkflowStep.STEP_10_EDIT_COMMENT_BLOCK,
            WorkflowStep.STEP_11_EDIT_QUESTION_BLOCK,
            WorkflowStep.STEP_12_CLOSE_TEST_MODULE,
            WorkflowStep.STEP_13_ENTER_VERSION_COMMENT,
            WorkflowStep.STEP_14_CLOSE_OBJECT_RETURN_HOME,
        ]
        for step in expected_steps:
            assert step in result.steps_completed

    def test_run_task_failure_captures_error_and_recovers(self):
        task_id = "GFF_999"
        gff_name = "Corrupted_Function_Test"

        # Simulate exception during search
        self.runner.step_2_input_function_search = MagicMock(
            side_effect=RuntimeError("Search input field not responsive.")
        )

        result = self.runner.run_task(task_id=task_id, gff_name=gff_name)

        assert result.status == "FAILED"
        assert "Search input field not responsive" in result.error_details
        assert result.error_screenshot_base64 is not None
        assert WorkflowStep.STEP_0_HOME in result.steps_completed
        assert WorkflowStep.STEP_1_OPEN_SEARCH in result.steps_completed

    def test_run_task_failure_when_screen_capture_fails(self):
        task_id = "GFF_ERR"
        gff_name = "Capture_Error_Function"

        self.runner.step_1_open_search = MagicMock(side_effect=RuntimeError("UI blocked"))
        self.mock_capture.capture_as_base64.side_effect = RuntimeError("Screen capture failure")

        result = self.runner.run_task(task_id=task_id, gff_name=gff_name)
        assert result.status == "FAILED"
        assert result.error_screenshot_base64 is None
        assert "UI blocked" in result.error_details


# ---------------------------------------------------------------------------
# Test Singleton Accessor
# ---------------------------------------------------------------------------

class TestWorkflowRunnerSingleton:
    """Tests for singleton factory."""

    def test_get_workflow_runner_singleton(self):
        r1 = get_workflow_runner()
        r2 = get_workflow_runner()
        assert r1 is r2
        assert isinstance(r1, WorkflowRunner)
