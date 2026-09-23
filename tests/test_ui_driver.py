"""Unit tests for UI Driver, Mouse/Keyboard Primitives and Action History (TASK-007)."""

from datetime import datetime
from unittest.mock import MagicMock, call, patch
import pytest

from controller.config import Settings
from controller.vision_engine import CanvasBoundingBox
from worker.screen_capture import ScreenRegion
from worker.ui_driver import (
    BackendAdapter,
    UIActionRecord,
    UIActionType,
    UIDriver,
    get_ui_driver,
)


# ---------------------------------------------------------------------------
# Test Models and Enums
# ---------------------------------------------------------------------------

class TestUIModels:
    """Tests for UIActionRecord and UIActionType enums."""

    def test_action_types_enum_members(self):
        assert UIActionType.CLICK == "CLICK"
        assert UIActionType.DOUBLE_CLICK == "DOUBLE_CLICK"
        assert UIActionType.RIGHT_CLICK == "RIGHT_CLICK"
        assert UIActionType.MIDDLE_CLICK == "MIDDLE_CLICK"
        assert UIActionType.MOVE_TO == "MOVE_TO"
        assert UIActionType.DRAG_TO == "DRAG_TO"
        assert UIActionType.TYPE_TEXT == "TYPE_TEXT"
        assert UIActionType.PASTE_TEXT == "PASTE_TEXT"
        assert UIActionType.CLEAR_TEXT == "CLEAR_TEXT"
        assert UIActionType.CLEAR_AND_TYPE == "CLEAR_AND_TYPE"
        assert UIActionType.PRESS_KEY == "PRESS_KEY"
        assert UIActionType.HOTKEY == "HOTKEY"
        assert UIActionType.WAIT == "WAIT"
        assert UIActionType.FOCUS_WINDOW == "FOCUS_WINDOW"
        assert UIActionType.MAXIMIZE_WINDOW == "MAXIMIZE_WINDOW"

    def test_action_record_creation(self):
        rec = UIActionRecord(
            action_type=UIActionType.CLICK,
            params={"x": 100, "y": 200, "button": "left"},
            dry_run=True,
        )
        assert rec.action_type == UIActionType.CLICK
        assert rec.params["x"] == 100
        assert rec.params["y"] == 200
        assert rec.dry_run is True
        assert rec.timestamp is not None


# ---------------------------------------------------------------------------
# Test BackendAdapter Delegation
# ---------------------------------------------------------------------------

class TestBackendAdapter:
    """Tests that BackendAdapter properly delegates calls to PyAutoGUI and Pyperclip."""

    def setup_method(self):
        self.mock_pyautogui = MagicMock()
        self.mock_clipboard = MagicMock()
        self.adapter = BackendAdapter(
            pyautogui_module=self.mock_pyautogui,
            clipboard_module=self.mock_clipboard,
        )

    def test_click_with_coords(self):
        self.adapter.click(x=150, y=250, button="right", clicks=2, interval=0.1)
        self.mock_pyautogui.click.assert_called_once_with(
            x=150, y=250, clicks=2, interval=0.1, button="right"
        )

    def test_click_without_coords(self):
        self.adapter.click(clicks=1, button="left")
        self.mock_pyautogui.click.assert_called_once_with(
            clicks=1, interval=0.0, button="left"
        )

    def test_double_click(self):
        self.adapter.double_click(x=300, y=400, interval=0.2, button="left")
        self.mock_pyautogui.doubleClick.assert_called_once_with(
            x=300, y=400, interval=0.2, button="left"
        )

    def test_right_click(self):
        self.adapter.right_click(x=500, y=600)
        self.mock_pyautogui.rightClick.assert_called_once_with(x=500, y=600)

    def test_middle_click(self):
        self.adapter.middle_click(x=700, y=800)
        self.mock_pyautogui.middleClick.assert_called_once_with(x=700, y=800)

    def test_move_to(self):
        self.adapter.move_to(x=100, y=200, duration=0.25)
        self.mock_pyautogui.moveTo.assert_called_once_with(x=100, y=200, duration=0.25)

    def test_drag_to(self):
        self.adapter.drag_to(x=300, y=400, duration=0.5, button="left")
        self.mock_pyautogui.dragTo.assert_called_once_with(x=300, y=400, duration=0.5, button="left")

    def test_mouse_down_and_up(self):
        self.adapter.mouse_down(x=10, y=20, button="left")
        self.adapter.mouse_up(x=10, y=20, button="left")
        self.mock_pyautogui.mouseDown.assert_called_once_with(x=10, y=20, button="left")
        self.mock_pyautogui.mouseUp.assert_called_once_with(x=10, y=20, button="left")

    def test_scroll(self):
        self.adapter.scroll(clicks=-5, x=100, y=200)
        self.mock_pyautogui.scroll.assert_called_once_with(-5, x=100, y=200)

    def test_type_text(self):
        self.adapter.type_text("Test string", interval=0.01)
        self.mock_pyautogui.typewrite.assert_called_once_with("Test string", interval=0.01)

    def test_paste_text(self):
        self.adapter.paste_text("Pasted content")
        self.mock_clipboard.copy.assert_called_once_with("Pasted content")
        self.mock_pyautogui.hotkey.assert_called_once_with("ctrl", "v", interval=0.0)

    def test_press_key(self):
        self.adapter.press_key("enter", presses=2, interval=0.05)
        self.mock_pyautogui.press.assert_called_once_with("enter", presses=2, interval=0.05)

    def test_key_down_and_up(self):
        self.adapter.key_down("shift")
        self.adapter.key_up("shift")
        self.mock_pyautogui.keyDown.assert_called_once_with("shift")
        self.mock_pyautogui.keyUp.assert_called_once_with("shift")

    def test_hotkey(self):
        self.adapter.hotkey("ctrl", "alt", "del")
        self.mock_pyautogui.hotkey.assert_called_once_with("ctrl", "alt", "del", interval=0.0)

    def test_get_mouse_position(self):
        self.mock_pyautogui.position.return_value = (1920, 1080)
        pos = self.adapter.get_mouse_position()
        assert pos == (1920, 1080)


# ---------------------------------------------------------------------------
# Test UIDriver in Dry-Run Mode
# ---------------------------------------------------------------------------

class TestUIDriverDryRun:
    """Tests that UIDriver in dry-run mode records actions without invoking backend."""

    def setup_method(self):
        self.mock_backend = MagicMock(spec=BackendAdapter)
        self.driver = UIDriver(
            dry_run=True,
            action_delay=0.0,
            backend=self.mock_backend,
        )

    def test_dry_run_click_records_action(self):
        self.driver.click(x=100, y=200, button="left")
        assert len(self.driver.action_history) == 1
        rec = self.driver.action_history[0]
        assert rec.action_type == UIActionType.CLICK
        assert rec.params == {"x": 100, "y": 200, "button": "left", "clicks": 1}
        assert rec.dry_run is True
        # Underlying backend MUST NOT be called in dry run
        self.mock_backend.click.assert_not_called()

    def test_dry_run_double_click_records_action(self):
        self.driver.double_click(x=300, y=400, interval=0.1)
        assert len(self.driver.action_history) == 1
        assert self.driver.action_history[0].action_type == UIActionType.DOUBLE_CLICK
        self.mock_backend.double_click.assert_not_called()

    def test_dry_run_right_click_records_action(self):
        self.driver.right_click(x=500, y=600)
        assert len(self.driver.action_history) == 1
        assert self.driver.action_history[0].action_type == UIActionType.RIGHT_CLICK
        self.mock_backend.right_click.assert_not_called()

    def test_dry_run_middle_click_records_action(self):
        self.driver.middle_click(x=150, y=250)
        assert len(self.driver.action_history) == 1
        assert self.driver.action_history[0].action_type == UIActionType.MIDDLE_CLICK
        self.mock_backend.middle_click.assert_not_called()

    def test_dry_run_type_and_paste_text(self):
        self.driver.type_text("Sample input")
        self.driver.paste_text("Pasted input")
        assert len(self.driver.action_history) == 2
        assert self.driver.action_history[0].action_type == UIActionType.TYPE_TEXT
        assert self.driver.action_history[1].action_type == UIActionType.PASTE_TEXT
        self.mock_backend.type_text.assert_not_called()
        self.mock_backend.paste_text.assert_not_called()

    def test_dry_run_clear_and_type(self):
        self.driver.clear_and_type("Cleaned text", use_clipboard=True)
        assert len(self.driver.action_history) == 1
        rec = self.driver.action_history[0]
        assert rec.action_type == UIActionType.CLEAR_AND_TYPE
        assert rec.params["text"] == "Cleaned text"
        self.mock_backend.hotkey.assert_not_called()
        self.mock_backend.press_key.assert_not_called()
        self.mock_backend.paste_text.assert_not_called()
        self.mock_backend.type_text.assert_not_called()

    def test_dry_run_hotkey_and_press_key(self):
        self.driver.hotkey("ctrl", "a")
        self.driver.press_key("enter", presses=2)
        assert len(self.driver.action_history) == 2
        assert self.driver.action_history[0].action_type == UIActionType.HOTKEY
        assert self.driver.action_history[1].action_type == UIActionType.PRESS_KEY
        self.mock_backend.hotkey.assert_not_called()
        self.mock_backend.press_key.assert_not_called()

    def test_clear_history(self):
        self.driver.click(10, 20)
        self.driver.press_key("esc")
        assert len(self.driver.action_history) == 2
        self.driver.clear_history()
        assert len(self.driver.action_history) == 0


# ---------------------------------------------------------------------------
# Test UIDriver in Live Execution Mode
# ---------------------------------------------------------------------------

class TestUIDriverLiveExecution:
    """Tests that UIDriver in active mode invokes backend adapter properly."""

    def setup_method(self):
        self.mock_backend = MagicMock(spec=BackendAdapter)
        self.driver = UIDriver(
            dry_run=False,
            action_delay=0.0,
            backend=self.mock_backend,
        )

    def test_live_click(self):
        self.driver.click(x=100, y=200, button="left", clicks=1)
        self.mock_backend.click.assert_called_once_with(
            x=100, y=200, button="left", clicks=1, interval=0.0
        )
        assert len(self.driver.action_history) == 1
        assert self.driver.action_history[0].dry_run is False

    def test_live_double_click(self):
        self.driver.double_click(x=300, y=400, interval=0.15)
        self.mock_backend.double_click.assert_called_once_with(
            x=300, y=400, interval=0.15
        )

    def test_live_right_click(self):
        self.driver.right_click(x=500, y=600)
        self.mock_backend.right_click.assert_called_once_with(x=500, y=600)

    def test_live_move_to_and_drag_to(self):
        self.driver.move_to(x=50, y=60, duration=0.1)
        self.mock_backend.move_to.assert_called_once_with(x=50, y=60, duration=0.1)

        self.driver.drag_to(x=70, y=80, duration=0.2, button="right")
        self.mock_backend.drag_to.assert_called_once_with(x=70, y=80, duration=0.2, button="right")

    def test_live_mouse_down_and_up(self):
        self.driver.mouse_down(x=10, y=20, button="middle")
        self.driver.mouse_up(x=10, y=20, button="middle")
        self.mock_backend.mouse_down.assert_called_once_with(x=10, y=20, button="middle")
        self.mock_backend.mouse_up.assert_called_once_with(x=10, y=20, button="middle")

    def test_live_scroll(self):
        self.driver.scroll(clicks=-3, x=100, y=200)
        self.mock_backend.scroll.assert_called_once_with(clicks=-3, x=100, y=200)

    def test_live_type_text(self):
        self.driver.type_text("Hello World", interval=0.02)
        self.mock_backend.type_text.assert_called_once_with("Hello World", interval=0.02)

    def test_live_paste_text(self):
        self.driver.paste_text("Pasted Text")
        self.mock_backend.paste_text.assert_called_once_with("Pasted Text")

    def test_live_clear_text(self):
        self.driver.clear_text()
        self.mock_backend.hotkey.assert_called_once_with("ctrl", "a")
        self.mock_backend.press_key.assert_called_once_with("backspace")

    def test_live_clear_and_type_with_clipboard(self):
        self.driver.clear_and_type("Replaced content", use_clipboard=True)
        self.mock_backend.hotkey.assert_called_once_with("ctrl", "a")
        self.mock_backend.press_key.assert_called_once_with("backspace")
        self.mock_backend.paste_text.assert_called_once_with("Replaced content")

    def test_live_clear_and_type_with_typing(self):
        self.driver.clear_and_type("Typed content", use_clipboard=False, interval=0.01)
        self.mock_backend.hotkey.assert_called_once_with("ctrl", "a")
        self.mock_backend.press_key.assert_called_once_with("backspace")
        self.mock_backend.type_text.assert_called_once_with("Typed content", interval=0.01)

    def test_live_press_key(self):
        self.driver.press_key("enter", presses=1)
        self.mock_backend.press_key.assert_called_once_with("enter", presses=1, interval=0.0)

    def test_live_key_down_and_up(self):
        self.driver.key_down("ctrl")
        self.driver.key_up("ctrl")
        self.mock_backend.key_down.assert_called_once_with("ctrl")
        self.mock_backend.key_up.assert_called_once_with("ctrl")

    def test_live_hotkey(self):
        self.driver.hotkey("ctrl", "shift", "s")
        self.mock_backend.hotkey.assert_called_once_with("ctrl", "shift", "s", interval=0.0)

    def test_live_wait(self):
        self.driver.wait(0.001)
        assert len(self.driver.action_history) == 1
        assert self.driver.action_history[0].action_type == UIActionType.WAIT


# ---------------------------------------------------------------------------
# Test Relative Canvas Coordinates Mapping
# ---------------------------------------------------------------------------

class TestUIDriverRelativeCoordinates:
    """Tests for resolving and clicking normalized [0.0, 1.0] coordinates within bounding boxes."""

    def setup_method(self):
        self.mock_backend = MagicMock(spec=BackendAdapter)
        self.driver = UIDriver(
            dry_run=False,
            action_delay=0.0,
            backend=self.mock_backend,
        )
        self.bbox = CanvasBoundingBox(x=510, y=120, width=1400, height=900)

    def test_resolve_screen_coords(self):
        # 510 + (0.45 * 1400) = 510 + 630 = 1140
        # 120 + (0.32 * 900) = 120 + 288 = 408
        sx, sy = self.driver.resolve_screen_coords(0.45, 0.32, self.bbox)
        assert sx == 1140
        assert sy == 408

    def test_resolve_screen_coords_with_screen_region(self):
        region = ScreenRegion(x=100, y=200, width=1000, height=500)
        sx, sy = self.driver.resolve_screen_coords(0.5, 0.5, region)
        assert sx == 600
        assert sy == 450

    def test_resolve_screen_coords_with_tuple(self):
        sx, sy = self.driver.resolve_screen_coords(0.5, 0.5, (100, 200, 1000, 500))
        assert sx == 600
        assert sy == 450

    def test_resolve_screen_coords_invalid_bbox_raises(self):
        with pytest.raises(ValueError):
            self.driver.resolve_screen_coords(0.5, 0.5, None)

    def test_click_relative(self):
        sx, sy = self.driver.click_relative(0.45, 0.32, self.bbox, button="left")
        assert sx == 1140
        assert sy == 408
        self.mock_backend.click.assert_called_once_with(
            x=1140, y=408, button="left", clicks=1, interval=0.0
        )

    def test_double_click_relative(self):
        sx, sy = self.driver.double_click_relative(0.52, 0.58, self.bbox, interval=0.12)
        # 510 + (0.52 * 1400) = 510 + 728 = 1238
        # 120 + (0.58 * 900) = 120 + 522 = 642
        assert sx == 1238
        assert sy == 642
        self.mock_backend.double_click.assert_called_once_with(
            x=1238, y=642, interval=0.12
        )

    def test_right_click_relative(self):
        sx, sy = self.driver.right_click_relative(0.61, 0.75, self.bbox)
        # 510 + (0.61 * 1400) = 510 + 854 = 1364
        # 120 + (0.75 * 900) = 120 + 675 = 795
        assert sx == 1364
        assert sy == 795
        self.mock_backend.right_click.assert_called_once_with(x=1364, y=795)


# ---------------------------------------------------------------------------
# Test Window Management
# ---------------------------------------------------------------------------

class TestUIDriverWindowManagement:
    """Tests for window focus, find, and maximize operations."""

    def test_focus_window_dry_run(self):
        driver = UIDriver(dry_run=True, action_delay=0.0)
        res = driver.focus_window("ODIS Creator")
        assert res is True
        assert len(driver.action_history) == 1
        assert driver.action_history[0].action_type == UIActionType.FOCUS_WINDOW

    def test_maximize_window_dry_run(self):
        driver = UIDriver(dry_run=True, action_delay=0.0)
        res = driver.maximize_window()
        assert res is True
        assert len(driver.action_history) == 1
        assert driver.action_history[0].action_type == UIActionType.MAXIMIZE_WINDOW

    def test_find_window_non_windows_platform(self):
        driver = UIDriver(dry_run=False, action_delay=0.0)
        with patch("sys.platform", "linux"):
            assert driver.find_window("ODIS") is None
            assert driver.focus_window("ODIS") is False
            assert driver.maximize_window() is False

    def test_focus_window_success_on_windows(self):
        driver = UIDriver(dry_run=False, action_delay=0.0)
        with patch("sys.platform", "win32"), \
             patch.object(driver, "find_window", return_value=12345), \
             patch("ctypes.windll") as mock_windll:
            
            mock_windll.user32.IsIconic.return_value = 0
            mock_windll.user32.SetForegroundWindow.return_value = 1

            res = driver.focus_window("ODIS Creator")
            assert res is True
            mock_windll.user32.SetForegroundWindow.assert_called_once_with(12345)

    def test_focus_window_restores_minimized_window(self):
        driver = UIDriver(dry_run=False, action_delay=0.0)
        with patch("sys.platform", "win32"), \
             patch.object(driver, "find_window", return_value=54321), \
             patch("ctypes.windll") as mock_windll:
            
            mock_windll.user32.IsIconic.return_value = 1  # Window is minimized
            mock_windll.user32.ShowWindow.return_value = 1
            mock_windll.user32.SetForegroundWindow.return_value = 1

            res = driver.focus_window("ODIS Creator")
            assert res is True
            mock_windll.user32.ShowWindow.assert_called_once_with(54321, 9)  # SW_RESTORE
            mock_windll.user32.SetForegroundWindow.assert_called_once_with(54321)

    def test_focus_window_not_found_returns_false(self):
        driver = UIDriver(dry_run=False, action_delay=0.0)
        with patch("sys.platform", "win32"), \
             patch.object(driver, "find_window", return_value=None):
            
            res = driver.focus_window("NonExistentWindow")
            assert res is False

    def test_maximize_window_success_on_windows(self):
        driver = UIDriver(dry_run=False, action_delay=0.0)
        with patch("sys.platform", "win32"), patch("ctypes.windll") as mock_windll:
            mock_windll.user32.GetForegroundWindow.return_value = 99999
            mock_windll.user32.ShowWindow.return_value = 1

            res = driver.maximize_window()
            assert res is True
            mock_windll.user32.ShowWindow.assert_called_once_with(99999, 3)  # SW_MAXIMIZE

    def test_maximize_window_no_foreground_returns_false(self):
        driver = UIDriver(dry_run=False, action_delay=0.0)
        with patch("sys.platform", "win32"), patch("ctypes.windll") as mock_windll:
            mock_windll.user32.GetForegroundWindow.return_value = 0
            res = driver.maximize_window()
            assert res is False


# ---------------------------------------------------------------------------
# Test Singleton Accessor
# ---------------------------------------------------------------------------

class TestUIDriverSingleton:
    """Tests for singleton factory."""

    def test_get_ui_driver_singleton(self):
        d1 = get_ui_driver()
        d2 = get_ui_driver()
        assert d1 is d2
        assert isinstance(d1, UIDriver)
