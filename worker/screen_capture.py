"""High-precision screen capture module for ODIS Obliterator Worker (TASK-007).

Provides selective bounding box capture, in-memory PIL Image generation,
Base64 encoding/decoding for Controller API payloads, multi-monitor and DPI awareness.
"""

import base64
import ctypes
import io
import logging
import os
from pathlib import Path
import sys
from typing import Any, Callable, Dict, Optional, Tuple, Union
from PIL import Image, ImageGrab
from pydantic import BaseModel, Field, field_validator

from controller.config import Settings, get_settings
from controller.vision_engine import CanvasBoundingBox

logger = logging.getLogger(__name__)


def enable_dpi_awareness() -> bool:
    """Enable per-monitor DPI awareness on Windows to avoid screenshot scaling discrepancies.

    Returns:
        bool: True if DPI awareness was successfully configured, False otherwise.
    """
    if sys.platform != "win32":
        return False

    try:
        # Try Windows 8.1+ SetProcessDpiAwareness (PROCESS_PER_MONITOR_DPI_AWARE = 2)
        shcore = ctypes.windll.shcore
        if hasattr(shcore, "SetProcessDpiAwareness"):
            res = shcore.SetProcessDpiAwareness(2)
            logger.debug(f"SetProcessDpiAwareness(2) returned: {res}")
            return True
    except Exception as exc:
        logger.debug(f"SetProcessDpiAwareness failed: {exc}")

    try:
        # Fallback to Windows Vista+ SetProcessDPIAware
        user32 = ctypes.windll.user32
        if hasattr(user32, "SetProcessDPIAware"):
            res = user32.SetProcessDPIAware()
            logger.debug(f"SetProcessDPIAware() returned: {res}")
            return bool(res)
    except Exception as exc:
        logger.debug(f"SetProcessDPIAware fallback failed: {exc}")

    return False


class ScreenRegion(BaseModel):
    """Represents a screen region bounding box for selective captures."""

    x: int = Field(default=0, ge=0, description="Left X coordinate in screen pixels.")
    y: int = Field(default=0, ge=0, description="Top Y coordinate in screen pixels.")
    width: int = Field(..., gt=0, description="Width of region in screen pixels.")
    height: int = Field(..., gt=0, description="Height of region in screen pixels.")

    @property
    def left(self) -> int:
        """Left edge X coordinate."""
        return self.x

    @property
    def top(self) -> int:
        """Top edge Y coordinate."""
        return self.y

    @property
    def right(self) -> int:
        """Right edge X coordinate."""
        return self.x + self.width

    @property
    def bottom(self) -> int:
        """Bottom edge Y coordinate."""
        return self.y + self.height

    def to_bbox_tuple(self) -> Tuple[int, int, int, int]:
        """Convert to (left, top, right, bottom) tuple format for PIL ImageGrab."""
        return (self.left, self.top, self.right, self.bottom)

    def to_dict(self) -> Dict[str, int]:
        """Convert to standard dictionary format."""
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}

    def to_canvas_bbox(self) -> CanvasBoundingBox:
        """Convert to CanvasBoundingBox instance."""
        return CanvasBoundingBox(x=self.x, y=self.y, width=self.width, height=self.height)

    @classmethod
    def from_canvas_bbox(cls, bbox: CanvasBoundingBox) -> "ScreenRegion":
        """Create ScreenRegion from CanvasBoundingBox."""
        return cls(x=bbox.x, y=bbox.y, width=bbox.width, height=bbox.height)

    @classmethod
    def from_tuple(
        cls,
        coords: Tuple[int, int, int, int],
        mode: str = "xywh",
    ) -> "ScreenRegion":
        """Create ScreenRegion from a 4-integer tuple.

        Args:
            coords: Tuple of 4 integers.
            mode: 'xywh' for (x, y, width, height) or 'ltrb' for (left, top, right, bottom).

        Returns:
            ScreenRegion instance.
        """
        c1, c2, c3, c4 = coords
        if mode.lower() == "ltrb":
            return cls(x=c1, y=c2, width=max(1, c3 - c1), height=max(1, c4 - c2))
        return cls(x=c1, y=c2, width=c3, height=c4)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScreenRegion":
        """Create ScreenRegion from a dictionary."""
        if "width" in data and "height" in data:
            return cls(
                x=int(data.get("x", 0)),
                y=int(data.get("y", 0)),
                width=int(data["width"]),
                height=int(data["height"]),
            )
        if "left" in data and "right" in data and "top" in data and "bottom" in data:
            left = int(data["left"])
            top = int(data["top"])
            right = int(data["right"])
            bottom = int(data["bottom"])
            return cls(x=left, y=top, width=max(1, right - left), height=max(1, bottom - top))
        raise ValueError(f"Unrecognized region dictionary format: {data}")


def normalize_region(
    region: Optional[Union[ScreenRegion, CanvasBoundingBox, Tuple[int, int, int, int], Dict[str, Any]]],
    mode: str = "xywh",
) -> Optional[ScreenRegion]:
    """Normalize various bounding box representations into a canonical ScreenRegion.

    Args:
        region: Region as ScreenRegion, CanvasBoundingBox, tuple, or dict, or None.
        mode: Tuple interpretation mode ('xywh' or 'ltrb').

    Returns:
        ScreenRegion instance or None if input was None.
    """
    if region is None:
        return None
    if isinstance(region, ScreenRegion):
        return region
    if isinstance(region, CanvasBoundingBox):
        return ScreenRegion.from_canvas_bbox(region)
    if isinstance(region, (tuple, list)) and len(region) == 4:
        return ScreenRegion.from_tuple(tuple(region), mode=mode)
    if isinstance(region, dict):
        return ScreenRegion.from_dict(region)
    raise ValueError(f"Unsupported region type: {type(region)}")


def image_to_base64(
    image: Image.Image,
    format: str = "PNG",
    include_data_uri: bool = True,
) -> str:
    """Encode a PIL Image to a Base64 string.

    Args:
        image: PIL Image object.
        format: Image format (e.g. 'PNG', 'JPEG'). Defaults to 'PNG'.
        include_data_uri: If True, prefixes with 'data:image/{format};base64,'.

    Returns:
        Base64-encoded string.
    """
    buffered = io.BytesIO()
    fmt = format.upper()
    if fmt == "JPG":
        fmt = "JPEG"

    # Convert RGBA to RGB if saving as JPEG
    if fmt == "JPEG" and image.mode in ("RGBA", "LA", "P"):
        rgb_image = Image.new("RGB", image.size, (255, 255, 255))
        if image.mode == "RGBA":
            rgb_image.paste(image, mask=image.split()[-1])
        else:
            rgb_image.paste(image.convert("RGB"))
        rgb_image.save(buffered, format=fmt, quality=95)
    else:
        image.save(buffered, format=fmt)

    encoded = base64.b64encode(buffered.getvalue()).decode("utf-8")
    if include_data_uri:
        mime = f"image/{fmt.lower()}"
        return f"data:{mime};base64,{encoded}"
    return encoded


def base64_to_image(image_base64: str) -> Image.Image:
    """Decode a Base64 string (with or without data URI header) to a PIL Image.

    Args:
        image_base64: Base64-encoded image string.

    Returns:
        PIL Image object.

    Raises:
        ValueError: If base64 string is invalid or cannot be decoded as image.
    """
    if not image_base64 or not isinstance(image_base64, str):
        raise ValueError("Invalid or empty image_base64 string.")

    raw_data = image_base64.strip()
    if "," in raw_data and raw_data.startswith("data:"):
        _, raw_data = raw_data.split(",", 1)

    try:
        decoded = base64.b64decode(raw_data)
        return Image.open(io.BytesIO(decoded))
    except Exception as exc:
        raise ValueError(f"Failed to decode image from Base64: {exc}") from exc


class ScreenCapture:
    """High-precision screen capture driver with ROI cropping and Base64 streaming."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        grab_fn: Optional[Callable[..., Image.Image]] = None,
        enable_dpi: bool = True,
    ):
        """Initialize ScreenCapture instance.

        Args:
            settings: Optional Settings instance.
            grab_fn: Optional custom screen grabber function (for mocking/testing).
                     Defaults to PIL.ImageGrab.grab.
            enable_dpi: Whether to automatically configure Windows DPI awareness.
        """
        self.settings = settings or get_settings()
        self._grab_fn = grab_fn or ImageGrab.grab
        if enable_dpi:
            enable_dpi_awareness()

    def get_screen_size(self) -> Tuple[int, int]:
        """Get the full primary screen resolution in pixels.

        Returns:
            Tuple of (width, height) integers.
        """
        full_img = self.capture_full_screen()
        return (full_img.width, full_img.height)

    def capture_full_screen(self, all_screens: bool = False) -> Image.Image:
        """Capture the entire screen.

        Args:
            all_screens: Whether to capture all monitors on Windows (if supported).

        Returns:
            PIL Image object of the full screen.
        """
        try:
            if sys.platform == "win32" and all_screens:
                return self._grab_fn(all_screens=True)
            return self._grab_fn()
        except TypeError:
            # In case custom grab_fn or platform does not accept all_screens argument
            return self._grab_fn()
        except Exception as exc:
            logger.error(f"Full screen capture failed: {exc}")
            raise RuntimeError(f"Failed to capture screen: {exc}") from exc

    def capture_region(
        self,
        region: Union[ScreenRegion, CanvasBoundingBox, Tuple[int, int, int, int], Dict[str, Any]],
        mode: str = "xywh",
    ) -> Image.Image:
        """Capture a specific bounding box region of the screen.

        Args:
            region: Bounding box region.
            mode: Tuple mode ('xywh' or 'ltrb') if region is a tuple.

        Returns:
            PIL Image cropped to the bounding box.
        """
        norm_region = normalize_region(region, mode=mode)
        if norm_region is None:
            return self.capture_full_screen()

        bbox_tuple = norm_region.to_bbox_tuple()
        try:
            # ImageGrab.grab accepts bbox=(left, top, right, bottom)
            return self._grab_fn(bbox=bbox_tuple)
        except TypeError:
            # If grab_fn doesn't support bbox kwarg, grab full and crop
            full_screen = self.capture_full_screen()
            return full_screen.crop(bbox_tuple)
        except Exception as exc:
            # Fallback: capture full and crop manually
            logger.debug(f"Direct bbox grab failed ({exc}), falling back to full capture + crop.")
            full_screen = self.capture_full_screen()
            return full_screen.crop(bbox_tuple)

    def capture_canvas(
        self,
        canvas_bbox: Union[CanvasBoundingBox, ScreenRegion, Dict[str, Any], Tuple[int, int, int, int]],
    ) -> Image.Image:
        """Capture the ODIS Creator flowchart canvas area.

        Args:
            canvas_bbox: Canvas bounding box definition.

        Returns:
            PIL Image of the canvas area.
        """
        return self.capture_region(canvas_bbox)

    def capture_as_base64(
        self,
        region: Optional[Union[ScreenRegion, CanvasBoundingBox, Tuple[int, int, int, int], Dict[str, Any]]] = None,
        format: str = "PNG",
        include_data_uri: bool = True,
    ) -> str:
        """Capture screen or region and return as Base64-encoded string.

        Args:
            region: Optional region to capture (full screen if None).
            format: Image format ('PNG', 'JPEG'). Defaults to 'PNG'.
            include_data_uri: Whether to include data URI prefix.

        Returns:
            Base64 encoded image string.
        """
        if region is None:
            img = self.capture_full_screen()
        else:
            img = self.capture_region(region)

        return image_to_base64(img, format=format, include_data_uri=include_data_uri)

    def save_screenshot(
        self,
        image: Image.Image,
        filepath: Union[str, Path],
        format: str = "PNG",
    ) -> Path:
        """Save a PIL Image screenshot to disk.

        Args:
            image: PIL Image to save.
            filepath: Destination file path.
            format: Image format. Defaults to 'PNG'.

        Returns:
            Resolved Path of saved file.
        """
        path = Path(filepath).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(str(path), format=format)
        logger.debug(f"Saved screenshot to: {path}")
        return path

    def capture_and_save(
        self,
        filepath: Union[str, Path],
        region: Optional[Union[ScreenRegion, CanvasBoundingBox, Tuple[int, int, int, int], Dict[str, Any]]] = None,
        format: str = "PNG",
    ) -> Path:
        """Capture screen/region and save directly to disk.

        Args:
            filepath: Destination file path.
            region: Optional region bounding box.
            format: Image format. Defaults to 'PNG'.

        Returns:
            Path of saved screenshot file.
        """
        if region is None:
            img = self.capture_full_screen()
        else:
            img = self.capture_region(region)

        return self.save_screenshot(img, filepath=filepath, format=format)


# Global default instance
_default_screen_capture: Optional[ScreenCapture] = None


def get_screen_capture() -> ScreenCapture:
    """Return singleton ScreenCapture instance."""
    global _default_screen_capture
    if _default_screen_capture is None:
        _default_screen_capture = ScreenCapture()
    return _default_screen_capture


def capture_full_screen(all_screens: bool = False) -> Image.Image:
    """Convenience function to capture full screen using default ScreenCapture."""
    return get_screen_capture().capture_full_screen(all_screens=all_screens)


def capture_region(
    region: Union[ScreenRegion, CanvasBoundingBox, Tuple[int, int, int, int], Dict[str, Any]],
    mode: str = "xywh",
) -> Image.Image:
    """Convenience function to capture screen region using default ScreenCapture."""
    return get_screen_capture().capture_region(region, mode=mode)


def capture_canvas(
    canvas_bbox: Union[CanvasBoundingBox, ScreenRegion, Dict[str, Any], Tuple[int, int, int, int]],
) -> Image.Image:
    """Convenience function to capture canvas using default ScreenCapture."""
    return get_screen_capture().capture_canvas(canvas_bbox)


def capture_as_base64(
    region: Optional[Union[ScreenRegion, CanvasBoundingBox, Tuple[int, int, int, int], Dict[str, Any]]] = None,
    format: str = "PNG",
    include_data_uri: bool = True,
) -> str:
    """Convenience function to capture screen/region as Base64 string."""
    return get_screen_capture().capture_as_base64(
        region=region,
        format=format,
        include_data_uri=include_data_uri,
    )


def save_screenshot(
    image: Image.Image,
    filepath: Union[str, Path],
    format: str = "PNG",
) -> Path:
    """Convenience function to save screenshot to disk."""
    return get_screen_capture().save_screenshot(image, filepath=filepath, format=format)
