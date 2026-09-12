"""Unit tests for ClickChaos Linux evdev manager and failsafes."""

from __future__ import annotations

import sys
import time
from unittest.mock import MagicMock, call, patch

import pytest

from src.linux_manager import (
    EV_KEY,
    EV_REL,
    EV_SYN,
    REL_WHEEL,
    REL_X,
    REL_Y,
    BTN_LEFT,
    BTN_RIGHT,
    BTN_MIDDLE,
    LinuxMouseChaosManager,
    check_linux_permissions,
)


class DummyInputEvent:
    """Simulates an evdev.InputEvent."""
    def __init__(self, type_: int, code: int, value: int) -> None:
        self.type = type_
        self.code = code
        self.value = value


class TestLinuxManagerDeviceDiscovery:
    def test_find_mouse_devices_filters_keyboards(self):
        """Mice with REL_X/Y and BTN_LEFT should be selected, keyboards must be ignored."""
        # Mock evdev module
        mock_evdev = MagicMock()

        # Device 1: Physical mouse (has REL_X, REL_Y, BTN_LEFT, no keyboard keys)
        mouse_dev = MagicMock()
        mouse_dev.name = "Logitech USB Optical Mouse"
        mouse_dev.path = "/dev/input/event3"
        mouse_dev.capabilities.return_value = {
            EV_REL: [REL_X, REL_Y],
            EV_KEY: [BTN_LEFT, BTN_RIGHT, BTN_MIDDLE],
        }

        # Device 2: Keyboard (has BTN_LEFT, but also KEY_A=30, KEY_ENTER=28)
        kb_dev = MagicMock()
        kb_dev.name = "Mechanical Gaming Keyboard"
        kb_dev.path = "/dev/input/event2"
        kb_dev.capabilities.return_value = {
            EV_REL: [REL_X, REL_Y],
            EV_KEY: [BTN_LEFT, 28, 30],
        }

        # Device 3: Headset/Audio without REL
        audio_dev = MagicMock()
        audio_dev.name = "USB Audio Headset"
        audio_dev.path = "/dev/input/event1"
        audio_dev.capabilities.return_value = {
            EV_KEY: [114, 115],  # Volume buttons only
        }

        mock_evdev.list_devices.return_value = [
            "/dev/input/event1",
            "/dev/input/event2",
            "/dev/input/event3",
        ]

        def input_device_side_effect(path):
            if path == "/dev/input/event1":
                return audio_dev
            elif path == "/dev/input/event2":
                return kb_dev
            elif path == "/dev/input/event3":
                return mouse_dev
            raise ValueError(path)

        mock_evdev.InputDevice.side_effect = input_device_side_effect

        with patch.dict(sys.modules, {"evdev": mock_evdev}):
            devices = LinuxMouseChaosManager.find_mouse_devices()
            assert len(devices) == 1
            assert devices[0].name == "Logitech USB Optical Mouse"
            assert devices[0].path == "/dev/input/event3"


class TestLinuxChaosLogic:
    def test_derangement_generation(self):
        manager = LinuxMouseChaosManager()
        buttons = [BTN_LEFT, BTN_RIGHT, BTN_MIDDLE]

        for _ in range(50):
            mapping = manager.generate_derangement(buttons)
            assert len(mapping) == 3
            assert set(mapping.keys()) == set(buttons)
            assert set(mapping.values()) == set(buttons)
            for b in buttons:
                assert mapping[b] != b, f"Button {b} was mapped to itself!"

    def test_derangement_with_side_buttons(self):
        manager = LinuxMouseChaosManager()
        buttons = [BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, 0x113, 0x114]

        for _ in range(50):
            mapping = manager.generate_derangement(buttons)
            assert len(mapping) == 5
            for b in buttons:
                assert mapping[b] != b

    def test_colored_mapping_card(self):
        manager = LinuxMouseChaosManager(scroll_chaos=True, cursor_drift=True)
        manager._available_buttons = [BTN_LEFT, BTN_RIGHT, BTN_MIDDLE]
        manager._button_mapping = {BTN_LEFT: BTN_RIGHT, BTN_RIGHT: BTN_MIDDLE, BTN_MIDDLE: BTN_LEFT}
        card = manager.get_colored_mapping_card()

        assert "LINUX CLICKCHAOS" in card
        assert "Left Click" in card
        assert "Right Click" in card
        assert "INVERTED" in card
        assert "SAFETY FAILSAFE" in card

    def test_colored_mapping_line(self):
        manager = LinuxMouseChaosManager(scroll_chaos=True, cursor_drift=True)
        manager._available_buttons = [BTN_LEFT, BTN_RIGHT, BTN_MIDDLE]
        manager._button_mapping = {BTN_LEFT: BTN_RIGHT, BTN_RIGHT: BTN_MIDDLE, BTN_MIDDLE: BTN_LEFT}
        line = manager.get_colored_mapping_line()

        assert "Remap:" in line
        assert "Left" in line
        assert "Right" in line
        assert "Middle" in line
        assert "➔" in line



class TestLinuxEventTranslation:
    def test_button_press_and_release_mapping(self):
        """Button press should map to target, and release must use the active mapped target."""
        manager = LinuxMouseChaosManager()
        manager._uinput = MagicMock()
        manager._available_buttons = [BTN_LEFT, BTN_RIGHT, BTN_MIDDLE]
        manager._button_mapping = {
            BTN_LEFT: BTN_RIGHT,    # Left -> Right
            BTN_RIGHT: BTN_MIDDLE,  # Right -> Middle
            BTN_MIDDLE: BTN_LEFT,   # Middle -> Left
        }

        # 1. Physical Left click down (BTN_LEFT=0x110, value=1)
        event_down = DummyInputEvent(type_=EV_KEY, code=BTN_LEFT, value=1)
        manager._process_event(event_down)

        # Verify synthetic Right click was written to uinput
        manager._uinput.write.assert_called_with(EV_KEY, BTN_RIGHT, 1)
        assert manager._active_presses[BTN_LEFT] == BTN_RIGHT

        # 2. Simulate mapping reshuffle while button is held down!
        manager._button_mapping = {
            BTN_LEFT: BTN_MIDDLE,  # Now Left -> Middle
            BTN_RIGHT: BTN_LEFT,
            BTN_MIDDLE: BTN_RIGHT,
        }

        # 3. Physical Left click up (BTN_LEFT=0x110, value=0)
        event_up = DummyInputEvent(type_=EV_KEY, code=BTN_LEFT, value=0)
        manager._process_event(event_up)

        # The release MUST release target BTN_RIGHT, not BTN_MIDDLE, to prevent stuck button!
        manager._uinput.write.assert_called_with(EV_KEY, BTN_RIGHT, 0)
        assert BTN_LEFT not in manager._active_presses

    def test_scroll_wheel_inversion(self):
        """Scroll wheel events should have their delta inverted when scroll_chaos is True."""
        manager = LinuxMouseChaosManager(scroll_chaos=True)
        manager._uinput = MagicMock()

        # Scroll up: delta = +1
        event_scroll_up = DummyInputEvent(type_=EV_REL, code=REL_WHEEL, value=1)
        manager._process_event(event_scroll_up)

        # Virtual uinput should receive delta = -1 (inverted)
        manager._uinput.write.assert_called_with(EV_REL, REL_WHEEL, -1)
        manager._uinput.syn.assert_called()

        # When scroll_chaos is disabled, delta is preserved
        manager.scroll_chaos = False
        manager._process_event(event_scroll_up)
        manager._uinput.write.assert_called_with(EV_REL, REL_WHEEL, 1)

    def test_cursor_drift(self):
        """When cursor_drift is True, REL_X/REL_Y should receive drift offsets."""
        manager = LinuxMouseChaosManager(cursor_drift=True)
        manager._uinput = MagicMock()

        # With patch on random to ensure drift triggers
        with patch("random.random", return_value=0.1), patch("random.choice", return_value=2):
            event_move = DummyInputEvent(type_=EV_REL, code=REL_X, value=10)
            manager._process_event(event_move)
            # Value 10 + offset 2 = 12
            manager._uinput.write.assert_called_with(EV_REL, REL_X, 12)


class TestLinuxSafetyFailsafes:
    def test_dual_button_hold_failsafe(self):
        """Holding Left + Right click for >= 5.0 seconds must trigger emergency ungrab."""
        manager = LinuxMouseChaosManager(failsafe_hold_duration=5.0)
        mock_dev = MagicMock()
        mock_uinput = MagicMock()
        manager._device = mock_dev
        manager._uinput = mock_uinput

        # Both buttons down at t=100.0
        manager._left_down_time = 100.0
        manager._right_down_time = 100.0

        # At t=103.0 (3s elapsed) -> failsafe should NOT trigger
        now = 103.0
        hold_time = min(now - manager._left_down_time, now - manager._right_down_time)
        assert hold_time < manager.failsafe_hold_duration

        # At t=105.1 (5.1s elapsed) -> failsafe MUST trigger
        now = 105.1
        hold_time = min(now - manager._left_down_time, now - manager._right_down_time)
        assert hold_time >= manager.failsafe_hold_duration

    def test_cleanup_ungrabs_device_and_closes_uinput(self):
        """Cleanup must ungrab physical mouse and close uinput device."""
        manager = LinuxMouseChaosManager()
        mock_dev = MagicMock()
        mock_uinput = MagicMock()
        manager._device = mock_dev
        manager._uinput = mock_uinput
        manager._active_presses = {BTN_LEFT: BTN_RIGHT}  # One held press

        manager.cleanup()

        # Check that stuck button was released
        mock_uinput.write.assert_called_with(EV_KEY, BTN_RIGHT, 0)
        # Check device.ungrab was called
        mock_dev.ungrab.assert_called_once()
        # Check uinput.close was called
        mock_uinput.close.assert_called_once()
        assert manager._device is None
        assert manager._uinput is None


class TestLinuxPermissions:
    def test_check_linux_permissions_on_non_linux(self):
        with patch("sys.platform", "win32"):
            ok, msg = check_linux_permissions()
            assert not ok
            assert "not Linux" in msg

    def test_check_linux_permissions_missing_dev_input(self):
        with patch("sys.platform", "linux"), patch("os.path.exists", return_value=False):
            ok, msg = check_linux_permissions()
            assert not ok
            assert "PERMISSION ERROR" in msg
            assert "sudo" in msg
