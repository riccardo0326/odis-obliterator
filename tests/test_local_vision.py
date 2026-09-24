"""Unit tests for Local Vision Engine & Template Matching (TASK-011)."""

import base64
import io
import math
from pathlib import Path
import tempfile
import pytest
from PIL import Image, ImageDraw

from controller.config import Settings
from controller.vision_engine import (
    BlockType,
    CanvasBoundingBox,
    DetectedBlock,
    CanvasAnalysisResponse,
)
from worker.local_vision import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_PROXIMITY_RADIUS,
    LocalVisionEngine,
    RawMatch,
    TemplateModel,
    analyze_canvas_local,
    create_default_icon_assets,
    get_local_vision_engine,
)
from worker.screen_capture import image_to_base64


@pytest.fixture
def temp_icons_dir():
    """Create a temporary directory with generated default icon assets."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        icons_path = Path(tmp_dir) / "icons"
        create_default_icon_assets(icons_path)
        yield icons_path


@pytest.fixture
def local_engine(temp_icons_dir):
    """Instantiate a LocalVisionEngine with temporary test icons."""
    return LocalVisionEngine(
        icons_dir=temp_icons_dir,
        confidence_threshold=0.80,
        proximity_radius=15,
        step=2,
    )


class TestIconAssetsGeneration:
    """Tests for icon asset generation and template loading."""

    def test_create_default_icon_assets(self, temp_icons_dir):
        """Test default icon assets creation."""
        msg_file = temp_icons_dir / "icon_message.png"
        q_file = temp_icons_dir / "icon_question.png"
        c_file = temp_icons_dir / "icon_comment.png"

        assert msg_file.exists() and msg_file.is_file()
        assert q_file.exists() and q_file.is_file()
        assert c_file.exists() and c_file.is_file()

        with Image.open(msg_file) as img:
            assert img.size == (24, 24)
            assert img.mode in ("RGBA", "RGB")

        with Image.open(q_file) as img:
            assert img.size == (24, 24)

        with Image.open(c_file) as img:
            assert img.size == (24, 24)

    def test_load_templates_loads_all_three_types(self, local_engine):
        """Test template loader successfully parses all 3 BlockTypes."""
        templates = local_engine.load_templates()
        assert len(templates) >= 3

        loaded_types = {t.block_type for t in templates}
        assert BlockType.MESSAGE in loaded_types
        assert BlockType.QUESTION in loaded_types
        assert BlockType.COMMENT in loaded_types

    def test_template_model_properties(self, local_engine):
        """Test TemplateModel attributes and preprocessed anchors."""
        for tpl in local_engine.templates:
            assert isinstance(tpl.block_type, BlockType)
            assert tpl.width > 0
            assert tpl.height > 0
            assert tpl.total_opaque > 0
            assert len(tpl.primary_anchor) == 5
            assert tpl.max_diff_sum > 0

    def test_missing_templates_can_be_disabled(self, tmp_path):
        """Test that a missing asset directory is reported without fabrication."""
        engine = LocalVisionEngine(
            icons_dir=tmp_path / "missing-icons",
            auto_create_templates=False,
        )

        assert engine.templates == []
        assert engine.load_templates() == []


class TestLocalVisionDetection:
    """Tests for single and multi-block detection accuracy, normalization, and ordering."""

    def test_detect_single_message_block(self, local_engine, temp_icons_dir):
        """Test accurate detection of a single MESSAGE block."""
        canvas = Image.new("RGB", (800, 600), (245, 245, 245))
        msg_icon = Image.open(temp_icons_dir / "icon_message.png").convert("RGBA")
        canvas.paste(msg_icon, (200, 150), mask=msg_icon.split()[3])

        blocks = local_engine.detect_blocks(canvas)
        assert len(blocks) == 1
        block = blocks[0]
        assert block.type == BlockType.MESSAGE
        assert block.confidence >= 0.85

        # Expected center: x = 200 + 12 = 212, y = 150 + 12 = 162
        # Relative: x = 212/800 = 0.265, y = 162/600 = 0.27
        assert math.isclose(block.relative_x, 0.265, abs_tol=0.01)
        assert math.isclose(block.relative_y, 0.27, abs_tol=0.01)

    def test_detect_single_question_block(self, local_engine, temp_icons_dir):
        """Test accurate detection of a single QUESTION block."""
        canvas = Image.new("RGB", (800, 600), (250, 250, 250))
        q_icon = Image.open(temp_icons_dir / "icon_question.png").convert("RGBA")
        canvas.paste(q_icon, (400, 300), mask=q_icon.split()[3])

        blocks = local_engine.detect_blocks(canvas)
        assert len(blocks) == 1
        block = blocks[0]
        assert block.type == BlockType.QUESTION
        assert block.confidence >= 0.85

        # Expected center: x = 400 + 12 = 412, y = 300 + 12 = 312
        # Relative: x = 412/800 = 0.515, y = 312/600 = 0.52
        assert math.isclose(block.relative_x, 0.515, abs_tol=0.01)
        assert math.isclose(block.relative_y, 0.52, abs_tol=0.01)

    def test_detect_single_comment_block(self, local_engine, temp_icons_dir):
        """Test accurate detection of a single COMMENT block."""
        canvas = Image.new("RGB", (800, 600), (240, 240, 240))
        c_icon = Image.open(temp_icons_dir / "icon_comment.png").convert("RGBA")
        canvas.paste(c_icon, (100, 450), mask=c_icon.split()[3])

        blocks = local_engine.detect_blocks(canvas)
        assert len(blocks) == 1
        block = blocks[0]
        assert block.type == BlockType.COMMENT
        assert block.confidence >= 0.85

        # Expected center: x = 100 + 12 = 112, y = 450 + 12 = 462
        # Relative: x = 112/800 = 0.14, y = 462/600 = 0.77
        assert math.isclose(block.relative_x, 0.14, abs_tol=0.01)
        assert math.isclose(block.relative_y, 0.77, abs_tol=0.01)

    def test_detect_multiple_blocks_and_ordering(self, local_engine, temp_icons_dir):
        """Test detecting multiple blocks across canvas in vertical execution sequence."""
        canvas = Image.new("RGB", (1400, 900), (240, 240, 240))
        msg_icon = Image.open(temp_icons_dir / "icon_message.png").convert("RGBA")
        q_icon = Image.open(temp_icons_dir / "icon_question.png").convert("RGBA")
        c_icon = Image.open(temp_icons_dir / "icon_comment.png").convert("RGBA")

        # Paste in non-sequential order
        # Step 1: Message at top (100, 80)
        canvas.paste(msg_icon, (100, 80), mask=msg_icon.split()[3])
        # Step 4: Message near bottom (700, 600)
        canvas.paste(msg_icon, (700, 600), mask=msg_icon.split()[3])
        # Step 2: Question in upper-middle (500, 250)
        canvas.paste(q_icon, (500, 250), mask=q_icon.split()[3])
        # Step 5: Question at bottom (400, 750)
        canvas.paste(q_icon, (400, 750), mask=q_icon.split()[3])
        # Step 3: Comment in middle (300, 400)
        canvas.paste(c_icon, (300, 400), mask=c_icon.split()[3])

        bbox = CanvasBoundingBox(x=510, y=120, width=1400, height=900)
        blocks = local_engine.detect_blocks(canvas, canvas_bbox=bbox)

        assert len(blocks) == 5

        # Verify sorted order: relative_y increasing (top to bottom)
        for i in range(len(blocks) - 1):
            assert blocks[i].relative_y <= blocks[i + 1].relative_y

        # Verify sequence types
        assert blocks[0].type == BlockType.MESSAGE
        assert blocks[1].type == BlockType.QUESTION
        assert blocks[2].type == BlockType.COMMENT
        assert blocks[3].type == BlockType.MESSAGE
        assert blocks[4].type == BlockType.QUESTION

        # Verify screen coordinate mapping
        # First block: center (112, 92) -> screen (510 + 112, 120 + 92) = (622, 212)
        assert abs(blocks[0].screen_x - 622) <= 2
        assert abs(blocks[0].screen_y - 212) <= 2

    def test_same_row_is_sorted_left_to_right(self, local_engine, temp_icons_dir):
        """Test the secondary X ordering for blocks on the same flow row."""
        canvas = Image.new("RGB", (800, 400), (240, 240, 240))
        msg_icon = Image.open(temp_icons_dir / "icon_message.png").convert("RGBA")
        q_icon = Image.open(temp_icons_dir / "icon_question.png").convert("RGBA")
        canvas.paste(q_icon, (500, 150), mask=q_icon.split()[3])
        canvas.paste(msg_icon, (100, 150), mask=msg_icon.split()[3])

        blocks = local_engine.detect_blocks(canvas)

        assert len(blocks) == 2
        assert blocks[0].relative_x < blocks[1].relative_x
        assert blocks[0].type == BlockType.MESSAGE
        assert blocks[1].type == BlockType.QUESTION

    def test_confidence_threshold_rejects_non_matching_icon(self, local_engine, temp_icons_dir):
        """Test that a heavily altered template does not become a detection."""
        canvas = Image.new("RGB", (600, 400), (240, 240, 240))
        altered = Image.new("RGBA", (24, 24), (255, 0, 255, 255))
        canvas.paste(altered, (200, 150), mask=altered.split()[3])

        blocks = local_engine.detect_blocks(canvas, confidence_threshold=0.95)

        assert blocks == []

    def test_deduplication_proximity_clustering(self, local_engine):
        """Test that raw duplicate/jittered matches within radius are deduplicated."""
        matches = [
            RawMatch(block_type=BlockType.MESSAGE, x=100, y=100, width=24, height=24, confidence=1.0),
            RawMatch(block_type=BlockType.MESSAGE, x=102, y=101, width=24, height=24, confidence=0.92),
            RawMatch(block_type=BlockType.MESSAGE, x=99, y=100, width=24, height=24, confidence=0.88),
            RawMatch(block_type=BlockType.QUESTION, x=300, y=300, width=24, height=24, confidence=0.95),
            RawMatch(block_type=BlockType.QUESTION, x=301, y=301, width=24, height=24, confidence=0.91),
        ]

        deduped = local_engine.deduplicate_matches(matches, proximity_radius=15)
        assert len(deduped) == 2
        assert deduped[0].block_type == BlockType.MESSAGE
        assert deduped[0].confidence == 1.0
        assert deduped[1].block_type == BlockType.QUESTION
        assert deduped[1].confidence == 0.95

    def test_empty_canvas_returns_no_blocks(self, local_engine):
        """Test that a blank canvas produces an empty detection list."""
        canvas = Image.new("RGB", (1000, 800), (240, 240, 240))
        blocks = local_engine.detect_blocks(canvas)
        assert blocks == []

    def test_canvas_with_noise_and_lines(self, local_engine, temp_icons_dir):
        """Test detection resilience in presence of diagram grid lines and noise."""
        canvas = Image.new("RGB", (1000, 800), (245, 245, 245))
        d = ImageDraw.Draw(canvas)

        # Draw grid and connector lines
        for y in range(0, 800, 50):
            d.line([(0, y), (1000, y)], fill=(220, 220, 220), width=1)
        for x in range(0, 1000, 50):
            d.line([(x, 0), (x, 800)], fill=(220, 220, 220), width=1)

        # Draw diagonal connector arrow
        d.line([(100, 100), (500, 500)], fill=(100, 100, 100), width=2)

        # Paste target icons
        msg_icon = Image.open(temp_icons_dir / "icon_message.png").convert("RGBA")
        q_icon = Image.open(temp_icons_dir / "icon_question.png").convert("RGBA")

        canvas.paste(msg_icon, (200, 200), mask=msg_icon.split()[3])
        canvas.paste(q_icon, (600, 400), mask=q_icon.split()[3])

        blocks = local_engine.detect_blocks(canvas)
        assert len(blocks) == 2
        assert blocks[0].type == BlockType.MESSAGE
        assert blocks[1].type == BlockType.QUESTION


class TestInputFormatsAndAPI:
    """Tests for input conversion (base64, bytes, Image) and API response compatibility."""

    def test_detect_blocks_from_base64_string(self, local_engine, temp_icons_dir):
        """Test accepting base64 encoded screenshot string."""
        canvas = Image.new("RGB", (600, 400), (255, 255, 255))
        msg_icon = Image.open(temp_icons_dir / "icon_message.png").convert("RGBA")
        canvas.paste(msg_icon, (150, 100), mask=msg_icon.split()[3])

        b64_str = image_to_base64(canvas)
        blocks = local_engine.detect_blocks(b64_str)
        assert len(blocks) == 1
        assert blocks[0].type == BlockType.MESSAGE

    def test_detect_blocks_from_bytes(self, local_engine, temp_icons_dir):
        """Test accepting raw bytes image data."""
        canvas = Image.new("RGB", (600, 400), (255, 255, 255))
        c_icon = Image.open(temp_icons_dir / "icon_comment.png").convert("RGBA")
        canvas.paste(c_icon, (150, 100), mask=c_icon.split()[3])

        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        raw_bytes = buf.getvalue()

        blocks = local_engine.detect_blocks(raw_bytes)
        assert len(blocks) == 1
        assert blocks[0].type == BlockType.COMMENT

    def test_analyze_canvas_response_structure(self, local_engine, temp_icons_dir):
        """Test analyze_canvas returns compliant CanvasAnalysisResponse."""
        canvas = Image.new("RGB", (800, 600), (240, 240, 240))
        q_icon = Image.open(temp_icons_dir / "icon_question.png").convert("RGBA")
        canvas.paste(q_icon, (300, 200), mask=q_icon.split()[3])

        bbox = CanvasBoundingBox(x=100, y=50, width=800, height=600)
        resp = local_engine.analyze_canvas(canvas, canvas_bbox=bbox, task_id="TEST_GFF_01")

        assert isinstance(resp, CanvasAnalysisResponse)
        assert resp.task_id == "TEST_GFF_01"
        assert resp.total_detected == 1
        assert resp.execution_time_seconds is not None
        assert resp.execution_time_seconds >= 0.0
        assert len(resp.blocks) == 1
        assert resp.blocks[0].type == BlockType.QUESTION
        assert resp.blocks[0].screen_x is not None
        assert resp.blocks[0].screen_y is not None

    def test_invalid_image_input_raises_value_error(self, local_engine):
        """Test that invalid image inputs raise ValueError."""
        with pytest.raises(ValueError):
            local_engine.detect_blocks(12345)  # Invalid type

        with pytest.raises(ValueError):
            local_engine.detect_blocks("invalid_not_base64_string")

    def test_convenience_functions(self, temp_icons_dir):
        """Test get_local_vision_engine and analyze_canvas_local helpers."""
        engine = get_local_vision_engine(icons_dir=temp_icons_dir)
        assert isinstance(engine, LocalVisionEngine)

        canvas = Image.new("RGB", (400, 300), (240, 240, 240))
        resp = analyze_canvas_local(canvas, task_id="CONV_TEST")
        assert isinstance(resp, CanvasAnalysisResponse)
        assert resp.task_id == "CONV_TEST"
