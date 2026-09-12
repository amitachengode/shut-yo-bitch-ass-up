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
    MOUSEEVENTF_XDOWN,
    MOUSEEVENTF_XUP,
    MOUSEINPUT,
    MSLLHOOKSTRUCT,
    WM_LBUTTONDOWN,
    WM_LBUTTONUP,
    WM_MBUTTONDOWN,
    WM_MBUTTONUP,
    WM_RBUTTONDOWN,
    WM_RBUTTONUP,
    WM_XBUTTONDOWN,
    WM_XBUTTONUP,
    XBUTTON1,
    XBUTTON2,
    MouseHookManager,
)
from src.randomizer import ALL_BUTTONS, STANDARD_BUTTONS, ButtonRandomizer, ButtonType
from src.tray_ui import generate_tray_image


class TestButtonRandomizer:
    def test_bijective_mapping_5_buttons(self):
        """Every generated mapping in 5-button mode must be a 1-to-1 bijection."""
        randomizer = ButtonRandomizer(derangement_only=False, include_middle=True, include_xbuttons=True)
        for _ in range(50):
            mapping = randomizer.generate_mapping()
            assert len(mapping) == 5
            assert set(mapping.keys()) == set(ALL_BUTTONS)
            assert set(mapping.values()) == set(ALL_BUTTONS)

    def test_derangement_mapping_5_buttons(self):
        """When derangement_only is True, all 5 active buttons must map to different buttons."""
        randomizer = ButtonRandomizer(derangement_only=True, include_middle=True, include_xbuttons=True)
        for _ in range(50):
            mapping = randomizer.generate_mapping()
            for btn in ALL_BUTTONS:
                assert mapping[btn] != btn, f"Button {btn} was mapped to itself!"

    def test_derangement_mapping_3_buttons(self):
        """In 3-button mode, Left, Right, Middle derange, while X buttons map to themselves."""
        randomizer = ButtonRandomizer(derangement_only=True, include_middle=True, include_xbuttons=False)
        for _ in range(30):
            mapping = randomizer.generate_mapping()
            for btn in STANDARD_BUTTONS:
                assert mapping[btn] != btn
            assert mapping[ButtonType.XBUTTON1] == ButtonType.XBUTTON1
            assert mapping[ButtonType.XBUTTON2] == ButtonType.XBUTTON2

    def test_derangement_mapping_2_buttons(self):
        """In 2-button mode, Left and Right swap, Middle and X buttons remain identity."""
        randomizer = ButtonRandomizer(derangement_only=True, include_middle=False, include_xbuttons=False)
        mapping = randomizer.generate_mapping()
        assert mapping[ButtonType.LEFT] == ButtonType.RIGHT
        assert mapping[ButtonType.RIGHT] == ButtonType.LEFT
        assert mapping[ButtonType.MIDDLE] == ButtonType.MIDDLE
        assert mapping[ButtonType.XBUTTON1] == ButtonType.XBUTTON1
        assert mapping[ButtonType.XBUTTON2] == ButtonType.XBUTTON2

    def test_short_names(self):
        assert ButtonType.LEFT.short_name == "L"
        assert ButtonType.RIGHT.short_name == "R"
        assert ButtonType.MIDDLE.short_name == "M"
        assert ButtonType.XBUTTON1.short_name == "X1"
        assert ButtonType.XBUTTON2.short_name == "X2"

    def test_map_button(self):
        randomizer = ButtonRandomizer(derangement_only=True, include_xbuttons=True)
        for btn in ALL_BUTTONS:
            mapped = randomizer.map_button(btn)
            assert mapped in ALL_BUTTONS
            assert mapped != btn

    def test_reset_to_identity(self):
        randomizer = ButtonRandomizer(derangement_only=True, include_xbuttons=True)
        identity = randomizer.reset_to_identity()
        assert identity == {b: b for b in ALL_BUTTONS}
        for btn in ALL_BUTTONS:
            assert randomizer.map_button(btn) == btn

    def test_summary_string(self):
        randomizer = ButtonRandomizer(derangement_only=True, include_xbuttons=True)
        summary = randomizer.get_summary_string()
        assert "L ➔" in summary
        assert "R ➔" in summary
        assert "M ➔" in summary
        assert "X1 ➔" in summary
        assert "X2 ➔" in summary

    def test_colored_summary_and_card(self):
        from src.randomizer import BUTTON_COLORS, RESET
        randomizer = ButtonRandomizer(derangement_only=True, include_xbuttons=True)
        col_summary = randomizer.get_colored_summary_string()
        assert RESET in col_summary
        for col in BUTTON_COLORS.values():
            assert col in col_summary

        card = randomizer.get_colored_mapping_card()
        assert "MOUSE BUTTONS RANDOMIZED" in card
        assert "Summary:" in card
        assert RESET in card

    def test_multiple_change_callbacks(self):
        randomizer = ButtonRandomizer(derangement_only=True, include_xbuttons=True)
        calls_a = []
        calls_b = []

        cb_a = lambda m: calls_a.append(len(m))
        cb_b = lambda m: calls_b.append(len(m))

        randomizer.add_change_callback(cb_a)
        randomizer.add_change_callback(cb_b)

        randomizer.shuffle()
        assert len(calls_a) >= 1
        assert len(calls_b) >= 1

        randomizer.remove_change_callback(cb_a)
        prev_a = len(calls_a)
        randomizer.shuffle()
        assert len(calls_a) == prev_a
        assert len(calls_b) >= 2

    def test_thread_safety(self):
        """Ensure concurrent reading and shuffling does not race or corrupt state."""
        randomizer = ButtonRandomizer(interval_seconds=10.0, derangement_only=True, include_xbuttons=True)
        errors = []

        def reader():
            for _ in range(100):
                try:
                    m = randomizer.get_mapping()
                    assert len(m) == 5
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

    def test_button_4_and_5_presence_detection(self):
        from src.randomizer import are_buttons_4_and_5_present, detect_mouse_button_count
        count = detect_mouse_button_count()
        assert isinstance(count, int)
        assert count >= 0
        has_x = are_buttons_4_and_5_present()
        assert has_x == (count >= 5)

        # When include_xbuttons is None (default), it automatically matches hardware presence
        rnd = ButtonRandomizer(include_xbuttons=None)
        assert rnd.include_xbuttons == has_x


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

        # XButton 1 (Mouse 4)
        data_x1 = XBUTTON1 << 16
        assert mgr._decode_mouse_event(WM_XBUTTONDOWN, data_x1) == (ButtonType.XBUTTON1, True)
        assert mgr._decode_mouse_event(WM_XBUTTONUP, data_x1) == (ButtonType.XBUTTON1, False)

        # XButton 2 (Mouse 5)
        data_x2 = XBUTTON2 << 16
        assert mgr._decode_mouse_event(WM_XBUTTONDOWN, data_x2) == (ButtonType.XBUTTON2, True)
        assert mgr._decode_mouse_event(WM_XBUTTONUP, data_x2) == (ButtonType.XBUTTON2, False)

        # Non-click messages return None
        assert mgr._decode_mouse_event(0x0200) is None  # WM_MOUSEMOVE

    def test_input_flags_and_data(self):
        randomizer = ButtonRandomizer()
        mgr = MouseHookManager(randomizer=randomizer)

        flags, data = mgr._get_input_flags_and_data(ButtonType.XBUTTON1, True)
        assert flags == MOUSEEVENTF_XDOWN
        assert data == XBUTTON1

        flags, data = mgr._get_input_flags_and_data(ButtonType.XBUTTON2, False)
        assert flags == MOUSEEVENTF_XUP
        assert data == XBUTTON2

    def test_toggle_state(self):
        randomizer = ButtonRandomizer()
        mgr = MouseHookManager(randomizer=randomizer)

        assert not mgr.is_active
        mgr.set_active(True)
        assert mgr.is_active
        new_state = mgr.toggle()
        assert not new_state
        assert not mgr.is_active

    def test_cursor_lock_state(self):
        randomizer = ButtonRandomizer()
        mgr = MouseHookManager(randomizer=randomizer)

        assert not mgr.is_cursor_locked
        res = mgr.lock_cursor()
        assert res is True
        assert mgr.is_cursor_locked

        res_unlock = mgr.unlock_cursor()
        assert res_unlock is True
        assert not mgr.is_cursor_locked

        # Toggle cursor lock
        toggled = mgr.toggle_cursor_lock()
        assert toggled is True
        assert mgr.is_cursor_locked

        toggled_off = mgr.toggle_cursor_lock()
        assert toggled_off is False
        assert not mgr.is_cursor_locked

    def test_teleport_mouse_state(self):
        randomizer = ButtonRandomizer()
        mgr = MouseHookManager(randomizer=randomizer)
        assert not mgr.is_teleport_enabled
        mgr.set_teleport_enabled(True)
        assert mgr.is_teleport_enabled
        mgr.toggle_teleport()
        assert not mgr.is_teleport_enabled

        rx, ry = mgr.teleport_cursor()
        assert rx >= 0
        assert ry >= 0

    def test_scroll_chaos_state(self):
        randomizer = ButtonRandomizer()
        mgr = MouseHookManager(randomizer=randomizer)
        assert mgr.is_scroll_chaos_enabled
        mgr.set_scroll_chaos_enabled(False)
        assert not mgr.is_scroll_chaos_enabled
        mgr.toggle_scroll_chaos()
        assert mgr.is_scroll_chaos_enabled

    def test_toggle_releases_active_buttons_and_unlocks_cursor(self):
        """When Chaos Mode is turned off, any held synthetic buttons must be released and cursor unlocked."""
        randomizer = ButtonRandomizer()
        mgr = MouseHookManager(randomizer=randomizer)

        mgr.set_active(True)
        mgr.lock_cursor()
        assert mgr.is_cursor_locked

        # Simulate active press held down
        mgr._active_presses[ButtonType.LEFT] = ButtonType.RIGHT
        mgr._active_presses[ButtonType.XBUTTON1] = ButtonType.XBUTTON2

        # Toggle to inactive
        mgr.set_active(False)
        assert not mgr.is_active
        assert not mgr.is_cursor_locked
        assert len(mgr._active_presses) == 0

        # Verify synthetic release events were queued
        released = []
        while not mgr._injection_queue.empty():
            released.append(mgr._injection_queue.get_nowait())

        assert (ButtonType.RIGHT, False) in released
        assert (ButtonType.XBUTTON2, False) in released

    def test_recursion_constants(self):
        assert CHAOS_EXTRA_INFO == 0xC11C4CA0
        assert LLMHF_INJECTED == 0x00000001
        assert LLMHF_LOWER_IL_INJECTED == 0x00000002


class TestTrayUIAssets:
    def test_generate_tray_image(self):
        img_active = generate_tray_image(size=64, active=True, locked=False)
        assert isinstance(img_active, Image.Image)
        assert img_active.size == (64, 64)
        assert img_active.mode == "RGBA"

        img_locked = generate_tray_image(size=64, active=True, locked=True)
        assert isinstance(img_locked, Image.Image)
        assert img_locked.size == (64, 64)
        assert img_locked.mode == "RGBA"

        img_inactive = generate_tray_image(size=64, active=False, locked=False)
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

        # Test cursor lock toggle
        assert not mgr.is_cursor_locked
        tray._toggle_cursor_lock(icon=None, item=None)
        assert mgr.is_cursor_locked
        tray._toggle_cursor_lock(icon=None, item=None)
        assert not mgr.is_cursor_locked

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

        # toggle_cursor_lock
        tray.toggle_cursor_lock()
        assert mgr.is_cursor_locked

        # emergency_disable
        tray.emergency_disable()
        assert not mgr.is_active
        assert not mgr.is_cursor_locked

        # toggle_button_mode cycling (5 -> 3 -> 2 -> 5)
        assert randomizer.include_middle and randomizer.include_xbuttons
        tray.toggle_button_mode()
        assert randomizer.include_middle and not randomizer.include_xbuttons
        tray.toggle_button_mode()
        assert not randomizer.include_middle and not randomizer.include_xbuttons
        tray.toggle_button_mode()
        assert randomizer.include_middle and randomizer.include_xbuttons

        # toggle_teleport & toggle_scroll_chaos
        assert not mgr.is_teleport_enabled
        tray.toggle_teleport()
        assert mgr.is_teleport_enabled

        assert mgr.is_scroll_chaos_enabled
        tray.toggle_scroll_chaos()
        assert not mgr.is_scroll_chaos_enabled

        # randomize_now
        tray.randomize_now()
        assert len(randomizer.get_mapping()) == 5


class TestHotkeyManager:
    def test_hotkey_manager_lifecycle_and_dispatch(self):
        from src.hotkey_manager import HotkeyManager, WM_HOTKEY, user32

        calls = []

        hm = HotkeyManager(
            on_toggle_chaos=lambda: calls.append("toggle"),
            on_randomize=lambda: calls.append("randomize"),
            on_emergency_disable=lambda: calls.append("emergency"),
            on_toggle_middle=lambda: calls.append("middle"),
            on_toggle_cursor_lock=lambda: calls.append("cursor_lock"),
            on_toggle_teleport=lambda: calls.append("teleport"),
            on_toggle_scroll=lambda: calls.append("scroll"),
            on_shuffle_hotkeys=lambda: calls.append("shuffle_hotkeys"),
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
        user32.PostThreadMessageW(hm._thread_id, WM_HOTKEY, HotkeyManager.HOTKEY_ID_TOGGLE_CURSOR_LOCK, 0)
        user32.PostThreadMessageW(hm._thread_id, WM_HOTKEY, HotkeyManager.HOTKEY_ID_TOGGLE_TELEPORT, 0)
        user32.PostThreadMessageW(hm._thread_id, WM_HOTKEY, HotkeyManager.HOTKEY_ID_TOGGLE_SCROLL, 0)
        user32.PostThreadMessageW(hm._thread_id, WM_HOTKEY, HotkeyManager.HOTKEY_ID_SHUFFLE_HOTKEYS, 0)
        user32.PostThreadMessageW(hm._thread_id, WM_HOTKEY, HotkeyManager.HOTKEY_ID_EXIT, 0)

        time.sleep(0.25)
        hm.stop()
        assert not hm._running

        assert "toggle" in calls
        assert "randomize" in calls
        assert "emergency" in calls
        assert "middle" in calls
        assert "cursor_lock" in calls
        assert "teleport" in calls
        assert "scroll" in calls
        assert "shuffle_hotkeys" in calls
        assert "exit" in calls

    def test_randomize_and_reset_action_hotkeys(self):
        from src.hotkey_manager import HotkeyManager

        hm = HotkeyManager()
        initial_configs = hm.get_active_configs()

        # Randomize action keys
        hm.randomize_action_hotkeys()
        new_configs = hm.get_active_configs()
        # Emergency disable and exit must remain intact
        assert hm._action_keys["emergency_disable"][1] == "X"
        assert hm._action_keys["exit"][1] == "Q"

        # Reset to defaults
        hm.reset_to_default_hotkeys()
        assert hm._action_keys == HotkeyManager.DEFAULT_ACTION_KEYS
