"""Unit tests for high-precision Screen Capture and Base64 Streaming (TASK-007)."""

import base64
import io
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch
import pytest
from PIL import Image, ImageDraw

from controller.config import Settings
from controller.vision_engine import CanvasBoundingBox
from worker.screen_capture import (
    ScreenCapture,
    ScreenRegion,
    base64_to_image,
    capture_as_base64,
    capture_canvas,
    capture_full_screen,
    capture_region,
    enable_dpi_awareness,
    get_screen_capture,
    image_to_base64,
    normalize_region,
    save_screenshot,
)


def _create_mock_image(width: int = 1920, height: int = 1080, color: str = "blue") -> Image.Image:
    """Helper to create a synthetic PIL Image for testing."""
    img = Image.new("RGB", (width, height), color=color)
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 100, 100], fill="red")
    return img


# ---------------------------------------------------------------------------
# Test ScreenRegion Model
# ---------------------------------------------------------------------------

class TestScreenRegion:
    """Tests for ScreenRegion model and conversion helpers."""

    def test_screen_region_creation(self):
        region = ScreenRegion(x=100, y=200, width=800, height=600)
        assert region.x == 100
        assert region.y == 200
        assert region.width == 800
        assert region.height == 600
        assert region.left == 100
        assert region.top == 200
        assert region.right == 900
        assert region.bottom == 800

    def test_to_bbox_tuple(self):
        region = ScreenRegion(x=50, y=60, width=500, height=400)
        assert region.to_bbox_tuple() == (50, 60, 550, 460)

    def test_to_dict(self):
        region = ScreenRegion(x=10, y=20, width=300, height=200)
        assert region.to_dict() == {"x": 10, "y": 20, "width": 300, "height": 200}

    def test_to_canvas_bbox(self):
        region = ScreenRegion(x=510, y=120, width=1400, height=900)
        canvas_bbox = region.to_canvas_bbox()
        assert isinstance(canvas_bbox, CanvasBoundingBox)
        assert canvas_bbox.x == 510
        assert canvas_bbox.y == 120
        assert canvas_bbox.width == 1400
        assert canvas_bbox.height == 900

    def test_from_canvas_bbox(self):
        c_bbox = CanvasBoundingBox(x=510, y=120, width=1400, height=900)
        region = ScreenRegion.from_canvas_bbox(c_bbox)
        assert region.x == 510
        assert region.y == 120
        assert region.width == 1400
        assert region.height == 900

    def test_from_tuple_xywh_mode(self):
        region = ScreenRegion.from_tuple((100, 150, 800, 600), mode="xywh")
        assert region.x == 100
        assert region.y == 150
        assert region.width == 800
        assert region.height == 600

    def test_from_tuple_ltrb_mode(self):
        region = ScreenRegion.from_tuple((100, 150, 900, 750), mode="ltrb")
        assert region.x == 100
        assert region.y == 150
        assert region.width == 800
        assert region.height == 600

    def test_from_dict_xywh(self):
        data = {"x": 50, "y": 70, "width": 640, "height": 480}
        region = ScreenRegion.from_dict(data)
        assert region.x == 50
        assert region.y == 70
        assert region.width == 640
        assert region.height == 480

    def test_from_dict_ltrb(self):
        data = {"left": 50, "top": 70, "right": 690, "bottom": 550}
        region = ScreenRegion.from_dict(data)
        assert region.x == 50
        assert region.y == 70
        assert region.width == 640
        assert region.height == 480

    def test_from_dict_invalid_raises(self):
        with pytest.raises(ValueError):
            ScreenRegion.from_dict({"foo": 123})

    def test_invalid_dimensions_raise_validation_error(self):
        with pytest.raises(Exception):
            ScreenRegion(width=0, height=100)
        with pytest.raises(Exception):
            ScreenRegion(width=100, height=-5)
        with pytest.raises(Exception):
            ScreenRegion(x=-10, y=0, width=100, height=100)


# ---------------------------------------------------------------------------
# Test normalize_region
# ---------------------------------------------------------------------------

class TestNormalizeRegion:
    """Tests for the normalize_region function."""

    def test_normalize_none_returns_none(self):
        assert normalize_region(None) is None

    def test_normalize_screen_region(self):
        reg = ScreenRegion(x=10, y=20, width=100, height=200)
        assert normalize_region(reg) is reg

    def test_normalize_canvas_bounding_box(self):
        c_bbox = CanvasBoundingBox(x=100, y=200, width=500, height=400)
        norm = normalize_region(c_bbox)
        assert isinstance(norm, ScreenRegion)
        assert norm.x == 100
        assert norm.y == 200
        assert norm.width == 500
        assert norm.height == 400

    def test_normalize_tuple(self):
        norm = normalize_region((10, 20, 300, 400), mode="xywh")
        assert norm.x == 10
        assert norm.width == 300

    def test_normalize_dict(self):
        norm = normalize_region({"x": 10, "y": 20, "width": 300, "height": 400})
        assert norm.x == 10
        assert norm.width == 300

    def test_normalize_invalid_type_raises(self):
        with pytest.raises(ValueError):
            normalize_region("invalid_string_region")


# ---------------------------------------------------------------------------
# Test Base64 Encoding & Decoding
# ---------------------------------------------------------------------------

class TestBase64Conversions:
    """Tests for image Base64 encoding, decoding, and round-tripping."""

    def test_image_to_base64_with_data_uri(self):
        img = _create_mock_image(100, 100, color="green")
        b64 = image_to_base64(img, format="PNG", include_data_uri=True)
        assert b64.startswith("data:image/png;base64,")
        assert len(b64) > 30

    def test_image_to_base64_without_data_uri(self):
        img = _create_mock_image(100, 100, color="green")
        b64 = image_to_base64(img, format="PNG", include_data_uri=False)
        assert not b64.startswith("data:")
        # Verify it decodes cleanly as base64 bytes
        decoded_bytes = base64.b64decode(b64)
        assert len(decoded_bytes) > 0

    def test_image_to_base64_jpeg_format(self):
        # Create RGBA image to test alpha channel flattening for JPEG
        img_rgba = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
        b64_jpg = image_to_base64(img_rgba, format="JPEG", include_data_uri=True)
        assert b64_jpg.startswith("data:image/jpeg;base64,")

    def test_base64_to_image_roundtrip_with_data_uri(self):
        original = _create_mock_image(200, 150, color="yellow")
        b64_str = image_to_base64(original, format="PNG", include_data_uri=True)

        decoded = base64_to_image(b64_str)
        assert isinstance(decoded, Image.Image)
        assert decoded.width == 200
        assert decoded.height == 150

    def test_base64_to_image_roundtrip_without_data_uri(self):
        original = _create_mock_image(120, 80, color="cyan")
        b64_str = image_to_base64(original, format="PNG", include_data_uri=False)

        decoded = base64_to_image(b64_str)
        assert isinstance(decoded, Image.Image)
        assert decoded.width == 120
        assert decoded.height == 80

    def test_base64_to_image_invalid_string_raises(self):
        with pytest.raises(ValueError):
            base64_to_image("")
        with pytest.raises(ValueError):
            base64_to_image("this_is_not_valid_base64_image_data_!")
        with pytest.raises(ValueError):
            base64_to_image(None)


# ---------------------------------------------------------------------------
# Test DPI Awareness
# ---------------------------------------------------------------------------

class TestDpiAwareness:
    """Tests for Windows DPI awareness helper."""

    def test_enable_dpi_awareness_non_windows(self):
        with patch("sys.platform", "linux"):
            assert enable_dpi_awareness() is False

    def test_enable_dpi_awareness_windows_shcore_success(self):
        with patch("sys.platform", "win32"), patch("ctypes.windll") as mock_windll:
            mock_windll.shcore.SetProcessDpiAwareness.return_value = 0
            res = enable_dpi_awareness()
            assert res is True
            mock_windll.shcore.SetProcessDpiAwareness.assert_called_once_with(2)

    def test_enable_dpi_awareness_windows_fallback_user32(self):
        with patch("sys.platform", "win32"), patch("ctypes.windll") as mock_windll:
            # shcore throws AttributeError/Exception
            del mock_windll.shcore.SetProcessDpiAwareness
            mock_windll.user32.SetProcessDPIAware.return_value = 1
            res = enable_dpi_awareness()
            assert res is True
            mock_windll.user32.SetProcessDPIAware.assert_called_once()


# ---------------------------------------------------------------------------
# Test ScreenCapture Class & Methods
# ---------------------------------------------------------------------------

class TestScreenCaptureClass:
    """Tests for ScreenCapture driver and capture methods."""

    def setup_method(self):
        self.mock_full_img = _create_mock_image(1920, 1080, color="gray")
        self.mock_grab_fn = MagicMock(return_value=self.mock_full_img)
        self.sc = ScreenCapture(grab_fn=self.mock_grab_fn, enable_dpi=False)

    def test_capture_full_screen(self):
        img = self.sc.capture_full_screen()
        assert img == self.mock_full_img
        self.mock_grab_fn.assert_called_once()

    def test_get_screen_size(self):
        w, h = self.sc.get_screen_size()
        assert w == 1920
        assert h == 1080

    def test_capture_region_with_direct_bbox_support(self):
        mock_region_img = _create_mock_image(400, 300, color="red")
        self.mock_grab_fn.return_value = mock_region_img

        reg = ScreenRegion(x=100, y=100, width=400, height=300)
        result = self.sc.capture_region(reg)

        assert result == mock_region_img
        self.mock_grab_fn.assert_called_with(bbox=(100, 100, 500, 400))

    def test_capture_region_fallback_crop_on_type_error(self):
        def fake_grab(bbox=None, **kwargs):
            if bbox is not None:
                raise TypeError("Custom grabber does not accept bbox")
            return self.mock_full_img

        sc = ScreenCapture(grab_fn=fake_grab, enable_dpi=False)
        reg = ScreenRegion(x=100, y=100, width=400, height=300)
        result = sc.capture_region(reg)

        assert isinstance(result, Image.Image)
        assert result.width == 400
        assert result.height == 300

    def test_capture_canvas(self):
        c_bbox = CanvasBoundingBox(x=510, y=120, width=1400, height=900)
        mock_canvas_img = _create_mock_image(1400, 900, color="white")
        self.mock_grab_fn.return_value = mock_canvas_img

        result = self.sc.capture_canvas(c_bbox)
        assert result == mock_canvas_img
        self.mock_grab_fn.assert_called_with(bbox=(510, 120, 1910, 1020))

    def test_capture_as_base64_full_screen(self):
        b64_str = self.sc.capture_as_base64()
        assert b64_str.startswith("data:image/png;base64,")

    def test_capture_as_base64_region(self):
        mock_region_img = _create_mock_image(500, 400, color="blue")
        self.mock_grab_fn.return_value = mock_region_img

        reg = ScreenRegion(x=50, y=50, width=500, height=400)
        b64_str = self.sc.capture_as_base64(region=reg, include_data_uri=False)
        assert not b64_str.startswith("data:")
        decoded = base64_to_image(b64_str)
        assert decoded.width == 500
        assert decoded.height == 400

    def test_save_screenshot(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dest = Path(tmp_dir) / "subfolder" / "test_capture.png"
            img = _create_mock_image(200, 200, color="purple")
            saved_path = self.sc.save_screenshot(img, dest)

            assert saved_path.exists()
            with Image.open(saved_path) as loaded_img:
                assert loaded_img.size == (200, 200)

    def test_capture_and_save(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dest = Path(tmp_dir) / "output.png"
            saved_path = self.sc.capture_and_save(dest)
            assert saved_path.exists()


# ---------------------------------------------------------------------------
# Test Standalone Convenience Functions
# ---------------------------------------------------------------------------

class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_convenience_functions_execute(self):
        mock_img = _create_mock_image(800, 600, color="orange")
        with patch.object(ScreenCapture, "capture_full_screen", return_value=mock_img), \
             patch.object(ScreenCapture, "capture_region", return_value=mock_img):
            
            assert capture_full_screen() == mock_img
            assert capture_region(ScreenRegion(x=0, y=0, width=100, height=100)) == mock_img
            assert capture_canvas(CanvasBoundingBox(x=0, y=0, width=100, height=100)) == mock_img
            
            b64 = capture_as_base64()
            assert b64.startswith("data:image/png;base64,")

    def test_get_screen_capture_singleton(self):
        inst1 = get_screen_capture()
        inst2 = get_screen_capture()
        assert inst1 is inst2
