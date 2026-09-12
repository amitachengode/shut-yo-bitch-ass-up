"""Unit and functional tests for ClickChaos."""

from __future__ import annotations

import ctypes
import threading
import time

import pytest
from PIL import Image

from src.hook_manager import (
    CHAOS_EXTRA_INFO,
    INPUT,
    LLMHF_INJECTED,
    LLMHF_LOWER_IL_INJECTED,
    MOUSEINPUT,
    MSLLHOOKSTRUCT,
    WM_LBUTTONDOWN,
    WM_LBUTTONUP,
    WM_MBUTTONDOWN,
    WM_MBUTTONUP,
    WM_RBUTTONDOWN,
    WM_RBUTTONUP,
    MouseHookManager,
)
from src.randomizer import ALL_BUTTONS, ButtonRandomizer, ButtonType
from src.tray_ui import generate_tray_image


class TestButtonRandomizer:
    def test_bijective_mapping(self):
        """Every generated mapping must be a 1-to-1 bijection of the 3 buttons."""
        randomizer = ButtonRandomizer(derangement_only=False)
        for _ in range(50):
            mapping = randomizer.generate_mapping()
            assert len(mapping) == 3
            # All buttons present in keys and values
            assert set(mapping.keys()) == set(ALL_BUTTONS)
            assert set(mapping.values()) == set(ALL_BUTTONS)

    def test_derangement_mapping(self):
        """When derangement_only is True, no button should map to itself."""
        randomizer = ButtonRandomizer(derangement_only=True)
        for _ in range(50):
            mapping = randomizer.generate_mapping()
            for btn in ALL_BUTTONS:
                assert mapping[btn] != btn, f"Button {btn} was mapped to itself!"

    def test_map_button(self):
        randomizer = ButtonRandomizer(derangement_only=True)
        for btn in ALL_BUTTONS:
            mapped = randomizer.map_button(btn)
            assert mapped in ALL_BUTTONS
            assert mapped != btn

    def test_reset_to_identity(self):
        randomizer = ButtonRandomizer(derangement_only=True)
        identity = randomizer.reset_to_identity()
        assert identity == {b: b for b in ALL_BUTTONS}
        for btn in ALL_BUTTONS:
            assert randomizer.map_button(btn) == btn

    def test_summary_string(self):
        randomizer = ButtonRandomizer(derangement_only=True)
        summary = randomizer.get_summary_string()
        assert "L ➔" in summary
        assert "R ➔" in summary
        assert "M ➔" in summary

    def test_thread_safety(self):
        """Ensure concurrent reading and shuffling does not race or corrupt state."""
        randomizer = ButtonRandomizer(interval_seconds=10.0, derangement_only=True)
        errors = []

        def reader():
            for _ in range(100):
                try:
                    m = randomizer.get_mapping()
                    assert len(m) == 3
                    assert set(m.keys()) == set(ALL_BUTTONS)
                except Exception as e:
                    errors.append(e)

        def writer():
            for _ in range(50):
                try:
                    randomizer.shuffle()
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(5)]
        threads.extend([threading.Thread(target=writer) for _ in range(3)])

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_auto_shuffle_timer(self):
        """Verify the background auto-shuffle thread triggers updates."""
        updates = []
        randomizer = ButtonRandomizer(
            interval_seconds=0.1,
            derangement_only=True,
            on_change_callback=lambda m: updates.append(dict(m)),
        )
        assert not randomizer.auto_shuffle_enabled

        randomizer.start_auto_shuffle()
        assert randomizer.auto_shuffle_enabled

        # Wait briefly for at least 1 shuffle
        time.sleep(0.35)
        randomizer.stop_auto_shuffle()
        assert not randomizer.auto_shuffle_enabled
        assert len(updates) >= 1

    def test_default_interval_is_5_seconds(self):
        """Default auto-shuffle interval must be 5.0 seconds."""
        randomizer = ButtonRandomizer()
        assert randomizer.interval_seconds == 5.0



class TestMouseHookManagerStructures:
    def test_ctypes_struct_sizes(self):
        """Verify Windows ctypes structs have valid memory alignment."""
        assert ctypes.sizeof(INPUT) > 0
        assert ctypes.sizeof(MOUSEINPUT) > 0
        assert ctypes.sizeof(MSLLHOOKSTRUCT) > 0

    def test_event_decoding(self):
        randomizer = ButtonRandomizer()
        mgr = MouseHookManager(randomizer=randomizer)

        assert mgr._decode_mouse_event(WM_LBUTTONDOWN) == (ButtonType.LEFT, True)
        assert mgr._decode_mouse_event(WM_LBUTTONUP) == (ButtonType.LEFT, False)
        assert mgr._decode_mouse_event(WM_RBUTTONDOWN) == (ButtonType.RIGHT, True)
        assert mgr._decode_mouse_event(WM_RBUTTONUP) == (ButtonType.RIGHT, False)
        assert mgr._decode_mouse_event(WM_MBUTTONDOWN) == (ButtonType.MIDDLE, True)
        assert mgr._decode_mouse_event(WM_MBUTTONUP) == (ButtonType.MIDDLE, False)
        # Non-click messages return None
        assert mgr._decode_mouse_event(0x0200) is None  # WM_MOUSEMOVE

    def test_toggle_state(self):
        randomizer = ButtonRandomizer()
        mgr = MouseHookManager(randomizer=randomizer)

        assert not mgr.is_active
        mgr.set_active(True)
        assert mgr.is_active
        new_state = mgr.toggle()
        assert not new_state
        assert not mgr.is_active

    def test_toggle_repeatedly(self):
        """Ensure repeated toggling does not deadlock or corrupt state."""
        randomizer = ButtonRandomizer()
        mgr = MouseHookManager(randomizer=randomizer)

        for i in range(10):
            expected = (i % 2 == 0)
            res = mgr.toggle()
            assert res == expected
            assert mgr.is_active == expected

    def test_toggle_releases_active_buttons(self):
        """When Chaos Mode is turned off, any held synthetic buttons must be released."""
        randomizer = ButtonRandomizer()
        mgr = MouseHookManager(randomizer=randomizer)

        mgr.set_active(True)
        # Simulate active press held down
        mgr._active_presses[ButtonType.LEFT] = ButtonType.RIGHT
        mgr._active_presses[ButtonType.RIGHT] = ButtonType.LEFT

        # Toggle to inactive
        mgr.set_active(False)
        assert not mgr.is_active
        assert len(mgr._active_presses) == 0

        # Verify synthetic release events were queued
        released = []
        while not mgr._injection_queue.empty():
            released.append(mgr._injection_queue.get_nowait())

        assert (ButtonType.RIGHT, False) in released
        assert (ButtonType.LEFT, False) in released

    def test_recursion_constants(self):
        assert CHAOS_EXTRA_INFO == 0xC11C4CA0
        assert LLMHF_INJECTED == 0x00000001
        assert LLMHF_LOWER_IL_INJECTED == 0x00000002


class TestTrayUIAssets:
    def test_generate_tray_image(self):
        img_active = generate_tray_image(size=64, active=True)
        assert isinstance(img_active, Image.Image)
        assert img_active.size == (64, 64)
        assert img_active.mode == "RGBA"

        img_inactive = generate_tray_image(size=64, active=False)
        assert isinstance(img_inactive, Image.Image)
        assert img_inactive.size == (64, 64)
        assert img_inactive.mode == "RGBA"


class TestTrayUIBehavior:
    def test_tray_toggle_and_menu(self):
        randomizer = ButtonRandomizer()
        mgr = MouseHookManager(randomizer=randomizer)
        from src.tray_ui import TrayUI
        tray = TrayUI(randomizer=randomizer, hook_manager=mgr)

        assert not mgr.is_active
        # Trigger toggle via tray handler
        tray._toggle_chaos(icon=None, item=None)
        assert mgr.is_active

        tray._toggle_chaos(icon=None, item=None)
        assert not mgr.is_active

        # Verify dynamic menu can be built
        menu = tray._build_menu()
        assert menu is not None

        # Verify interval preset handler for 5 seconds
        set_5s_handler = tray._set_interval(5)
        set_5s_handler(icon=None, item=None)
        assert randomizer.interval_seconds == 5.0

    def test_tray_visual_updates_on_toggle(self):
        class DummyIcon:
            def __init__(self):
                self.icon = None
                self.title = ""
                self.menu_updated = False
            def update_menu(self):
                self.menu_updated = True

        randomizer = ButtonRandomizer()
        mgr = MouseHookManager(randomizer=randomizer)
        from src.tray_ui import TrayUI
        tray = TrayUI(randomizer=randomizer, hook_manager=mgr)
        dummy_icon = DummyIcon()
        tray._icon = dummy_icon

        # Initial state: inactive
        tray._update_icon_visual()
        assert "INACTIVE" in dummy_icon.title
        assert dummy_icon.icon == tray._inactive_icon_img

        # Toggle to active
        tray._toggle_chaos(icon=dummy_icon, item=None)
        assert mgr.is_active
        assert "ACTIVE" in dummy_icon.title
        assert dummy_icon.icon == tray._active_icon_img
        assert dummy_icon.menu_updated

        # Toggle back to inactive
        dummy_icon.menu_updated = False
        tray._toggle_chaos(icon=dummy_icon, item=None)
        assert not mgr.is_active
        assert "INACTIVE" in dummy_icon.title
        assert dummy_icon.icon == tray._inactive_icon_img
        assert dummy_icon.menu_updated

    def test_tray_public_shortcut_methods(self):
        randomizer = ButtonRandomizer()
        mgr = MouseHookManager(randomizer=randomizer)
        from src.tray_ui import TrayUI
        tray = TrayUI(randomizer=randomizer, hook_manager=mgr)

        assert not mgr.is_active
        # toggle_chaos
        tray.toggle_chaos()
        assert mgr.is_active

        # emergency_disable
        tray.emergency_disable()
        assert not mgr.is_active

        # toggle_button_mode
        initial_mode = randomizer.include_middle
        tray.toggle_button_mode()
        assert randomizer.include_middle != initial_mode

        # randomize_now
        m1 = randomizer.get_mapping()
        tray.randomize_now()
        # Ensure it shuffles without error
        assert len(randomizer.get_mapping()) == 3


class TestHotkeyManager:
    def test_hotkey_manager_lifecycle_and_dispatch(self):
        from src.hotkey_manager import HotkeyManager, WM_HOTKEY, user32

        calls = []

        hm = HotkeyManager(
            on_toggle_chaos=lambda: calls.append("toggle"),
            on_randomize=lambda: calls.append("randomize"),
            on_emergency_disable=lambda: calls.append("emergency"),
            on_toggle_middle=lambda: calls.append("middle"),
            on_exit=lambda: calls.append("exit"),
        )

        hm.start()
        assert hm._running
        assert hm._thread_id is not None

        # Post synthetic WM_HOTKEY messages to verify thread dispatch
        user32.PostThreadMessageW(hm._thread_id, WM_HOTKEY, HotkeyManager.HOTKEY_ID_TOGGLE_CHAOS, 0)
        user32.PostThreadMessageW(hm._thread_id, WM_HOTKEY, HotkeyManager.HOTKEY_ID_RANDOMIZE, 0)
        user32.PostThreadMessageW(hm._thread_id, WM_HOTKEY, HotkeyManager.HOTKEY_ID_EMERGENCY_DISABLE, 0)
        user32.PostThreadMessageW(hm._thread_id, WM_HOTKEY, HotkeyManager.HOTKEY_ID_TOGGLE_MIDDLE, 0)
        user32.PostThreadMessageW(hm._thread_id, WM_HOTKEY, HotkeyManager.HOTKEY_ID_EXIT, 0)

        time.sleep(0.2)
        hm.stop()
        assert not hm._running

        assert "toggle" in calls
        assert "randomize" in calls
        assert "emergency" in calls
        assert "middle" in calls
        assert "exit" in calls


