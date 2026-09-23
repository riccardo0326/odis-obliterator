"""Unit tests for Vision Engine and Canvas Coordinate Mapping (TASK-004)."""

import base64
import io
import json
from unittest.mock import MagicMock, patch
import pytest
from PIL import Image, ImageDraw

from controller.config import Settings
from controller.kelpie_client import KelpieClient, KelpieRequestError, KelpieResponseError
from controller.vision_engine import (
    CANVAS_ANALYSIS_SYSTEM_INSTRUCTION,
    CANVAS_ANALYSIS_USER_PROMPT,
    POPUP_DETECTION_SYSTEM_INSTRUCTION,
    POPUP_DETECTION_USER_PROMPT,
    BlockType,
    CanvasAnalysisRequest,
    CanvasAnalysisResponse,
    CanvasBoundingBox,
    DetectedBlock,
    PopupDetectionResult,
    PopupType,
    VisionEngine,
    analyze_canvas,
    map_relative_to_screen,
    map_screen_to_relative,
    normalize_block_type,
)


# ---------------------------------------------------------------------------
# Test Coordinate Mapping & Bounding Box
# ---------------------------------------------------------------------------

class TestCoordinateMapping:
    """Tests for coordinate conversion between relative [0.0, 1.0] and screen pixels."""

    def test_canvas_bounding_box_creation(self):
        bbox = CanvasBoundingBox(x=510, y=120, width=1400, height=900)
        assert bbox.x == 510
        assert bbox.y == 120
        assert bbox.width == 1400
        assert bbox.height == 900

    def test_canvas_bounding_box_defaults(self):
        bbox = CanvasBoundingBox(width=1000, height=800)
        assert bbox.x == 0
        assert bbox.y == 0
        assert bbox.width == 1000
        assert bbox.height == 800

    def test_invalid_bounding_box_dimensions(self):
        with pytest.raises(ValueError):
            CanvasBoundingBox(width=0, height=500)
        with pytest.raises(ValueError):
            CanvasBoundingBox(width=500, height=-10)

    def test_to_screen_coords_origin_and_extremes(self):
        bbox = CanvasBoundingBox(x=100, y=200, width=1000, height=800)
        
        # Origin (0.0, 0.0) -> top-left
        sx, sy = bbox.to_screen_coords(0.0, 0.0)
        assert sx == 100
        assert sy == 200

        # Extreme (1.0, 1.0) -> bottom-right
        sx, sy = bbox.to_screen_coords(1.0, 1.0)
        assert sx == 1100
        assert sy == 1000

        # Center (0.5, 0.5)
        sx, sy = bbox.to_screen_coords(0.5, 0.5)
        assert sx == 600
        assert sy == 600

    def test_to_screen_coords_design_spec_example(self):
        # DESIGN.md example: canvas_bbox: {"x": 510, "y": 120, "width": 1400, "height": 900}
        # Block: relative_x: 0.45, relative_y: 0.32
        bbox = CanvasBoundingBox(x=510, y=120, width=1400, height=900)
        sx, sy = bbox.to_screen_coords(0.45, 0.32)
        # Expected: 510 + (0.45 * 1400) = 510 + 630 = 1140
        # Expected: 120 + (0.32 * 900) = 120 + 288 = 408
        assert sx == 1140
        assert sy == 408

    def test_to_screen_coords_clamping(self):
        bbox = CanvasBoundingBox(x=100, y=100, width=500, height=500)
        
        # Negative relative coordinates clamped to min
        sx, sy = bbox.to_screen_coords(-0.5, -0.2)
        assert sx == 100
        assert sy == 100

        # Coordinates > 1.0 clamped to max
        sx, sy = bbox.to_screen_coords(1.5, 2.0)
        assert sx == 600
        assert sy == 600

    def test_to_relative_coords(self):
        bbox = CanvasBoundingBox(x=100, y=200, width=1000, height=800)
        
        rx, ry = bbox.to_relative_coords(100, 200)
        assert rx == 0.0
        assert ry == 0.0

        rx, ry = bbox.to_relative_coords(1100, 1000)
        assert rx == 1.0
        assert ry == 1.0

        rx, ry = bbox.to_relative_coords(600, 600)
        assert rx == 0.5
        assert ry == 0.5

    def test_to_relative_coords_clamping(self):
        bbox = CanvasBoundingBox(x=100, y=200, width=1000, height=800)
        
        # Outside left/top
        rx, ry = bbox.to_relative_coords(50, 100)
        assert rx == 0.0
        assert ry == 0.0

        # Outside right/bottom
        rx, ry = bbox.to_relative_coords(2000, 2000)
        assert rx == 1.0
        assert ry == 1.0

    def test_standalone_helper_functions(self):
        bbox = CanvasBoundingBox(x=200, y=100, width=800, height=600)
        
        sx, sy = map_relative_to_screen(0.25, 0.75, bbox)
        assert sx == 200 + 200  # 400
        assert sy == 100 + 450  # 550

        rx, ry = map_screen_to_relative(400, 550, bbox)
        assert rx == 0.25
        assert ry == 0.75


# ---------------------------------------------------------------------------
# Test BlockType Normalization & Pydantic Models
# ---------------------------------------------------------------------------

class TestBlockTypesAndModels:
    """Tests for BlockType normalization and Pydantic schemas."""

    def test_normalize_block_type_canonical(self):
        assert normalize_block_type("MESSAGE") == BlockType.MESSAGE
        assert normalize_block_type("QUESTION") == BlockType.QUESTION
        assert normalize_block_type("COMMENT") == BlockType.COMMENT

    def test_normalize_block_type_case_insensitive_and_aliases(self):
        assert normalize_block_type("message") == BlockType.MESSAGE
        assert normalize_block_type("Message") == BlockType.MESSAGE
        assert normalize_block_type("msg") == BlockType.MESSAGE
        assert normalize_block_type("question") == BlockType.QUESTION
        assert normalize_block_type("Question") == BlockType.QUESTION
        assert normalize_block_type("quest") == BlockType.QUESTION
        assert normalize_block_type("comment") == BlockType.COMMENT
        assert normalize_block_type("Comment") == BlockType.COMMENT
        assert normalize_block_type("commentary") == BlockType.COMMENT

    def test_normalize_block_type_ignores_non_target(self):
        # Non-target elements in ODIS flowchart must return None
        assert normalize_block_type("IF") is None
        assert normalize_block_type("if") is None
        assert normalize_block_type("SUBROUTINE") is None
        assert normalize_block_type("subroutine") is None
        assert normalize_block_type("EXPRESSION") is None
        assert normalize_block_type("READ_FILE") is None
        assert normalize_block_type("WRITE_FILE") is None
        assert normalize_block_type("SET_STATUS") is None
        assert normalize_block_type("unknown_type") is None
        assert normalize_block_type(None) is None
        assert normalize_block_type(123) is None

    def test_detected_block_validation(self):
        block = DetectedBlock(
            type="MESSAGE",
            relative_x=0.45,
            relative_y=0.32,
            label="Message With this test...",
            screen_x=1140,
            screen_y=408,
            confidence=0.98,
        )
        assert block.type == BlockType.MESSAGE
        assert block.relative_x == 0.45
        assert block.relative_y == 0.32
        assert block.label == "Message With this test..."
        assert block.screen_x == 1140
        assert block.screen_y == 408
        assert block.confidence == 0.98

    def test_detected_block_clamping_validator(self):
        block = DetectedBlock(
            type="QUESTION",
            relative_x=-0.1,
            relative_y=1.5,
        )
        assert block.relative_x == 0.0
        assert block.relative_y == 1.0

    def test_detected_block_invalid_type_raises(self):
        with pytest.raises(ValueError):
            DetectedBlock(type="IF", relative_x=0.5, relative_y=0.5)

    def test_canvas_analysis_request_model(self):
        req = CanvasAnalysisRequest(
            task_id="GFF_042",
            image_base64="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            canvas_bbox=CanvasBoundingBox(x=510, y=120, width=1400, height=900),
        )
        assert req.task_id == "GFF_042"
        assert req.canvas_bbox.width == 1400
        dict_data = req.model_dump()
        assert dict_data["task_id"] == "GFF_042"
        assert dict_data["canvas_bbox"]["x"] == 510

    def test_canvas_analysis_response_model(self):
        blocks = [
            DetectedBlock(type=BlockType.MESSAGE, relative_x=0.45, relative_y=0.32, label="Msg 1"),
            DetectedBlock(type=BlockType.COMMENT, relative_x=0.52, relative_y=0.58, label="Comment 1"),
        ]
        resp = CanvasAnalysisResponse(
            blocks=blocks,
            task_id="GFF_042",
            total_detected=2,
            execution_time_seconds=0.452,
        )
        assert resp.total_detected == 2
        assert resp.task_id == "GFF_042"
        assert len(resp.blocks) == 2
        assert resp.blocks[0].type == BlockType.MESSAGE
        assert resp.blocks[1].type == BlockType.COMMENT

    def test_popup_detection_model(self):
        res = PopupDetectionResult(
            detected=True,
            popup_type=PopupType.VALIDATION_ERROR,
            title="Validation error",
            message="Dialog validation failed. Please enter correct data.",
            ok_button_relative_x=0.52,
            ok_button_relative_y=0.60,
        )
        assert res.detected is True
        assert res.popup_type == PopupType.VALIDATION_ERROR
        assert res.ok_button_relative_x == 0.52


# ---------------------------------------------------------------------------
# Test Model Response Parsing in VisionEngine
# ---------------------------------------------------------------------------

class TestModelResponseParsing:
    """Tests for parsing raw Gemini JSON output into structured DetectedBlock lists."""

    def setup_method(self):
        self.engine = VisionEngine()

    def test_parse_standard_blocks_dict(self):
        raw_json = {
            "blocks": [
                {
                    "type": "MESSAGE",
                    "relative_x": 0.45,
                    "relative_y": 0.32,
                    "label": "Message With this test...",
                },
                {
                    "type": "COMMENT",
                    "relative_x": 0.52,
                    "relative_y": 0.58,
                    "label": "Comment 1 = statisch",
                },
                {
                    "type": "QUESTION",
                    "relative_x": 0.61,
                    "relative_y": 0.75,
                    "label": "Question Yes/No,...",
                },
            ]
        }
        blocks = self.engine.parse_model_response(raw_json)
        assert len(blocks) == 3
        assert blocks[0].type == BlockType.MESSAGE
        assert blocks[0].relative_x == 0.45
        assert blocks[0].relative_y == 0.32
        assert blocks[0].label == "Message With this test..."
        assert blocks[1].type == BlockType.COMMENT
        assert blocks[2].type == BlockType.QUESTION

    def test_parse_raw_list_response(self):
        raw_list = [
            {"type": "MESSAGE", "relative_x": 0.3, "relative_y": 0.2, "label": "Msg A"},
            {"type": "QUESTION", "relative_x": 0.4, "relative_y": 0.5, "label": "Quest B"},
        ]
        blocks = self.engine.parse_model_response(raw_list)
        assert len(blocks) == 2
        assert blocks[0].type == BlockType.MESSAGE
        assert blocks[1].type == BlockType.QUESTION

    def test_parse_string_json_with_codeblock_markdown(self):
        raw_str = """```json
{
  "blocks": [
    {"type": "COMMENT", "relative_x": 0.5, "relative_y": 0.4, "label": "Internal note"}
  ]
}
```"""
        blocks = self.engine.parse_model_response(raw_str)
        assert len(blocks) == 1
        assert blocks[0].type == BlockType.COMMENT
        assert blocks[0].relative_x == 0.5
        assert blocks[0].relative_y == 0.4

    def test_filters_non_target_blocks(self):
        # Model might return IF, Subroutine, or Expression blocks: they must be ignored!
        raw_data = {
            "blocks": [
                {"type": "MESSAGE", "relative_x": 0.4, "relative_y": 0.2, "label": "Valid Message"},
                {"type": "IF", "relative_x": 0.4, "relative_y": 0.4, "label": "Condition diamond"},
                {"type": "Subroutine", "relative_x": 0.4, "relative_y": 0.6, "label": "Aux routine"},
                {"type": "QUESTION", "relative_x": 0.4, "relative_y": 0.8, "label": "Valid Question"},
                {"type": "Expression", "relative_x": 0.5, "relative_y": 0.9, "label": "Assignment"},
            ]
        }
        blocks = self.engine.parse_model_response(raw_data)
        assert len(blocks) == 2
        assert blocks[0].type == BlockType.MESSAGE
        assert blocks[1].type == BlockType.QUESTION

    def test_converts_percentage_scale_to_normalized(self):
        # Some models might return 0-100 values instead of 0.0-1.0
        raw_data = {
            "blocks": [
                {"type": "MESSAGE", "relative_x": 45.0, "relative_y": 32.0, "label": "Percent scaled"},
            ]
        }
        blocks = self.engine.parse_model_response(raw_data)
        assert len(blocks) == 1
        assert blocks[0].relative_x == 0.45
        assert blocks[0].relative_y == 0.32

    def test_computes_screen_coordinates_when_bbox_provided(self):
        bbox = CanvasBoundingBox(x=500, y=100, width=1000, height=800)
        raw_data = {
            "blocks": [
                {"type": "MESSAGE", "relative_x": 0.5, "relative_y": 0.5, "label": "Center msg"},
            ]
        }
        blocks = self.engine.parse_model_response(raw_data, canvas_bbox=bbox)
        assert len(blocks) == 1
        assert blocks[0].screen_x == 1000  # 500 + 0.5*1000
        assert blocks[0].screen_y == 500   # 100 + 0.5*800

    def test_sorts_blocks_in_execution_flow(self):
        # Unsorted blocks should be ordered top-to-bottom (relative_y), then left-to-right (relative_x)
        raw_data = {
            "blocks": [
                {"type": "QUESTION", "relative_x": 0.5, "relative_y": 0.9, "label": "Step 3"},
                {"type": "MESSAGE", "relative_x": 0.5, "relative_y": 0.1, "label": "Step 1"},
                {"type": "COMMENT", "relative_x": 0.2, "relative_y": 0.5, "label": "Step 2A"},
                {"type": "MESSAGE", "relative_x": 0.8, "relative_y": 0.5, "label": "Step 2B"},
            ]
        }
        blocks = self.engine.parse_model_response(raw_data)
        assert len(blocks) == 4
        assert blocks[0].label == "Step 1"
        assert blocks[1].label == "Step 2A"
        assert blocks[2].label == "Step 2B"
        assert blocks[3].label == "Step 3"

    def test_handles_malformed_and_empty_responses(self):
        assert self.engine.parse_model_response({}) == []
        assert self.engine.parse_model_response([]) == []
        assert self.engine.parse_model_response("invalid json text") == []
        assert self.engine.parse_model_response(None) == []


# ---------------------------------------------------------------------------
# Test Popup Detection Response Parsing
# ---------------------------------------------------------------------------

class TestPopupDetectionParsing:
    """Tests for parsing popup and modal dialog responses."""

    def setup_method(self):
        self.engine = VisionEngine()

    def test_parse_validation_error_popup(self):
        raw_data = {
            "detected": True,
            "popup_type": "VALIDATION_ERROR",
            "title": "Validation error",
            "message": "Dialog validation failed. Please enter correct data.",
            "ok_button_relative_x": 0.52,
            "ok_button_relative_y": 0.60,
        }
        res = self.engine.parse_popup_response(raw_data)
        assert res.detected is True
        assert res.popup_type == PopupType.VALIDATION_ERROR
        assert res.title == "Validation error"
        assert res.message == "Dialog validation failed. Please enter correct data."
        assert res.ok_button_relative_x == 0.52
        assert res.ok_button_relative_y == 0.60
        assert res.cancel_button_relative_x is None

    def test_parse_search_ended_popup(self):
        raw_data = {
            "detected": True,
            "popup_type": "SEARCH_ENDED",
            "title": "Search ended",
            "message": "The search is complete.",
            "ok_button_relative_x": 0.5,
            "ok_button_relative_y": 0.55,
        }
        res = self.engine.parse_popup_response(raw_data)
        assert res.detected is True
        assert res.popup_type == PopupType.SEARCH_ENDED
        assert res.ok_button_relative_x == 0.5

    def test_parse_no_popup_visible(self):
        raw_data = {
            "detected": False,
            "popup_type": "NONE",
        }
        res = self.engine.parse_popup_response(raw_data)
        assert res.detected is False
        assert res.popup_type == PopupType.NONE

    def test_parse_popup_markdown_string(self):
        raw_str = """```json
{
  "detected": true,
  "popup_type": "USAGE_LOCATIONS",
  "title": "Usage locations",
  "ok_button_relative_x": 0.65,
  "ok_button_relative_y": 0.85
}
```"""
        res = self.engine.parse_popup_response(raw_str)
        assert res.detected is True
        assert res.popup_type == PopupType.USAGE_LOCATIONS
        assert res.ok_button_relative_x == 0.65


# ---------------------------------------------------------------------------
# Test VisionEngine Integration with Mock KelpieClient
# ---------------------------------------------------------------------------

class TestVisionEngineWithMockClient:
    """Tests for VisionEngine canvas analysis calling Kelpie AI Gateway."""

    def _create_test_image(self) -> Image.Image:
        """Create a simple synthetic image representing a canvas."""
        img = Image.new("RGB", (800, 600), color=(240, 240, 240))
        draw = ImageDraw.Draw(img)
        # Draw a simulated message block
        draw.rectangle([200, 100, 400, 160], fill=(220, 255, 220), outline=(0, 150, 0))
        draw.text((210, 110), "Message Block 1", fill=(0, 0, 0))
        return img

    def test_analyze_canvas_invokes_kelpie_with_proper_payload(self):
        mock_client = MagicMock(spec=KelpieClient)
        mock_client.generate_json.return_value = {
            "blocks": [
                {
                    "type": "MESSAGE",
                    "relative_x": 0.45,
                    "relative_y": 0.32,
                    "label": "Message With this test...",
                },
                {
                    "type": "COMMENT",
                    "relative_x": 0.52,
                    "relative_y": 0.58,
                    "label": "Comment 1 = statisch",
                },
            ]
        }

        engine = VisionEngine(kelpie_client=mock_client)
        test_img = self._create_test_image()
        bbox = CanvasBoundingBox(x=510, y=120, width=1400, height=900)

        response = engine.analyze_canvas(
            image=test_img,
            canvas_bbox=bbox,
            task_id="GFF_042",
        )

        # Verify call arguments to KelpieClient
        mock_client.generate_json.assert_called_once()
        call_kwargs = mock_client.generate_json.call_args.kwargs
        assert call_kwargs["prompt"] == CANVAS_ANALYSIS_USER_PROMPT
        assert call_kwargs["image_base64"] == test_img
        assert call_kwargs["system_instruction"] == CANVAS_ANALYSIS_SYSTEM_INSTRUCTION
        assert call_kwargs["temperature"] == 0.0

        # Verify response structure
        assert response.task_id == "GFF_042"
        assert response.total_detected == 2
        assert len(response.blocks) == 2
        assert response.execution_time_seconds is not None
        assert response.execution_time_seconds >= 0.0

        # Check screen coordinate calculation
        msg_block = response.blocks[0]
        assert msg_block.type == BlockType.MESSAGE
        assert msg_block.relative_x == 0.45
        assert msg_block.screen_x == 1140  # 510 + 0.45*1400
        assert msg_block.screen_y == 408   # 120 + 0.32*900

    def test_analyze_canvas_base64_string_input(self):
        mock_client = MagicMock(spec=KelpieClient)
        mock_client.generate_json.return_value = {
            "blocks": [
                {"type": "QUESTION", "relative_x": 0.6, "relative_y": 0.7, "label": "Question Yes/No"}
            ]
        }

        engine = VisionEngine(kelpie_client=mock_client)
        b64_img = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

        resp = engine.analyze_canvas(image=b64_img, task_id="TEST_001")
        assert resp.total_detected == 1
        assert resp.blocks[0].type == BlockType.QUESTION

    def test_detect_popup_invokes_kelpie(self):
        mock_client = MagicMock(spec=KelpieClient)
        mock_client.generate_json.return_value = {
            "detected": True,
            "popup_type": "VALIDATION_ERROR",
            "title": "Validation error",
            "message": "Dialog validation failed. Please enter correct data.",
            "ok_button_relative_x": 0.52,
            "ok_button_relative_y": 0.60,
        }

        engine = VisionEngine(kelpie_client=mock_client)
        test_img = self._create_test_image()

        res = engine.detect_popup(image=test_img)

        mock_client.generate_json.assert_called_once()
        call_kwargs = mock_client.generate_json.call_args.kwargs
        assert call_kwargs["prompt"] == POPUP_DETECTION_USER_PROMPT
        assert call_kwargs["system_instruction"] == POPUP_DETECTION_SYSTEM_INSTRUCTION

        assert res.detected is True
        assert res.popup_type == PopupType.VALIDATION_ERROR
        assert res.ok_button_relative_x == 0.52

    def test_analyze_canvas_propagates_kelpie_request_error(self):
        mock_client = MagicMock(spec=KelpieClient)
        mock_client.generate_json.side_effect = KelpieRequestError("Connection timeout to gateway")

        engine = VisionEngine(kelpie_client=mock_client)
        test_img = self._create_test_image()

        with pytest.raises(KelpieRequestError) as exc_info:
            engine.analyze_canvas(image=test_img)
        assert "Connection timeout" in str(exc_info.value)

    def test_standalone_analyze_canvas_convenience_function(self):
        mock_client = MagicMock(spec=KelpieClient)
        mock_client.generate_json.return_value = {
            "blocks": [
                {"type": "MESSAGE", "relative_x": 0.1, "relative_y": 0.2, "label": "Top msg"}
            ]
        }

        test_img = self._create_test_image()
        resp = analyze_canvas(image=test_img, task_id="CONV_01", kelpie_client=mock_client)
        assert resp.total_detected == 1
        assert resp.blocks[0].type == BlockType.MESSAGE
