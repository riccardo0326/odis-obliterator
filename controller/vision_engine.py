"""Vision Engine and canvas coordinate mapping for ODIS Obliterator (TASK-004).

Analyzes ODIS Creator flowchart canvas screenshots via Kelpie AI Gateway (gemini-3.7-flash)
to detect editable target blocks (MESSAGE, QUESTION, COMMENT) and map normalized relative
coordinates to absolute screen coordinates.
"""

from enum import Enum
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple, Union
from PIL import Image
from pydantic import BaseModel, Field, field_validator

from controller.config import Settings, get_settings
from controller.kelpie_client import (
    KelpieClient,
    KelpieError,
    KelpieRequestError,
    KelpieResponseError,
    normalize_image_to_base64,
    strip_markdown_codeblocks,
)

logger = logging.getLogger(__name__)


class BlockType(str, Enum):
    """Target block types in ODIS Creator flowchart editor."""

    MESSAGE = "MESSAGE"
    QUESTION = "QUESTION"
    COMMENT = "COMMENT"


# Mapping aliases to canonical BlockType
_BLOCK_TYPE_ALIASES: Dict[str, BlockType] = {
    "message": BlockType.MESSAGE,
    "msg": BlockType.MESSAGE,
    "question": BlockType.QUESTION,
    "quest": BlockType.QUESTION,
    "comment": BlockType.COMMENT,
    "commentary": BlockType.COMMENT,
    "comment_block": BlockType.COMMENT,
}


def normalize_block_type(value: Any) -> Optional[BlockType]:
    """Normalize block type string or enum to BlockType, or None if non-target.

    Non-target blocks (e.g. IF, SUBROUTINE, EXPRESSION, READ_FILE) will return None.

    Args:
        value: Input block type (string or BlockType).

    Returns:
        Canonical BlockType enum or None if non-target.
    """
    if isinstance(value, BlockType):
        return value

    if not isinstance(value, str):
        return None

    cleaned = value.strip().upper()
    if cleaned in BlockType.__members__:
        return BlockType[cleaned]

    # Check lowercased aliases
    lower_val = value.strip().lower()
    return _BLOCK_TYPE_ALIASES.get(lower_val, None)


class CanvasBoundingBox(BaseModel):
    """Screen bounding box defining canvas area origin and dimensions."""

    x: int = Field(default=0, ge=0, description="Screen X coordinate of canvas top-left corner.")
    y: int = Field(default=0, ge=0, description="Screen Y coordinate of canvas top-left corner.")
    width: int = Field(..., gt=0, description="Width of the canvas area in screen pixels.")
    height: int = Field(..., gt=0, description="Height of the canvas area in screen pixels.")

    def to_screen_coords(self, relative_x: float, relative_y: float) -> Tuple[int, int]:
        """Convert normalized relative coordinates [0.0, 1.0] to absolute screen coordinates.

        Formula:
            X_screen = X_origin + (X_rel * Width)
            Y_screen = Y_origin + (Y_rel * Height)

        Args:
            relative_x: Normalized horizontal coordinate [0.0, 1.0].
            relative_y: Normalized vertical coordinate [0.0, 1.0].

        Returns:
            Tuple of (screen_x, screen_y) integers clamped to canvas bounds.
        """
        clamped_rel_x = max(0.0, min(1.0, float(relative_x)))
        clamped_rel_y = max(0.0, min(1.0, float(relative_y)))

        screen_x = int(round(self.x + (clamped_rel_x * self.width)))
        screen_y = int(round(self.y + (clamped_rel_y * self.height)))

        # Clamp within bounding box
        screen_x = max(self.x, min(self.x + self.width, screen_x))
        screen_y = max(self.y, min(self.y + self.height, screen_y))
        return screen_x, screen_y

    def to_relative_coords(self, screen_x: int, screen_y: int) -> Tuple[float, float]:
        """Convert absolute screen coordinates to normalized relative coordinates [0.0, 1.0].

        Args:
            screen_x: Absolute screen X coordinate.
            screen_y: Absolute screen Y coordinate.

        Returns:
            Tuple of (relative_x, relative_y) floats in range [0.0, 1.0].
        """
        rel_x = (float(screen_x) - self.x) / float(self.width)
        rel_y = (float(screen_y) - self.y) / float(self.height)

        clamped_rel_x = max(0.0, min(1.0, rel_x))
        clamped_rel_y = max(0.0, min(1.0, rel_y))
        return round(clamped_rel_x, 4), round(clamped_rel_y, 4)


class DetectedBlock(BaseModel):
    """Pydantic model representing an identified target block on the canvas."""

    type: BlockType = Field(..., description="Canonical block type (MESSAGE, QUESTION, COMMENT).")
    relative_x: float = Field(..., ge=0.0, le=1.0, description="Normalized horizontal center [0.0, 1.0].")
    relative_y: float = Field(..., ge=0.0, le=1.0, description="Normalized vertical center [0.0, 1.0].")
    label: Optional[str] = Field(default=None, description="Visible text label or identifier.")
    screen_x: Optional[int] = Field(default=None, description="Absolute screen X coordinate if bbox provided.")
    screen_y: Optional[int] = Field(default=None, description="Absolute screen Y coordinate if bbox provided.")
    confidence: Optional[float] = Field(default=1.0, ge=0.0, le=1.0, description="Detection confidence score.")

    @field_validator("relative_x", "relative_y", mode="before")
    @classmethod
    def _clamp_relative(cls, val: Any) -> float:
        float_val = float(val)
        return max(0.0, min(1.0, round(float_val, 4)))

    @field_validator("type", mode="before")
    @classmethod
    def _validate_type(cls, val: Any) -> BlockType:
        norm = normalize_block_type(val)
        if norm is None:
            raise ValueError(f"Invalid or non-target block type: {val}")
        return norm


class CanvasAnalysisRequest(BaseModel):
    """Pydantic model for canvas analysis API request."""

    task_id: Optional[str] = Field(default=None, description="Diagnostic task or GFF identifier.")
    image_base64: str = Field(..., description="Base64 encoded screenshot of the canvas area.")
    canvas_bbox: Optional[CanvasBoundingBox] = Field(
        default=None,
        description="Optional bounding box of canvas on screen to compute screen coordinates.",
    )


class CanvasAnalysisResponse(BaseModel):
    """Pydantic model for canvas analysis API response."""

    blocks: List[DetectedBlock] = Field(
        default_factory=list,
        description="List of detected target blocks sorted by vertical execution sequence.",
    )
    task_id: Optional[str] = Field(default=None, description="Diagnostic task identifier.")
    total_detected: int = Field(default=0, description="Total count of detected target blocks.")
    execution_time_seconds: Optional[float] = Field(
        default=None,
        description="Duration of vision analysis in seconds.",
    )


class PopupType(str, Enum):
    """Types of modal dialogs and popups in ODIS Creator."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    SEARCH_ENDED = "SEARCH_ENDED"
    USAGE_LOCATIONS = "USAGE_LOCATIONS"
    SAVE_CONFIRMATION = "SAVE_CONFIRMATION"
    GENERIC_DIALOG = "GENERIC_DIALOG"
    NONE = "NONE"


class PopupDetectionResult(BaseModel):
    """Result of popup and modal dialog detection."""

    detected: bool = Field(default=False, description="Whether a modal popup is currently visible.")
    popup_type: PopupType = Field(default=PopupType.NONE, description="Classification of the modal popup.")
    title: Optional[str] = Field(default=None, description="Title text of the modal window.")
    message: Optional[str] = Field(default=None, description="Informational or error message in dialog.")
    ok_button_relative_x: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Normalized relative X coordinate of primary/OK button."
    )
    ok_button_relative_y: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Normalized relative Y coordinate of primary/OK button."
    )
    cancel_button_relative_x: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Normalized relative X coordinate of Cancel button."
    )
    cancel_button_relative_y: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Normalized relative Y coordinate of Cancel button."
    )


# System instruction for gemini-3.7-flash canvas flowchart parsing
CANVAS_ANALYSIS_SYSTEM_INSTRUCTION = """You are an expert visual diagram parser for ODIS Creator diagnostic flowcharts (Test Module Editor).
Your task is to analyze the provided screenshot of an ODIS Creator flowchart canvas and locate all editable target blocks that may contain text requiring sanitization.

Target Blocks to detect:
1. "MESSAGE":
   - Visual: Rectangular block with a green parchment / folded-corner document icon.
   - Purpose: Informational message/instruction displayed to the user in ODIS Service.
2. "QUESTION":
   - Visual: Rectangular block with a green question mark (?) / speech bubble icon.
   - Purpose: Interactive decision point for the operator (Yes/No or list selection).
3. "COMMENT":
   - Visual: Rectangular block with a cyan / light blue notepad / memo note icon.
   - Purpose: Internal commentary note within the diagnostic tree.

NON-Target Blocks to IGNORE categorically:
- "If" condition blocks (yellow diamond / rhombus shape).
- "Subroutine" call blocks (yellow / orange rectangular blocks).
- "Expression" / calculation blocks.
- "Read file" and "Write file" blocks.
- "Set status" blocks.
- Background grid lines, flow lines, arrow connectors, and branch labels.

For each detected Target Block, provide:
- "type": EXACTLY one of ["MESSAGE", "QUESTION", "COMMENT"]
- "relative_x": Center horizontal position normalized between 0.0 (left edge of image) and 1.0 (right edge of image).
- "relative_y": Center vertical position normalized between 0.0 (top edge of image) and 1.0 (bottom edge of image).
- "label": Short text label or summary visible on or near the block.

Rules:
- Coordinate values must be between 0.0 and 1.0.
- Order the blocks from top to bottom (flow order, increasing relative_y), then left to right.
- You must return ONLY valid JSON matching this schema:
{
  "blocks": [
    {
      "type": "MESSAGE",
      "relative_x": 0.45,
      "relative_y": 0.32,
      "label": "Message With this test..."
    }
  ]
}
"""

CANVAS_ANALYSIS_USER_PROMPT = (
    "Analyze this ODIS Creator canvas screenshot. Locate all target blocks "
    "('MESSAGE', 'QUESTION', 'COMMENT') and return their normalized center "
    "coordinates (0.0 to 1.0) and labels in JSON format."
)

POPUP_DETECTION_SYSTEM_INSTRUCTION = """You are an expert UI analyzer for ODIS Creator.
Your task is to analyze the provided screenshot and determine if any modal dialog or popup is currently displayed.

Identify:
1. "VALIDATION_ERROR": Modal titled "Validation error" with message "Dialog validation failed. Please enter correct data."
2. "SEARCH_ENDED": Modal titled "Search ended" with notification "The search is complete."
3. "USAGE_LOCATIONS": Modal titled "Usage locations".
4. "SAVE_CONFIRMATION": Dialog asking to save changes (e.g. Save / Yes / Cancel).
5. "GENERIC_DIALOG": Any other modal or alert dialog.
6. "NONE": No popup is visible (standard workflow screen).

For detected popups, provide:
- "detected": boolean
- "popup_type": one of ["VALIDATION_ERROR", "SEARCH_ENDED", "USAGE_LOCATIONS", "SAVE_CONFIRMATION", "GENERIC_DIALOG", "NONE"]
- "title": Title of the popup dialog (if visible)
- "message": Informational/error text in the popup (if visible)
- "ok_button_relative_x": Normalized center X coordinate of the "OK" / "Save" / primary button (0.0 to 1.0)
- "ok_button_relative_y": Normalized center Y coordinate of the "OK" / "Save" / primary button (0.0 to 1.0)
- "cancel_button_relative_x": Normalized center X coordinate of the "Cancel" button if present
- "cancel_button_relative_y": Normalized center Y coordinate of the "Cancel" button if present

Return ONLY valid JSON matching this schema:
{
  "detected": true,
  "popup_type": "VALIDATION_ERROR",
  "title": "Validation error",
  "message": "Dialog validation failed. Please enter correct data.",
  "ok_button_relative_x": 0.52,
  "ok_button_relative_y": 0.60,
  "cancel_button_relative_x": null,
  "cancel_button_relative_y": null
}
"""

POPUP_DETECTION_USER_PROMPT = (
    "Analyze this ODIS Creator screenshot. Check if any modal popup or dialog is visible, "
    "classify it, and return its button coordinates in JSON format."
)


def map_relative_to_screen(
    relative_x: float,
    relative_y: float,
    bbox: CanvasBoundingBox,
) -> Tuple[int, int]:
    """Helper function to map normalized coordinates [0.0, 1.0] to screen coordinates.

    Args:
        relative_x: Normalized horizontal coordinate.
        relative_y: Normalized vertical coordinate.
        bbox: CanvasBoundingBox instance.

    Returns:
        Tuple of (screen_x, screen_y) integers.
    """
    return bbox.to_screen_coords(relative_x, relative_y)


def map_screen_to_relative(
    screen_x: int,
    screen_y: int,
    bbox: CanvasBoundingBox,
) -> Tuple[float, float]:
    """Helper function to map screen coordinates to normalized coordinates [0.0, 1.0].

    Args:
        screen_x: Absolute screen X coordinate.
        screen_y: Absolute screen Y coordinate.
        bbox: CanvasBoundingBox instance.

    Returns:
        Tuple of (relative_x, relative_y) floats.
    """
    return bbox.to_relative_coords(screen_x, screen_y)


class VisionEngine:
    """Multimodal vision parser for ODIS Creator flowchart canvas and UI elements."""

    def __init__(
        self,
        kelpie_client: Optional[KelpieClient] = None,
        settings: Optional[Settings] = None,
        model: Optional[str] = None,
    ):
        """Initialize VisionEngine.

        Args:
            kelpie_client: Optional KelpieClient instance (creates default if None).
            settings: Optional Settings instance.
            model: Optional model override (defaults to settings.kelpie_model).
        """
        self.settings = settings or get_settings()
        self.client = kelpie_client or KelpieClient(settings=self.settings)
        self.model = model or self.settings.kelpie_model

    def parse_model_response(
        self,
        response_data: Any,
        canvas_bbox: Optional[CanvasBoundingBox] = None,
    ) -> List[DetectedBlock]:
        """Parse raw model response into a validated, sorted list of DetectedBlock items.

        Filters out non-target blocks and calculates screen coordinates if canvas_bbox is provided.
        Blocks are sorted top-to-bottom, left-to-right following flowchart execution sequence.

        Args:
            response_data: Parsed JSON dict, list, or string from Gemini model.
            canvas_bbox: Optional canvas bounding box for screen coordinate mapping.

        Returns:
            List of DetectedBlock instances.
        """
        if isinstance(response_data, str):
            clean_str = strip_markdown_codeblocks(response_data)
            try:
                response_data = json.loads(clean_str)
            except json.JSONDecodeError as exc:
                logger.warning(f"Failed to parse model response string as JSON: {exc}")
                return []

        raw_blocks: List[Dict[str, Any]] = []

        if isinstance(response_data, dict):
            # Standard structure: {"blocks": [...]}
            if "blocks" in response_data and isinstance(response_data["blocks"], list):
                raw_blocks = response_data["blocks"]
            elif "target_blocks" in response_data and isinstance(response_data["target_blocks"], list):
                raw_blocks = response_data["target_blocks"]
            elif "elements" in response_data and isinstance(response_data["elements"], list):
                raw_blocks = response_data["elements"]
            else:
                # Might be a single block dictionary
                if "type" in response_data and ("relative_x" in response_data or "x" in response_data):
                    raw_blocks = [response_data]

        elif isinstance(response_data, list):
            raw_blocks = response_data

        detected_blocks: List[DetectedBlock] = []

        for item in raw_blocks:
            if not isinstance(item, dict):
                continue

            raw_type = item.get("type") or item.get("block_type") or item.get("category")
            block_type = normalize_block_type(raw_type)

            # Skip non-target blocks (e.g. IF, SUBROUTINE, EXPRESSION, READ_FILE)
            if block_type is None:
                logger.debug(f"Skipping non-target block with raw type: {raw_type}")
                continue

            # Extract coordinates (support relative_x, x, rel_x, x_rel)
            rel_x_val = item.get("relative_x")
            if rel_x_val is None:
                rel_x_val = item.get("rel_x") or item.get("x_rel") or item.get("x")
            if rel_x_val is None:
                continue

            rel_y_val = item.get("relative_y")
            if rel_y_val is None:
                rel_y_val = item.get("rel_y") or item.get("y_rel") or item.get("y")
            if rel_y_val is None:
                continue

            try:
                rel_x = float(rel_x_val)
                rel_y = float(rel_y_val)
            except (ValueError, TypeError):
                continue

            # Normalize if coordinates were provided on [0, 100] percentage scale
            if rel_x > 1.0 and rel_x <= 100.0:
                rel_x = rel_x / 100.0
            if rel_y > 1.0 and rel_y <= 100.0:
                rel_y = rel_y / 100.0

            # Clamp to [0.0, 1.0]
            rel_x = max(0.0, min(1.0, round(rel_x, 4)))
            rel_y = max(0.0, min(1.0, round(rel_y, 4)))

            label = item.get("label") or item.get("text") or item.get("description")
            if label is not None:
                label = str(label).strip()

            screen_x: Optional[int] = None
            screen_y: Optional[int] = None
            if canvas_bbox is not None:
                screen_x, screen_y = canvas_bbox.to_screen_coords(rel_x, rel_y)

            confidence_val = item.get("confidence", 1.0)
            try:
                confidence = max(0.0, min(1.0, float(confidence_val)))
            except (ValueError, TypeError):
                confidence = 1.0

            try:
                block = DetectedBlock(
                    type=block_type,
                    relative_x=rel_x,
                    relative_y=rel_y,
                    label=label,
                    screen_x=screen_x,
                    screen_y=screen_y,
                    confidence=confidence,
                )
                detected_blocks.append(block)
            except Exception as exc:
                logger.warning(f"Error creating DetectedBlock from {item}: {exc}")

        # Sort blocks by execution sequence: top-to-bottom (relative_y), then left-to-right (relative_x)
        detected_blocks.sort(key=lambda b: (round(b.relative_y, 2), round(b.relative_x, 2)))

        return detected_blocks

    def analyze_canvas(
        self,
        image: Union[str, bytes, Image.Image],
        canvas_bbox: Optional[CanvasBoundingBox] = None,
        task_id: Optional[str] = None,
        custom_prompt: Optional[str] = None,
    ) -> CanvasAnalysisResponse:
        """Analyze an ODIS Creator canvas screenshot and locate target blocks.

        Args:
            image: Canvas screenshot as base64 string, data URI, bytes, or PIL Image.
            canvas_bbox: Optional CanvasBoundingBox for calculating absolute screen coordinates.
            task_id: Optional diagnostic task identifier.
            custom_prompt: Optional user prompt override.

        Returns:
            CanvasAnalysisResponse containing detected target blocks.

        Raises:
            KelpieRequestError: If network request fails.
            KelpieResponseError: If response cannot be parsed.
        """
        start_time = time.time()
        user_prompt = custom_prompt or CANVAS_ANALYSIS_USER_PROMPT

        response_json = self.client.generate_json(
            prompt=user_prompt,
            image_base64=image,
            system_instruction=CANVAS_ANALYSIS_SYSTEM_INSTRUCTION,
            temperature=0.0,
            model=self.model,
        )

        blocks = self.parse_model_response(response_json, canvas_bbox=canvas_bbox)
        duration = round(time.time() - start_time, 3)

        return CanvasAnalysisResponse(
            blocks=blocks,
            task_id=task_id,
            total_detected=len(blocks),
            execution_time_seconds=duration,
        )

    def parse_popup_response(self, response_data: Any) -> PopupDetectionResult:
        """Parse raw model response into a PopupDetectionResult instance.

        Args:
            response_data: Parsed JSON dict, list, or string from Gemini model.

        Returns:
            PopupDetectionResult instance.
        """
        if isinstance(response_data, str):
            clean_str = strip_markdown_codeblocks(response_data)
            try:
                response_data = json.loads(clean_str)
            except json.JSONDecodeError:
                return PopupDetectionResult(detected=False, popup_type=PopupType.NONE)

        if isinstance(response_data, list) and response_data:
            response_data = response_data[0]

        if not isinstance(response_data, dict):
            return PopupDetectionResult(detected=False, popup_type=PopupType.NONE)

        detected = bool(response_data.get("detected", False))
        raw_type = response_data.get("popup_type", "NONE")

        try:
            popup_type = PopupType(str(raw_type).strip().upper())
        except ValueError:
            popup_type = PopupType.GENERIC_DIALOG if detected else PopupType.NONE

        title = response_data.get("title")
        message = response_data.get("message")

        def _parse_coord(val: Any) -> Optional[float]:
            if val is None:
                return None
            try:
                f = float(val)
                if f > 1.0 and f <= 100.0:
                    f = f / 100.0
                return max(0.0, min(1.0, round(f, 4)))
            except (ValueError, TypeError):
                return None

        ok_x = _parse_coord(response_data.get("ok_button_relative_x"))
        ok_y = _parse_coord(response_data.get("ok_button_relative_y"))
        cancel_x = _parse_coord(response_data.get("cancel_button_relative_x"))
        cancel_y = _parse_coord(response_data.get("cancel_button_relative_y"))

        return PopupDetectionResult(
            detected=detected,
            popup_type=popup_type,
            title=str(title) if title is not None else None,
            message=str(message) if message is not None else None,
            ok_button_relative_x=ok_x,
            ok_button_relative_y=ok_y,
            cancel_button_relative_x=cancel_x,
            cancel_button_relative_y=cancel_y,
        )

    def detect_popup(
        self,
        image: Union[str, bytes, Image.Image],
        custom_prompt: Optional[str] = None,
    ) -> PopupDetectionResult:
        """Detect and classify any modal popup/dialog in an ODIS screenshot.

        Args:
            image: Screenshot as base64 string, data URI, bytes, or PIL Image.
            custom_prompt: Optional prompt override.

        Returns:
            PopupDetectionResult instance.
        """
        user_prompt = custom_prompt or POPUP_DETECTION_USER_PROMPT

        response_json = self.client.generate_json(
            prompt=user_prompt,
            image_base64=image,
            system_instruction=POPUP_DETECTION_SYSTEM_INSTRUCTION,
            temperature=0.0,
            model=self.model,
        )

        return self.parse_popup_response(response_json)


def analyze_canvas(
    image: Union[str, bytes, Image.Image],
    canvas_bbox: Optional[CanvasBoundingBox] = None,
    task_id: Optional[str] = None,
    kelpie_client: Optional[KelpieClient] = None,
) -> CanvasAnalysisResponse:
    """Convenience helper function to analyze canvas using default VisionEngine.

    Args:
        image: Screenshot input.
        canvas_bbox: Optional screen bounding box.
        task_id: Optional task identifier.
        kelpie_client: Optional KelpieClient instance.

    Returns:
        CanvasAnalysisResponse instance.
    """
    engine = VisionEngine(kelpie_client=kelpie_client)
    return engine.analyze_canvas(image=image, canvas_bbox=canvas_bbox, task_id=task_id)
