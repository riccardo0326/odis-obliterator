"""End-to-End 14-Step Workflow Runner for ODIS Obliterator Worker (TASK-008).

Implements sequential execution of the 14 steps defined in WORKFLOW.md:
1. Full text search (Steps 1-3)
2. Open function and tree navigation (Steps 4-6)
3. Panel minimization and canvas expansion (Steps 7-8)
4. Flowchart scanning and Message/Comment/Question editing (Steps 9-11)
5. Module close, version comment, final close and return to Home (Steps 12-14)
6. Modal dialog and validation error popup handling (Edge cases).
"""

from datetime import datetime, timezone
from enum import Enum
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from PIL import Image
from pydantic import BaseModel, Field
import pyperclip
import requests

from controller.config import Settings, get_settings
from controller.text_cleaner import (
    TextCleanRequest,
    TextCleanResponse,
    TextCleaner,
    clean_text,
)
from controller.vision_engine import (
    BlockType,
    CanvasBoundingBox,
    DetectedBlock,
    PopupDetectionResult,
    PopupType,
    VisionEngine,
)
from worker.screen_capture import (
    ScreenCapture,
    ScreenRegion,
    get_screen_capture,
    image_to_base64,
)
from worker.ui_driver import UIDriver, get_ui_driver

logger = logging.getLogger(__name__)


class WorkflowStep(str, Enum):
    """The 14 canonical steps (+ Step 0 Home) of the ODIS Obliterator workflow."""

    STEP_0_HOME = "STEP_0_HOME"
    STEP_1_OPEN_SEARCH = "STEP_1_OPEN_SEARCH"
    STEP_2_INPUT_FUNCTION_SEARCH = "STEP_2_INPUT_FUNCTION_SEARCH"
    STEP_3_CLOSE_SEARCH_ENDED_POPUP = "STEP_3_CLOSE_SEARCH_ENDED_POPUP"
    STEP_4_SELECT_FUNCTION_RESULT = "STEP_4_SELECT_FUNCTION_RESULT"
    STEP_5_SELECT_USAGE_LOCATION = "STEP_5_SELECT_USAGE_LOCATION"
    STEP_6_OPEN_TEST_SEQUENCE = "STEP_6_OPEN_TEST_SEQUENCE"
    STEP_7_MINIMIZE_PANELS = "STEP_7_MINIMIZE_PANELS"
    STEP_8_EXPAND_CANVAS_AND_SCAN = "STEP_8_EXPAND_CANVAS_AND_SCAN"
    STEP_9_EDIT_MESSAGE_BLOCK = "STEP_9_EDIT_MESSAGE_BLOCK"
    STEP_10_EDIT_COMMENT_BLOCK = "STEP_10_EDIT_COMMENT_BLOCK"
    STEP_11_EDIT_QUESTION_BLOCK = "STEP_11_EDIT_QUESTION_BLOCK"
    STEP_12_CLOSE_TEST_MODULE = "STEP_12_CLOSE_TEST_MODULE"
    STEP_13_ENTER_VERSION_COMMENT = "STEP_13_ENTER_VERSION_COMMENT"
    STEP_14_CLOSE_OBJECT_RETURN_HOME = "STEP_14_CLOSE_OBJECT_RETURN_HOME"


class WorkflowCoordinates(BaseModel):
    """Configurable screen pixel coordinates and bounding boxes for ODIS UI elements.

    Default coordinates are calibrated for standard 1920x1080 resolution.
    """

    # Step 1: Toolbar search icon (11th button in toolbar with yellow flashlight)
    toolbar_search_button: Tuple[int, int] = Field(default=(340, 60), description="Toolbar search button (X, Y).")
    search_dialog_full_text_tab: Tuple[int, int] = Field(
        default=(620, 240), description="Full Text Search tab in Search dialog."
    )

    # Step 2: Search dialog text input and confirmation
    search_dialog_input_field: Tuple[int, int] = Field(
        default=(650, 290), description="Search text input field."
    )
    search_dialog_ok_button: Tuple[int, int] = Field(
        default=(870, 520), description="OK button on Search modal dialog."
    )

    # Step 3: 'Search ended' popup notification OK button
    search_ended_ok_button: Tuple[int, int] = Field(
        default=(960, 550), description="OK button on 'Search ended' popup."
    )

    # Step 4: Search Results table first row
    search_results_first_row: Tuple[int, int] = Field(
        default=(700, 650), description="First matching row in Search Results table."
    )

    # Step 5: 'Usage locations' dialog first hierarchy item and OK button
    usage_locations_first_item: Tuple[int, int] = Field(
        default=(750, 420), description="First usage location tree item."
    )
    usage_locations_ok_button: Tuple[int, int] = Field(
        default=(980, 680), description="OK button on Usage locations dialog."
    )

    # Step 6: Context menu on object tab grey background
    tab_object_background: Tuple[int, int] = Field(
        default=(600, 350), description="Grey background area in function object tab."
    )
    context_menu_test_sequence: Tuple[int, int] = Field(
        default=(650, 375), description="'Test sequence' item in right-click context menu."
    )

    # Step 7: Panel minimize buttons ('_')
    palette_minimize_button: Tuple[int, int] = Field(
        default=(1890, 110), description="Minimize button for Palette panel."
    )
    search_results_minimize_button: Tuple[int, int] = Field(
        default=(1890, 750), description="Minimize button for lower-center search/XML panel."
    )
    recent_objects_minimize_button: Tuple[int, int] = Field(
        default=(1890, 920), description="Minimize button for lower Recently-Used panel."
    )

    # Step 8: Central Test Steps column and Canvas Bounding Box
    test_step_central_column: Tuple[int, int] = Field(
        default=(400, 300), description="White background of central Test Step column."
    )
    canvas_bbox: CanvasBoundingBox = Field(
        default_factory=lambda: CanvasBoundingBox(x=510, y=120, width=1400, height=900),
        description="Bounding box of the flowchart canvas area.",
    )

    # Steps 9-11: Block editing dialog buttons and text area
    block_dialog_text_area: Tuple[int, int] = Field(
        default=(700, 450), description="Text editing area inside block dialogs."
    )
    block_dialog_ok_button: Tuple[int, int] = Field(
        default=(900, 750), description="OK button on Message/Comment/Question dialogs."
    )
    block_dialog_cancel_button: Tuple[int, int] = Field(
        default=(1000, 750), description="Cancel button on block dialogs."
    )

    # Step 12: Close Test Module tab
    test_module_close_x: Tuple[int, int] = Field(
        default=(520, 90), description="Red 'X' close button on Test module tab."
    )
    save_dialog_save_button: Tuple[int, int] = Field(
        default=(900, 560), description="Save/Yes button on save confirmation dialog."
    )

    # Step 13: Version comment box (yellow box on object tab)
    version_comment_box: Tuple[int, int] = Field(
        default=(600, 320), description="Yellow 'Version comment:' input box."
    )

    # Step 14: Close function object tab (return to Home)
    object_tab_close_x: Tuple[int, int] = Field(
        default=(380, 90), description="Red 'X' close button on main object tab."
    )

    # Edge Case: Validation Error popup OK button
    validation_error_ok_button: Tuple[int, int] = Field(
        default=(960, 560), description="OK button on 'Validation error' modal popup."
    )


class WorkflowExecutionResult(BaseModel):
    """Complete execution metrics and result for a single GFF task."""

    task_id: str = Field(..., description="Unique task identifier.")
    gff_name: str = Field(..., description="Diagnostic function name.")
    status: str = Field(default="SUCCESS", description="Terminal status ('SUCCESS', 'FAILED', 'SKIPPED', 'NOT_FOUND').")
    steps_completed: List[WorkflowStep] = Field(default_factory=list, description="Ordered list of completed steps.")
    current_step: Optional[WorkflowStep] = Field(default=None, description="Step where execution finished or failed.")
    blocks_detected: int = Field(default=0, description="Total target blocks detected on canvas.")
    blocks_modified: Dict[str, int] = Field(
        default_factory=lambda: {"message": 0, "comment": 0, "question": 0},
        description="Breakdown of modified blocks.",
    )
    duration_seconds: float = Field(default=0.0, description="Total execution duration in seconds.")
    error_details: Optional[str] = Field(default=None, description="Diagnostic error details if failed.")
    error_screenshot_base64: Optional[str] = Field(default=None, description="Base64 screenshot captured upon error.")

    @property
    def total_blocks_modified(self) -> int:
        """Total sanitized blocks count."""
        return sum(self.blocks_modified.values())


class ControllerClient:
    """HTTP and in-process client for communicating with Controller API services."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
        vision_engine: Optional[VisionEngine] = None,
        text_cleaner: Optional[TextCleaner] = None,
    ):
        """Initialize ControllerClient.

        Args:
            base_url: Base URL of the Controller API (e.g. 'http://127.0.0.1:8000').
            timeout: Request timeout in seconds.
            vision_engine: Optional in-process VisionEngine for direct execution / testing.
            text_cleaner: Optional in-process TextCleaner for direct execution / testing.
        """
        self.base_url = (base_url or get_settings().controller_api_url).rstrip("/")
        self.timeout = timeout
        self.vision_engine = vision_engine
        self.text_cleaner = text_cleaner
        self.session = requests.Session()

    def check_health(self) -> Dict[str, Any]:
        """Check Controller health and AI gateway connectivity."""
        url = f"{self.base_url}/api/v1/health"
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def start_session(
        self,
        session_id: Optional[str] = None,
        gff_list: Optional[List[str]] = None,
        input_file: Optional[str] = None,
        resume: bool = True,
        force_new: bool = False,
    ) -> Dict[str, Any]:
        """Start a new batch session or resume existing session."""
        url = f"{self.base_url}/api/v1/session/start"
        payload = {
            "session_id": session_id,
            "gff_list": gff_list,
            "input_file": input_file,
            "resume": resume,
            "force_new": force_new,
        }
        resp = self.session.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def get_next_task(self) -> Optional[Dict[str, Any]]:
        """Fetch next pending task from Controller. Returns None if queue is empty (204)."""
        url = f"{self.base_url}/api/v1/tasks/next"
        resp = self.session.get(url, timeout=self.timeout)
        if resp.status_code == 204:
            return None
        resp.raise_for_status()
        return resp.json()

    def get_session_status(self) -> Dict[str, Any]:
        """Get overall session execution summary and progress metrics."""
        url = f"{self.base_url}/api/v1/session/status"
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def clean_text(
        self,
        raw_text: str,
        block_type: Optional[str] = None,
        target_keyword: Optional[str] = None,
    ) -> TextCleanResponse:
        """Sanitize text by removing target keyword.

        If in-process text_cleaner is provided, uses it directly; otherwise sends REST request.
        """
        if self.text_cleaner is not None:
            res = self.text_cleaner.clean(
                raw_text=raw_text,
                block_type=block_type,
                target_keyword=target_keyword,
            )
            return res.to_response()

        url = f"{self.base_url}/api/v1/text/clean"
        payload = {
            "raw_text": raw_text,
            "block_type": block_type,
            "target_keyword": target_keyword,
        }
        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return TextCleanResponse.model_validate(resp.json())
        except Exception as exc:
            logger.warning(f"Controller API clean_text call failed ({exc}), falling back to local clean_text.")
            res = clean_text(raw_text, target_keyword=target_keyword, block_type=block_type)
            return res.to_response()

    def analyze_canvas(
        self,
        image_base64: str,
        canvas_bbox: Optional[CanvasBoundingBox] = None,
        task_id: Optional[str] = None,
    ) -> List[DetectedBlock]:
        """Analyze canvas screenshot to detect target blocks (MESSAGE, QUESTION, COMMENT)."""
        if self.vision_engine is not None:
            resp = self.vision_engine.analyze_canvas(
                image=image_base64,
                canvas_bbox=canvas_bbox,
                task_id=task_id,
            )
            return resp.blocks

        url = f"{self.base_url}/api/v1/vision/analyze-canvas"
        payload = {
            "task_id": task_id,
            "image_base64": image_base64,
            "canvas_bbox": canvas_bbox.model_dump() if canvas_bbox else None,
        }
        resp = self.session.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        raw_blocks = data.get("blocks", [])
        return [DetectedBlock.model_validate(b) for b in raw_blocks]

    def detect_popup(self, image_base64: str) -> PopupDetectionResult:
        """Detect and classify visible modal dialogs / popups."""
        if self.vision_engine is not None:
            return self.vision_engine.detect_popup(image=image_base64)

        url = f"{self.base_url}/api/v1/vision/detect-popup"
        payload = {"image_base64": image_base64}
        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return PopupDetectionResult.model_validate(resp.json())
        except Exception as exc:
            logger.debug(f"Popup detection API returned: {exc}")
            return PopupDetectionResult(detected=False, popup_type=PopupType.NONE)

    def complete_task(
        self,
        task_id: str,
        status: str,
        blocks_modified: Optional[Dict[str, int]] = None,
        duration_seconds: Optional[float] = None,
        error_details: Optional[str] = None,
        error_screenshot_base64: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Notify Controller of task completion."""
        url = f"{self.base_url}/api/v1/tasks/complete"
        payload = {
            "task_id": task_id,
            "status": status,
            "blocks_modified": blocks_modified,
            "duration_seconds": duration_seconds,
            "error_details": error_details,
            "error_screenshot_base64": error_screenshot_base64,
        }
        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning(f"Failed to send task completion notification to Controller: {exc}")
            return {"status": "unreachable", "error": str(exc)}


class WorkflowRunner:
    """Executes the complete 14-step ODIS Creator sanitization workflow for diagnostic objects."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        ui_driver: Optional[UIDriver] = None,
        screen_capture: Optional[ScreenCapture] = None,
        controller_client: Optional[ControllerClient] = None,
        coordinates: Optional[WorkflowCoordinates] = None,
        dry_run: Optional[bool] = None,
        action_delay: Optional[float] = None,
        text_supplier: Optional[Callable[[DetectedBlock], str]] = None,
    ):
        """Initialize WorkflowRunner.

        Args:
            settings: Application Settings instance.
            ui_driver: UIDriver instance for mouse/keyboard automation.
            screen_capture: ScreenCapture instance.
            controller_client: ControllerClient for AI/text services.
            coordinates: Configurable UI layout coordinates.
            dry_run: Override dry-run mode (if None, reads from settings.dry_run).
            action_delay: Delay after actions (if None, reads from settings.action_delay).
            text_supplier: Optional callback supplying simulated text for detected blocks in test/dry-run.
        """
        self.settings = settings or get_settings()
        self.dry_run = dry_run if dry_run is not None else self.settings.dry_run
        self.action_delay = action_delay if action_delay is not None else self.settings.action_delay

        self.ui = ui_driver or get_ui_driver()
        if dry_run is not None:
            self.ui.dry_run = self.dry_run
        self.capture = screen_capture or get_screen_capture()
        self.client = controller_client or ControllerClient(
            base_url=self.settings.controller_api_url,
            timeout=self.settings.timeout,
        )
        self.coords = coordinates or WorkflowCoordinates()
        self.text_supplier = text_supplier

        self.target_keyword = self.settings.target_keyword
        self.version_comment = self.settings.version_comment

        # Execution tracking
        self.completed_steps: List[WorkflowStep] = []
        self.current_step: Optional[WorkflowStep] = None
        self.modified_blocks_count: Dict[str, int] = {"message": 0, "comment": 0, "question": 0}

    def _mark_step(self, step: WorkflowStep) -> None:
        """Mark a workflow step as completed."""
        self.current_step = step
        self.completed_steps.append(step)
        logger.info(f"Completed Workflow Step: {step.value}")

    # ---------------------------------------------------------------------------
    # Step 0: Initial Screen (Home / Editing View)
    # ---------------------------------------------------------------------------

    def step_0_ensure_home(self) -> bool:
        """Step 0: Ensure ODIS Creator window is focused and ready in Editing View."""
        logger.debug("Step 0: Focusing ODIS Creator window...")
        self.ui.focus_window("ODIS Creator", delay=self.action_delay)
        self._mark_step(WorkflowStep.STEP_0_HOME)
        return True

    # ---------------------------------------------------------------------------
    # Step 1: Open Search & Select Full Text Search
    # ---------------------------------------------------------------------------

    def step_1_open_search(self) -> bool:
        """Step 1: Click 11th toolbar button (search) and select 'Full Text Search' tab."""
        logger.debug("Step 1: Opening Search window and selecting Full Text Search...")
        # Click on toolbar search icon
        sx, sy = self.coords.toolbar_search_button
        self.ui.click(x=sx, y=sy, delay=self.action_delay)

        # Click on 'Full Text Search' tab in Search dialog
        tab_x, tab_y = self.coords.search_dialog_full_text_tab
        self.ui.click(x=tab_x, y=tab_y, delay=self.action_delay)

        self._mark_step(WorkflowStep.STEP_1_OPEN_SEARCH)
        return True

    # ---------------------------------------------------------------------------
    # Step 2: Input Function Name & Start Search
    # ---------------------------------------------------------------------------

    def step_2_input_function_search(self, gff_name: str) -> bool:
        """Step 2: Enter full function name in 'Search text:' and click OK."""
        logger.debug(f"Step 2: Searching for function '{gff_name}'...")
        inp_x, inp_y = self.coords.search_dialog_input_field
        self.ui.click(x=inp_x, y=inp_y, delay=0.1)

        # Clear existing text and paste/type function name
        self.ui.clear_and_type(gff_name, use_clipboard=True, delay=0.1)

        # Click OK to submit search
        ok_x, ok_y = self.coords.search_dialog_ok_button
        self.ui.click(x=ok_x, y=ok_y, delay=self.action_delay)

        self._mark_step(WorkflowStep.STEP_2_INPUT_FUNCTION_SEARCH)
        return True

    # ---------------------------------------------------------------------------
    # Step 3: Close 'Search ended' Notification Popup
    # ---------------------------------------------------------------------------

    def step_3_close_search_ended_popup(self) -> bool:
        """Step 3: Await and close the 'Search ended' modal dialog."""
        logger.debug("Step 3: Closing 'Search ended' popup...")
        # In real execution, give brief pause for search to conclude
        if not self.dry_run:
            self.ui.wait(0.2)

        # Click OK on popup
        ok_x, ok_y = self.coords.search_ended_ok_button
        self.ui.click(x=ok_x, y=ok_y, delay=self.action_delay)

        self._mark_step(WorkflowStep.STEP_3_CLOSE_SEARCH_ENDED_POPUP)
        return True

    # ---------------------------------------------------------------------------
    # Step 4: Select & Open Function from Search Results
    # ---------------------------------------------------------------------------

    def step_4_select_function_result(self, gff_name: str) -> bool:
        """Step 4: Double click the matching function row in Search Results."""
        logger.debug(f"Step 4: Opening function '{gff_name}' from Search Results...")
        row_x, row_y = self.coords.search_results_first_row
        self.ui.double_click(x=row_x, y=row_y, delay=self.action_delay)

        self._mark_step(WorkflowStep.STEP_4_SELECT_FUNCTION_RESULT)
        return True

    # ---------------------------------------------------------------------------
    # Step 5: Select Usage Location & Wait for Tree Expansion
    # ---------------------------------------------------------------------------

    def step_5_select_usage_location(self) -> bool:
        """Step 5: Select first usage location, click OK, and await tree loading."""
        logger.debug("Step 5: Selecting Usage location and loading tree...")
        item_x, item_y = self.coords.usage_locations_first_item
        self.ui.click(x=item_x, y=item_y, delay=0.1)

        ok_x, ok_y = self.coords.usage_locations_ok_button
        self.ui.click(x=ok_x, y=ok_y, delay=self.action_delay)

        # Wait for Knowledge base navigator to expand
        if not self.dry_run:
            self.ui.wait(0.2)

        self._mark_step(WorkflowStep.STEP_5_SELECT_USAGE_LOCATION)
        return True

    # ---------------------------------------------------------------------------
    # Step 6: Open Test Sequence via Context Menu
    # ---------------------------------------------------------------------------

    def step_6_open_test_sequence(self) -> bool:
        """Step 6: Right click object tab background and click 'Test sequence'."""
        logger.debug("Step 6: Opening Test sequence from context menu...")
        bg_x, bg_y = self.coords.tab_object_background
        self.ui.right_click(x=bg_x, y=bg_y, delay=0.2)

        seq_x, seq_y = self.coords.context_menu_test_sequence
        self.ui.click(x=seq_x, y=seq_y, delay=self.action_delay)

        self._mark_step(WorkflowStep.STEP_6_OPEN_TEST_SEQUENCE)
        return True

    # ---------------------------------------------------------------------------
    # Step 7: Minimize Unnecessary Panels
    # ---------------------------------------------------------------------------

    def step_7_minimize_panels(self) -> bool:
        """Step 7: Minimize Palette, Search Results/XML, and Recently-Used Objects panels."""
        logger.debug("Step 7: Minimizing side/bottom panels to expand canvas...")
        # 1. Minimize Palette (top right)
        px, py = self.coords.palette_minimize_button
        self.ui.click(x=px, y=py, delay=0.1)

        # 2. Minimize Search Results / XML panel (lower middle)
        sx, sy = self.coords.search_results_minimize_button
        self.ui.click(x=sx, y=sy, delay=0.1)

        # 3. Minimize Recently-Used Objects (bottom)
        rx, ry = self.coords.recent_objects_minimize_button
        self.ui.click(x=rx, y=ry, delay=self.action_delay)

        self._mark_step(WorkflowStep.STEP_7_MINIMIZE_PANELS)
        return True

    # ---------------------------------------------------------------------------
    # Step 8: Expand Canvas & Scan Flowchart for Target Blocks
    # ---------------------------------------------------------------------------

    def step_8_expand_canvas_and_scan(self, task_id: str) -> List[DetectedBlock]:
        """Step 8: Click central Test Steps column, capture canvas, and detect target blocks."""
        logger.debug("Step 8: Expanding flowchart view and analyzing canvas...")
        # Click white background of central column
        cx, cy = self.coords.test_step_central_column
        self.ui.click(x=cx, y=cy, delay=self.action_delay)

        # Capture canvas screenshot
        canvas_b64 = self.capture.capture_as_base64(region=self.coords.canvas_bbox)

        # Send to Vision Engine / Controller API
        detected_blocks = self.client.analyze_canvas(
            image_base64=canvas_b64,
            canvas_bbox=self.coords.canvas_bbox,
            task_id=task_id,
        )

        logger.info(f"Detected {len(detected_blocks)} target blocks on canvas for task {task_id}.")
        self._mark_step(WorkflowStep.STEP_8_EXPAND_CANVAS_AND_SCAN)
        return detected_blocks

    # ---------------------------------------------------------------------------
    # Steps 9, 10, 11: Edit Target Blocks (Message, Comment, Question)
    # ---------------------------------------------------------------------------

    def edit_single_block(self, block: DetectedBlock) -> bool:
        """Edit a single detected block (Message, Comment, or Question).

        1. Double click block on canvas using relative coordinates.
        2. Obtain current text (via clipboard/supplier).
        3. Clean text using Controller text sanitization service.
        4. If text was modified, paste/type replacement and confirm with OK.
        5. Check and handle any 'Validation error' modal popup.
        """
        block_name = block.type.value
        logger.debug(f"Editing block {block_name} at ({block.relative_x}, {block.relative_y})...")

        # 1. Double click on block coordinates
        sx, sy = self.coords.canvas_bbox.to_screen_coords(block.relative_x, block.relative_y)
        self.ui.double_click(x=sx, y=sy, delay=self.action_delay)

        # 2. Extract current raw text
        raw_text = ""
        if self.text_supplier is not None:
            raw_text = self.text_supplier(block)
        elif self.dry_run:
            raw_text = block.label or f"Sample {block_name} with Lamborghini entry."
        else:
            # Live UI extraction: Focus text area, select all (Ctrl+A), copy (Ctrl+C)
            tx, ty = self.coords.block_dialog_text_area
            self.ui.click(x=tx, y=ty, delay=0.1)
            self.ui.hotkey("ctrl", "a", delay=0.05)
            self.ui.hotkey("ctrl", "c", delay=0.05)
            try:
                raw_text = pyperclip.paste()
            except Exception:
                raw_text = block.label or ""

        # 3. Clean text using Controller / TextCleaner
        clean_res = self.client.clean_text(
            raw_text=raw_text,
            block_type=block.type.value,
            target_keyword=self.target_keyword,
        )

        was_modified = clean_res.modified

        # 4. If modified, write replacement and click OK
        if was_modified:
            logger.info(
                f"Modifying {block_name} block text. Removed {clean_res.occurrences_removed} occurrences of '{self.target_keyword}'."
            )
            tx, ty = self.coords.block_dialog_text_area
            self.ui.click(x=tx, y=ty, delay=0.05)
            self.ui.clear_and_type(clean_res.cleaned_text, use_clipboard=True, delay=0.1)

            # Click OK to save block
            ok_x, ok_y = self.coords.block_dialog_ok_button
            self.ui.click(x=ok_x, y=ok_y, delay=self.action_delay)

            # 5. Handle Validation error edge case
            self.handle_validation_error_popup()

            # Increment count
            cat_key = block.type.value.lower()
            if cat_key in self.modified_blocks_count:
                self.modified_blocks_count[cat_key] += 1
        else:
            # Not modified: close dialog with Cancel
            cancel_x, cancel_y = self.coords.block_dialog_cancel_button
            self.ui.click(x=cancel_x, y=cancel_y, delay=self.action_delay)

        return was_modified

    def step_9_to_11_process_blocks(self, blocks: List[DetectedBlock]) -> Dict[str, int]:
        """Execute Steps 9, 10, 11 sequentially over all detected target blocks."""
        logger.debug(f"Processing {len(blocks)} detected blocks...")

        for idx, block in enumerate(blocks, start=1):
            logger.debug(f"Processing block {idx}/{len(blocks)} [{block.type.value}]")
            self.edit_single_block(block)

            # Track corresponding step
            if block.type == BlockType.MESSAGE and WorkflowStep.STEP_9_EDIT_MESSAGE_BLOCK not in self.completed_steps:
                self._mark_step(WorkflowStep.STEP_9_EDIT_MESSAGE_BLOCK)
            elif block.type == BlockType.COMMENT and WorkflowStep.STEP_10_EDIT_COMMENT_BLOCK not in self.completed_steps:
                self._mark_step(WorkflowStep.STEP_10_EDIT_COMMENT_BLOCK)
            elif block.type == BlockType.QUESTION and WorkflowStep.STEP_11_EDIT_QUESTION_BLOCK not in self.completed_steps:
                self._mark_step(WorkflowStep.STEP_11_EDIT_QUESTION_BLOCK)

        # Mark all three steps as visited in workflow history if not already
        for step in (
            WorkflowStep.STEP_9_EDIT_MESSAGE_BLOCK,
            WorkflowStep.STEP_10_EDIT_COMMENT_BLOCK,
            WorkflowStep.STEP_11_EDIT_QUESTION_BLOCK,
        ):
            if step not in self.completed_steps:
                self._mark_step(step)

        return self.modified_blocks_count

    # ---------------------------------------------------------------------------
    # Step 12: Close Test Module & Save Modifications
    # ---------------------------------------------------------------------------

    def step_12_close_test_module(self) -> bool:
        """Step 12: Click 'X' to close Test Module tab and confirm Save."""
        logger.debug("Step 12: Closing Test Module tab and saving changes...")
        close_x, close_y = self.coords.test_module_close_x
        self.ui.click(x=close_x, y=close_y, delay=self.action_delay)

        # Click Save / Yes on save prompt
        save_x, save_y = self.coords.save_dialog_save_button
        self.ui.click(x=save_x, y=save_y, delay=self.action_delay)

        self._mark_step(WorkflowStep.STEP_12_CLOSE_TEST_MODULE)
        return True

    # ---------------------------------------------------------------------------
    # Step 13: Enter Version Comment ("Removed Lamborghini labels")
    # ---------------------------------------------------------------------------

    def step_13_enter_version_comment(self) -> bool:
        """Step 13: Click yellow 'Version comment:' field and type standard comment."""
        logger.debug(f"Step 13: Entering version comment '{self.version_comment}'...")
        vx, vy = self.coords.version_comment_box
        self.ui.click(x=vx, y=vy, delay=0.1)

        # Type standard version comment string
        self.ui.clear_and_type(self.version_comment, use_clipboard=True, delay=self.action_delay)

        self._mark_step(WorkflowStep.STEP_13_ENTER_VERSION_COMMENT)
        return True

    # ---------------------------------------------------------------------------
    # Step 14: Close Object Tab & Return to Home
    # ---------------------------------------------------------------------------

    def step_14_close_object_return_home(self) -> bool:
        """Step 14: Click 'X' on main function tab, confirm Save, and return to Home."""
        logger.debug("Step 14: Closing main object tab and returning to Home view...")
        close_x, close_y = self.coords.object_tab_close_x
        self.ui.click(x=close_x, y=close_y, delay=self.action_delay)

        # Click Save on confirmation dialog
        save_x, save_y = self.coords.save_dialog_save_button
        self.ui.click(x=save_x, y=save_y, delay=self.action_delay)

        self._mark_step(WorkflowStep.STEP_14_CLOSE_OBJECT_RETURN_HOME)
        return True

    # ---------------------------------------------------------------------------
    # Edge Case Handler: Modal Validation Error Popup
    # ---------------------------------------------------------------------------

    def handle_validation_error_popup(self) -> bool:
        """Detect and dismiss modal 'Validation error' popups if displayed."""
        if self.dry_run:
            return False

        try:
            # Capture full screen to check for popup
            screen_b64 = self.capture.capture_as_base64()
            popup_res = self.client.detect_popup(screen_b64)

            if popup_res.detected and popup_res.popup_type == PopupType.VALIDATION_ERROR:
                logger.warning("Detected 'Validation error' modal popup. Dismissing with OK...")
                if popup_res.ok_button_relative_x is not None and popup_res.ok_button_relative_y is not None:
                    scr_w, scr_h = self.capture.get_screen_size()
                    btn_x = int(round(popup_res.ok_button_relative_x * scr_w))
                    btn_y = int(round(popup_res.ok_button_relative_y * scr_h))
                    self.ui.click(x=btn_x, y=btn_y, delay=self.action_delay)
                else:
                    vx, vy = self.coords.validation_error_ok_button
                    self.ui.click(x=vx, y=vy, delay=self.action_delay)
                return True
        except Exception as exc:
            logger.debug(f"Validation error popup check encountered: {exc}")

        return False

    # ---------------------------------------------------------------------------
    # Safety Recovery
    # ---------------------------------------------------------------------------

    def recover_to_home(self) -> None:
        """Attempt safe recovery by closing dialogs and returning to Home Editing view."""
        logger.warning("Initiating emergency UI recovery to Home state...")
        try:
            # Press Escape key multiple times to close potential hanging modals
            self.ui.press_key("esc", presses=3, interval=0.1, delay=0.2)
            # Click object tab close button
            cx, cy = self.coords.object_tab_close_x
            self.ui.click(x=cx, y=cy, delay=0.2)
            # Re-focus main ODIS window
            self.ui.focus_window("ODIS Creator", delay=0.2)
        except Exception as exc:
            logger.error(f"Error during recover_to_home: {exc}")

    # ---------------------------------------------------------------------------
    # Complete Workflow Runner Execution Loop
    # ---------------------------------------------------------------------------

    def run_task(self, task_id: str, gff_name: str) -> WorkflowExecutionResult:
        """Run the full 14-step workflow for a single GFF function.

        Args:
            task_id: Unique task identifier (e.g. 'GFF_001').
            gff_name: Diagnostic function object name.

        Returns:
            WorkflowExecutionResult instance.
        """
        start_time = time.time()
        self.completed_steps.clear()
        self.current_step = None
        self.modified_blocks_count = {"message": 0, "comment": 0, "question": 0}

        logger.info(f"Starting 14-step workflow for task {task_id}: '{gff_name}'")

        try:
            # Step 0: Ensure Home / Focus
            self.step_0_ensure_home()

            # Step 1: Open Search dialog
            self.step_1_open_search()

            # Step 2: Input function name & start search
            self.step_2_input_function_search(gff_name)

            # Step 3: Close 'Search ended' popup
            self.step_3_close_search_ended_popup()

            # Step 4: Open function from search results
            self.step_4_select_function_result(gff_name)

            # Step 5: Select usage location & load tree
            self.step_5_select_usage_location()

            # Step 6: Open test sequence via context menu
            self.step_6_open_test_sequence()

            # Step 7: Minimize panels
            self.step_7_minimize_panels()

            # Step 8: Expand canvas & scan flowchart for blocks
            detected_blocks = self.step_8_expand_canvas_and_scan(task_id)

            # Steps 9-11: Process detected blocks
            self.step_9_to_11_process_blocks(detected_blocks)

            # Step 12: Close Test Module & Save
            self.step_12_close_test_module()

            # Step 13: Enter Version Comment
            self.step_13_enter_version_comment()

            # Step 14: Close Object & Final Save (Return to Home)
            self.step_14_close_object_return_home()

            duration = round(time.time() - start_time, 2)
            result = WorkflowExecutionResult(
                task_id=task_id,
                gff_name=gff_name,
                status="SUCCESS",
                steps_completed=list(self.completed_steps),
                current_step=self.current_step,
                blocks_detected=len(detected_blocks),
                blocks_modified=dict(self.modified_blocks_count),
                duration_seconds=duration,
            )

            logger.info(
                f"Task {task_id} ({gff_name}) completed successfully in {duration}s. "
                f"Blocks modified: {self.modified_blocks_count}"
            )
            return result

        except Exception as exc:
            duration = round(time.time() - start_time, 2)
            logger.error(
                f"Workflow execution failed for task {task_id} ({gff_name}) at step {self.current_step}: {exc}",
                exc_info=True,
            )

            # Capture diagnostic error screenshot
            error_b64: Optional[str] = None
            try:
                error_b64 = self.capture.capture_as_base64()
            except Exception as cap_err:
                logger.debug(f"Could not capture error screenshot: {cap_err}")

            # Attempt UI recovery
            self.recover_to_home()

            result = WorkflowExecutionResult(
                task_id=task_id,
                gff_name=gff_name,
                status="FAILED",
                steps_completed=list(self.completed_steps),
                current_step=self.current_step,
                blocks_detected=0,
                blocks_modified=dict(self.modified_blocks_count),
                duration_seconds=duration,
                error_details=str(exc),
                error_screenshot_base64=error_b64,
            )
            return result


# Singleton instance
_default_workflow_runner: Optional[WorkflowRunner] = None


def get_workflow_runner(
    settings: Optional[Settings] = None,
    ui_driver: Optional[UIDriver] = None,
    screen_capture: Optional[ScreenCapture] = None,
    controller_client: Optional[ControllerClient] = None,
    coordinates: Optional[WorkflowCoordinates] = None,
) -> WorkflowRunner:
    """Return singleton WorkflowRunner instance."""
    global _default_workflow_runner
    if _default_workflow_runner is None:
        _default_workflow_runner = WorkflowRunner(
            settings=settings,
            ui_driver=ui_driver,
            screen_capture=screen_capture,
            controller_client=controller_client,
            coordinates=coordinates,
        )
    return _default_workflow_runner
