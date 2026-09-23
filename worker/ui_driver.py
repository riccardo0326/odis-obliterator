"""UI Automation Driver for ODIS Obliterator Worker (TASK-007).

Provides mouse and keyboard interaction primitives (click, double click, right click,
relative coordinate mapping, text input, clipboard paste, hotkeys, and window management).
Supports dry-run simulation and action history auditing.
"""

import ctypes
from datetime import datetime, timezone
from enum import Enum
import logging
import re
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from PIL import Image
import pyautogui
import pyperclip
from pydantic import BaseModel, Field

from controller.config import Settings, get_settings
from controller.vision_engine import CanvasBoundingBox
from worker.screen_capture import ScreenRegion, normalize_region

logger = logging.getLogger(__name__)

# Configure PyAutoGUI safe defaults
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05


class UIActionType(str, Enum):
    """Categorized UI action types."""

    CLICK = "CLICK"
    DOUBLE_CLICK = "DOUBLE_CLICK"
    RIGHT_CLICK = "RIGHT_CLICK"
    MIDDLE_CLICK = "MIDDLE_CLICK"
    MOVE_TO = "MOVE_TO"
    DRAG_TO = "DRAG_TO"
    MOUSE_DOWN = "MOUSE_DOWN"
    MOUSE_UP = "MOUSE_UP"
    SCROLL = "SCROLL"
    TYPE_TEXT = "TYPE_TEXT"
    PASTE_TEXT = "PASTE_TEXT"
    CLEAR_TEXT = "CLEAR_TEXT"
    CLEAR_AND_TYPE = "CLEAR_AND_TYPE"
    PRESS_KEY = "PRESS_KEY"
    KEY_DOWN = "KEY_DOWN"
    KEY_UP = "KEY_UP"
    HOTKEY = "HOTKEY"
    WAIT = "WAIT"
    FOCUS_WINDOW = "FOCUS_WINDOW"
    MAXIMIZE_WINDOW = "MAXIMIZE_WINDOW"


class UIActionRecord(BaseModel):
    """Record of an executed UI action for telemetry and verification."""

    action_type: UIActionType = Field(..., description="Type of UI action executed.")
    params: Dict[str, Any] = Field(default_factory=dict, description="Action arguments and coordinates.")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO timestamp when the action took place.",
    )
    dry_run: bool = Field(default=False, description="Whether the action was simulated in dry-run mode.")


class BackendAdapter:
    """Interface adapter wrapping underlying GUI libraries (PyAutoGUI, win32, clipboard)."""

    def __init__(self, pyautogui_module: Any = pyautogui, clipboard_module: Any = pyperclip):
        self._pyautogui = pyautogui_module
        self._clipboard = clipboard_module

    def click(self, x: Optional[int] = None, y: Optional[int] = None, button: str = "left", clicks: int = 1, interval: float = 0.0) -> None:
        if x is not None and y is not None:
            self._pyautogui.click(x=x, y=y, clicks=clicks, interval=interval, button=button)
        else:
            self._pyautogui.click(clicks=clicks, interval=interval, button=button)

    def double_click(self, x: Optional[int] = None, y: Optional[int] = None, interval: float = 0.1, button: str = "left") -> None:
        if x is not None and y is not None:
            self._pyautogui.doubleClick(x=x, y=y, interval=interval, button=button)
        else:
            self._pyautogui.doubleClick(interval=interval, button=button)

    def right_click(self, x: Optional[int] = None, y: Optional[int] = None) -> None:
        if x is not None and y is not None:
            self._pyautogui.rightClick(x=x, y=y)
        else:
            self._pyautogui.rightClick()

    def middle_click(self, x: Optional[int] = None, y: Optional[int] = None) -> None:
        if x is not None and y is not None:
            self._pyautogui.middleClick(x=x, y=y)
        else:
            self._pyautogui.middleClick()

    def move_to(self, x: int, y: int, duration: float = 0.0) -> None:
        self._pyautogui.moveTo(x=x, y=y, duration=duration)

    def drag_to(self, x: int, y: int, duration: float = 0.2, button: str = "left") -> None:
        self._pyautogui.dragTo(x=x, y=y, duration=duration, button=button)

    def mouse_down(self, x: Optional[int] = None, y: Optional[int] = None, button: str = "left") -> None:
        if x is not None and y is not None:
            self._pyautogui.mouseDown(x=x, y=y, button=button)
        else:
            self._pyautogui.mouseDown(button=button)

    def mouse_up(self, x: Optional[int] = None, y: Optional[int] = None, button: str = "left") -> None:
        if x is not None and y is not None:
            self._pyautogui.mouseUp(x=x, y=y, button=button)
        else:
            self._pyautogui.mouseUp(button=button)

    def scroll(self, clicks: int, x: Optional[int] = None, y: Optional[int] = None) -> None:
        if x is not None and y is not None:
            self._pyautogui.scroll(clicks, x=x, y=y)
        else:
            self._pyautogui.scroll(clicks)

    def type_text(self, text: str, interval: float = 0.0) -> None:
        self._pyautogui.typewrite(text, interval=interval)

    def paste_text(self, text: str) -> None:
        self._clipboard.copy(text)
        time.sleep(0.05)
        self.hotkey("ctrl", "v")

    def press_key(self, key: str, presses: int = 1, interval: float = 0.0) -> None:
        self._pyautogui.press(key, presses=presses, interval=interval)

    def key_down(self, key: str) -> None:
        self._pyautogui.keyDown(key)

    def key_up(self, key: str) -> None:
        self._pyautogui.keyUp(key)

    def hotkey(self, *keys: str, interval: float = 0.0) -> None:
        self._pyautogui.hotkey(*keys, interval=interval)

    def get_mouse_position(self) -> Tuple[int, int]:
        pos = self._pyautogui.position()
        return (int(pos[0]), int(pos[1]))


class UIDriver:
    """High-level Windows UI automation driver for ODIS Creator interactions."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        dry_run: Optional[bool] = None,
        action_delay: Optional[float] = None,
        backend: Optional[BackendAdapter] = None,
    ):
        """Initialize UIDriver.

        Args:
            settings: Optional Settings instance.
            dry_run: Force dry-run mode (if None, reads from settings.dry_run).
            action_delay: Delay in seconds after actions (if None, reads from settings.action_delay).
            backend: Optional BackendAdapter for dependency injection / mocking.
        """
        self.settings = settings or get_settings()
        self.dry_run = dry_run if dry_run is not None else self.settings.dry_run
        self.action_delay = action_delay if action_delay is not None else self.settings.action_delay
        self.backend = backend or BackendAdapter()
        self.action_history: List[UIActionRecord] = []

    def _record(self, action_type: UIActionType, params: Dict[str, Any]) -> None:
        """Record action in memory history."""
        rec = UIActionRecord(
            action_type=action_type,
            params=params,
            dry_run=self.dry_run,
        )
        self.action_history.append(rec)
        logger.debug(f"UI Action: {action_type.value} -> {params} (dry_run={self.dry_run})")

    def _post_action_delay(self, custom_delay: Optional[float] = None) -> None:
        """Apply delay after action if specified."""
        delay = custom_delay if custom_delay is not None else self.action_delay
        if delay > 0:
            time.sleep(delay)

    # ---------------------------------------------------------------------------
    # Mouse Primitives
    # ---------------------------------------------------------------------------

    def click(
        self,
        x: Optional[int] = None,
        y: Optional[int] = None,
        button: str = "left",
        clicks: int = 1,
        interval: float = 0.0,
        delay: Optional[float] = None,
    ) -> None:
        """Perform a single or multi-click at (x, y) or current cursor position.

        Args:
            x: Optional screen X pixel coordinate.
            y: Optional screen Y pixel coordinate.
            button: 'left', 'right', or 'middle'. Defaults to 'left'.
            clicks: Number of clicks. Defaults to 1.
            interval: Seconds between multi-clicks. Defaults to 0.0.
            delay: Optional post-action delay in seconds.
        """
        self._record(UIActionType.CLICK, {"x": x, "y": y, "button": button, "clicks": clicks})
        if not self.dry_run:
            self.backend.click(x=x, y=y, button=button, clicks=clicks, interval=interval)
        self._post_action_delay(delay)

    def double_click(
        self,
        x: Optional[int] = None,
        y: Optional[int] = None,
        interval: float = 0.1,
        delay: Optional[float] = None,
    ) -> None:
        """Perform a double click at (x, y) or current cursor position.

        Args:
            x: Optional screen X pixel coordinate.
            y: Optional screen Y pixel coordinate.
            interval: Interval between the two clicks in seconds. Defaults to 0.1.
            delay: Optional post-action delay in seconds.
        """
        self._record(UIActionType.DOUBLE_CLICK, {"x": x, "y": y, "interval": interval})
        if not self.dry_run:
            self.backend.double_click(x=x, y=y, interval=interval)
        self._post_action_delay(delay)

    def right_click(
        self,
        x: Optional[int] = None,
        y: Optional[int] = None,
        delay: Optional[float] = None,
    ) -> None:
        """Perform a right click at (x, y) or current cursor position.

        Args:
            x: Optional screen X pixel coordinate.
            y: Optional screen Y pixel coordinate.
            delay: Optional post-action delay in seconds.
        """
        self._record(UIActionType.RIGHT_CLICK, {"x": x, "y": y})
        if not self.dry_run:
            self.backend.right_click(x=x, y=y)
        self._post_action_delay(delay)

    def middle_click(
        self,
        x: Optional[int] = None,
        y: Optional[int] = None,
        delay: Optional[float] = None,
    ) -> None:
        """Perform a middle click at (x, y) or current cursor position.

        Args:
            x: Optional screen X pixel coordinate.
            y: Optional screen Y pixel coordinate.
            delay: Optional post-action delay in seconds.
        """
        self._record(UIActionType.MIDDLE_CLICK, {"x": x, "y": y})
        if not self.dry_run:
            self.backend.middle_click(x=x, y=y)
        self._post_action_delay(delay)

    def move_to(
        self,
        x: int,
        y: int,
        duration: float = 0.0,
        delay: Optional[float] = None,
    ) -> None:
        """Move cursor to (x, y).

        Args:
            x: Screen X pixel coordinate.
            y: Screen Y pixel coordinate.
            duration: Animation duration in seconds.
            delay: Optional post-action delay in seconds.
        """
        self._record(UIActionType.MOVE_TO, {"x": x, "y": y, "duration": duration})
        if not self.dry_run:
            self.backend.move_to(x=x, y=y, duration=duration)
        self._post_action_delay(delay)

    def drag_to(
        self,
        x: int,
        y: int,
        duration: float = 0.2,
        button: str = "left",
        delay: Optional[float] = None,
    ) -> None:
        """Drag mouse cursor to (x, y).

        Args:
            x: Target screen X pixel coordinate.
            y: Target screen Y pixel coordinate.
            duration: Duration of drag motion in seconds.
            button: Mouse button to hold while dragging.
            delay: Optional post-action delay in seconds.
        """
        self._record(UIActionType.DRAG_TO, {"x": x, "y": y, "duration": duration, "button": button})
        if not self.dry_run:
            self.backend.drag_to(x=x, y=y, duration=duration, button=button)
        self._post_action_delay(delay)

    def mouse_down(
        self,
        x: Optional[int] = None,
        y: Optional[int] = None,
        button: str = "left",
        delay: Optional[float] = None,
    ) -> None:
        """Press down mouse button.

        Args:
            x: Optional screen X coordinate.
            y: Optional screen Y coordinate.
            button: Mouse button ('left', 'right', 'middle').
            delay: Optional post-action delay in seconds.
        """
        self._record(UIActionType.MOUSE_DOWN, {"x": x, "y": y, "button": button})
        if not self.dry_run:
            self.backend.mouse_down(x=x, y=y, button=button)
        self._post_action_delay(delay)

    def mouse_up(
        self,
        x: Optional[int] = None,
        y: Optional[int] = None,
        button: str = "left",
        delay: Optional[float] = None,
    ) -> None:
        """Release mouse button.

        Args:
            x: Optional screen X coordinate.
            y: Optional screen Y coordinate.
            button: Mouse button ('left', 'right', 'middle').
            delay: Optional post-action delay in seconds.
        """
        self._record(UIActionType.MOUSE_UP, {"x": x, "y": y, "button": button})
        if not self.dry_run:
            self.backend.mouse_up(x=x, y=y, button=button)
        self._post_action_delay(delay)

    def scroll(
        self,
        clicks: int,
        x: Optional[int] = None,
        y: Optional[int] = None,
        delay: Optional[float] = None,
    ) -> None:
        """Scroll vertical mouse wheel.

        Args:
            clicks: Number of scroll steps (positive for up, negative for down).
            x: Optional screen X coordinate.
            y: Optional screen Y coordinate.
            delay: Optional post-action delay in seconds.
        """
        self._record(UIActionType.SCROLL, {"clicks": clicks, "x": x, "y": y})
        if not self.dry_run:
            self.backend.scroll(clicks=clicks, x=x, y=y)
        self._post_action_delay(delay)

    # ---------------------------------------------------------------------------
    # Relative Canvas Coordinates Primitives
    # ---------------------------------------------------------------------------

    def resolve_screen_coords(
        self,
        relative_x: float,
        relative_y: float,
        bbox: Union[CanvasBoundingBox, ScreenRegion, Tuple[int, int, int, int], Dict[str, Any]],
    ) -> Tuple[int, int]:
        """Convert normalized relative coordinates [0.0, 1.0] to absolute screen coordinates.

        Formula:
            X_screen = X_origin + (relative_x * width)
            Y_screen = Y_origin + (relative_y * height)

        Args:
            relative_x: Normalized relative X [0.0, 1.0].
            relative_y: Normalized relative Y [0.0, 1.0].
            bbox: Bounding box defining canvas area.

        Returns:
            Tuple of (screen_x, screen_y) integers.
        """
        norm_region = normalize_region(bbox)
        if norm_region is None:
            raise ValueError("Bounding box cannot be None when resolving relative coordinates.")

        canvas_bbox = norm_region.to_canvas_bbox()
        return canvas_bbox.to_screen_coords(relative_x, relative_y)

    def click_relative(
        self,
        relative_x: float,
        relative_y: float,
        bbox: Union[CanvasBoundingBox, ScreenRegion, Tuple[int, int, int, int], Dict[str, Any]],
        button: str = "left",
        clicks: int = 1,
        delay: Optional[float] = None,
    ) -> Tuple[int, int]:
        """Click at relative normalized coordinates inside a bounding box.

        Args:
            relative_x: Normalized X coordinate [0.0, 1.0].
            relative_y: Normalized Y coordinate [0.0, 1.0].
            bbox: Canvas bounding box.
            button: 'left', 'right', or 'middle'. Defaults to 'left'.
            clicks: Number of clicks. Defaults to 1.
            delay: Optional post-action delay in seconds.

        Returns:
            Tuple of calculated (screen_x, screen_y).
        """
        sx, sy = self.resolve_screen_coords(relative_x, relative_y, bbox)
        self.click(x=sx, y=sy, button=button, clicks=clicks, delay=delay)
        return (sx, sy)

    def double_click_relative(
        self,
        relative_x: float,
        relative_y: float,
        bbox: Union[CanvasBoundingBox, ScreenRegion, Tuple[int, int, int, int], Dict[str, Any]],
        interval: float = 0.1,
        delay: Optional[float] = None,
    ) -> Tuple[int, int]:
        """Double click at relative normalized coordinates inside a bounding box.

        Args:
            relative_x: Normalized X coordinate [0.0, 1.0].
            relative_y: Normalized Y coordinate [0.0, 1.0].
            bbox: Canvas bounding box.
            interval: Interval between double clicks. Defaults to 0.1.
            delay: Optional post-action delay in seconds.

        Returns:
            Tuple of calculated (screen_x, screen_y).
        """
        sx, sy = self.resolve_screen_coords(relative_x, relative_y, bbox)
        self.double_click(x=sx, y=sy, interval=interval, delay=delay)
        return (sx, sy)

    def right_click_relative(
        self,
        relative_x: float,
        relative_y: float,
        bbox: Union[CanvasBoundingBox, ScreenRegion, Tuple[int, int, int, int], Dict[str, Any]],
        delay: Optional[float] = None,
    ) -> Tuple[int, int]:
        """Right click at relative normalized coordinates inside a bounding box.

        Args:
            relative_x: Normalized X coordinate [0.0, 1.0].
            relative_y: Normalized Y coordinate [0.0, 1.0].
            bbox: Canvas bounding box.
            delay: Optional post-action delay in seconds.

        Returns:
            Tuple of calculated (screen_x, screen_y).
        """
        sx, sy = self.resolve_screen_coords(relative_x, relative_y, bbox)
        self.right_click(x=sx, y=sy, delay=delay)
        return (sx, sy)

    # ---------------------------------------------------------------------------
    # Keyboard & Text Input Primitives
    # ---------------------------------------------------------------------------

    def type_text(
        self,
        text: str,
        interval: float = 0.0,
        delay: Optional[float] = None,
    ) -> None:
        """Type a text string sequentially into the active focus element.

        Args:
            text: Text string to type.
            interval: Delay in seconds between each keystroke. Defaults to 0.0.
            delay: Optional post-action delay in seconds.
        """
        self._record(UIActionType.TYPE_TEXT, {"text": text, "interval": interval})
        if not self.dry_run:
            self.backend.type_text(text, interval=interval)
        self._post_action_delay(delay)

    def paste_text(
        self,
        text: str,
        delay: Optional[float] = None,
    ) -> None:
        """Paste text via the system clipboard (Ctrl+V).

        Highly recommended for multi-line text, special characters, or long strings.

        Args:
            text: String content to copy and paste.
            delay: Optional post-action delay in seconds.
        """
        self._record(UIActionType.PASTE_TEXT, {"text": text})
        if not self.dry_run:
            self.backend.paste_text(text)
        self._post_action_delay(delay)

    def clear_text(self, delay: Optional[float] = None) -> None:
        """Select all existing content (Ctrl+A) and delete it (Backspace).

        Args:
            delay: Optional post-action delay in seconds.
        """
        self._record(UIActionType.CLEAR_TEXT, {})
        if not self.dry_run:
            self.backend.hotkey("ctrl", "a")
            time.sleep(0.05)
            self.backend.press_key("backspace")
        self._post_action_delay(delay)

    def clear_and_type(
        self,
        text: str,
        use_clipboard: bool = True,
        interval: float = 0.0,
        delay: Optional[float] = None,
    ) -> None:
        """Select all existing text, delete it, and type/paste the replacement.

        Args:
            text: New text to insert.
            use_clipboard: If True, uses clipboard paste (Ctrl+V); otherwise types characters.
            interval: Typing interval if not using clipboard.
            delay: Optional post-action delay in seconds.
        """
        self._record(
            UIActionType.CLEAR_AND_TYPE,
            {"text": text, "use_clipboard": use_clipboard, "interval": interval},
        )
        if not self.dry_run:
            self.backend.hotkey("ctrl", "a")
            time.sleep(0.05)
            self.backend.press_key("backspace")
            time.sleep(0.05)
            if use_clipboard:
                self.backend.paste_text(text)
            else:
                self.backend.type_text(text, interval=interval)
        self._post_action_delay(delay)

    def press_key(
        self,
        key: str,
        presses: int = 1,
        interval: float = 0.0,
        delay: Optional[float] = None,
    ) -> None:
        """Press a keyboard key (e.g. 'enter', 'tab', 'esc', 'space', 'backspace').

        Args:
            key: Name of the key to press.
            presses: Number of times to press. Defaults to 1.
            interval: Delay between presses. Defaults to 0.0.
            delay: Optional post-action delay in seconds.
        """
        self._record(UIActionType.PRESS_KEY, {"key": key, "presses": presses, "interval": interval})
        if not self.dry_run:
            self.backend.press_key(key, presses=presses, interval=interval)
        self._post_action_delay(delay)

    def key_down(self, key: str, delay: Optional[float] = None) -> None:
        """Hold a key down without releasing it.

        Args:
            key: Name of key to hold down.
            delay: Optional post-action delay in seconds.
        """
        self._record(UIActionType.KEY_DOWN, {"key": key})
        if not self.dry_run:
            self.backend.key_down(key)
        self._post_action_delay(delay)

    def key_up(self, key: str, delay: Optional[float] = None) -> None:
        """Release a held key.

        Args:
            key: Name of key to release.
            delay: Optional post-action delay in seconds.
        """
        self._record(UIActionType.KEY_UP, {"key": key})
        if not self.dry_run:
            self.backend.key_up(key)
        self._post_action_delay(delay)

    def hotkey(
        self,
        *keys: str,
        interval: float = 0.0,
        delay: Optional[float] = None,
    ) -> None:
        """Execute a key combination (e.g. hotkey('ctrl', 's'), hotkey('alt', 'f4')).

        Args:
            *keys: Sequence of key strings.
            interval: Interval between key presses.
            delay: Optional post-action delay in seconds.
        """
        self._record(UIActionType.HOTKEY, {"keys": list(keys), "interval": interval})
        if not self.dry_run:
            self.backend.hotkey(*keys, interval=interval)
        self._post_action_delay(delay)

    # ---------------------------------------------------------------------------
    # Timing & Delays
    # ---------------------------------------------------------------------------

    def wait(self, seconds: float) -> None:
        """Explicitly pause execution for the specified duration.

        Args:
            seconds: Duration to wait in seconds.
        """
        self._record(UIActionType.WAIT, {"seconds": seconds})
        if seconds > 0:
            time.sleep(seconds)

    # ---------------------------------------------------------------------------
    # Windows Window Management & Focus
    # ---------------------------------------------------------------------------

    def find_window(self, title_pattern: str) -> Optional[int]:
        """Find a top-level Windows window matching title regex pattern.

        Args:
            title_pattern: Regular expression or substring of the window title.

        Returns:
            Window HWND integer handle if found, else None.
        """
        if sys.platform != "win32":
            logger.debug("Window management is only supported on Windows.")
            return None

        found_hwnd: Optional[int] = None
        compiled_regex = re.compile(title_pattern, re.IGNORECASE)

        def enum_windows_callback(hwnd: int, lparam: int) -> bool:
            nonlocal found_hwnd
            if ctypes.windll.user32.IsWindowVisible(hwnd):
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value
                    if compiled_regex.search(title):
                        found_hwnd = hwnd
                        return False  # Stop enumeration
            return True

        enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)(enum_windows_callback)
        try:
            ctypes.windll.user32.EnumWindows(enum_proc, 0)
        except Exception as exc:
            logger.debug(f"EnumWindows call encountered: {exc}")

        return found_hwnd

    def focus_window(self, title_pattern: str, delay: Optional[float] = None) -> bool:
        """Bring a target window matching title pattern to the foreground.

        Args:
            title_pattern: Window title regex or substring (e.g. 'ODIS Creator').
            delay: Optional post-action delay in seconds.

        Returns:
            True if window was found and brought to foreground, False otherwise.
        """
        self._record(UIActionType.FOCUS_WINDOW, {"title_pattern": title_pattern})
        if self.dry_run:
            self._post_action_delay(delay)
            return True

        if sys.platform != "win32":
            logger.debug("focus_window is only implemented for Windows.")
            self._post_action_delay(delay)
            return False

        hwnd = self.find_window(title_pattern)
        if hwnd is None:
            logger.warning(f"Could not find window matching pattern: '{title_pattern}'")
            return False

        try:
            # If minimized, restore it
            if ctypes.windll.user32.IsIconic(hwnd):
                ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE = 9

            # Bring to foreground
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            self._post_action_delay(delay or 0.2)
            return True
        except Exception as exc:
            logger.warning(f"Failed to focus window HWND {hwnd}: {exc}")
            return False

    def maximize_window(self, hwnd: Optional[int] = None, delay: Optional[float] = None) -> bool:
        """Maximize the specified window or current active window.

        Args:
            hwnd: Optional HWND handle. If None, targets the current foreground window.
            delay: Optional post-action delay in seconds.

        Returns:
            True if maximized successfully, False otherwise.
        """
        self._record(UIActionType.MAXIMIZE_WINDOW, {"hwnd": hwnd})
        if self.dry_run:
            self._post_action_delay(delay)
            return True

        if sys.platform != "win32":
            return False

        target_hwnd = hwnd or ctypes.windll.user32.GetForegroundWindow()
        if not target_hwnd:
            return False

        try:
            # SW_MAXIMIZE = 3
            res = ctypes.windll.user32.ShowWindow(target_hwnd, 3)
            self._post_action_delay(delay or 0.2)
            return bool(res)
        except Exception as exc:
            logger.warning(f"Failed to maximize window HWND {target_hwnd}: {exc}")
            return False

    def clear_history(self) -> None:
        """Reset recorded action history."""
        self.action_history.clear()


# Global default instance
_default_ui_driver: Optional[UIDriver] = None


def get_ui_driver() -> UIDriver:
    """Return singleton UIDriver instance."""
    global _default_ui_driver
    if _default_ui_driver is None:
        _default_ui_driver = UIDriver()
    return _default_ui_driver
