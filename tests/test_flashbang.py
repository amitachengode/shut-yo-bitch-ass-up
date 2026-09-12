"""Dedicated test suite for the Flashbang chaos module."""

from __future__ import annotations

import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from src.flashbang import FlashbangManager
from src.tray_ui import TrayUI
from src.randomizer import ButtonRandomizer
from src.hook_manager import MouseHookManager


class TestFlashbangSuite:
    """Comprehensive unit tests for FlashbangManager and tray integration."""

    def test_default_initialization(self):
        """Test default values and initialization."""
        fm = FlashbangManager()
        assert fm.min_interval == 1.0
        assert fm.max_interval == 10.0
        assert fm.fade_duration == 3.0
        assert fm.sound_enabled is True
        assert fm.enabled is True
        assert not fm._is_flashing

    def test_custom_initialization_and_clamping(self):
        """Test custom configuration and input clamping (min bounds)."""
        # min_interval is clamped to at least 1.0s, fade_duration to at least 0.5s
        fm = FlashbangManager(
            min_interval=0.2,
            max_interval=0.5,
            fade_duration=0.1,
            sound_enabled=False,
            enabled=False,
        )
        assert fm.min_interval == 1.0
        assert fm.max_interval == 1.0  # max_interval clamped to >= min_interval
        assert fm.fade_duration == 0.5
        assert fm.sound_enabled is False
        assert fm.enabled is False

    def test_toggle_state(self):
        """Test toggle switches enabled state back and forth."""
        fm = FlashbangManager(enabled=True)
        assert fm.enabled is True

        res1 = fm.toggle()
        assert res1 is False
        assert fm.enabled is False

        res2 = fm.toggle()
        assert res2 is True
        assert fm.enabled is True

        fm.enabled = False
        assert fm.enabled is False

    def test_scheduler_lifecycle(self):
        """Test starting, stopping, and idempotent restarts of the background scheduler."""
        fm = FlashbangManager(min_interval=10.0, max_interval=20.0, sound_enabled=False)
        assert fm._timer_thread is None

        fm.start_scheduler()
        assert fm._timer_thread is not None
        assert fm._timer_thread.is_alive()
        assert not fm._stop_event.is_set()

        # Starting again should be a no-op and keep existing thread alive
        existing_thread = fm._timer_thread
        fm.start_scheduler()
        assert fm._timer_thread is existing_thread

        # Stop scheduler cleanly
        fm.stop_scheduler()
        assert fm._stop_event.is_set()
        assert fm._timer_thread is None

        # Stopping again should be safe
        fm.stop_scheduler()
        assert fm._timer_thread is None

    def test_scheduler_trigger_execution(self):
        """Test that the scheduler triggers a flashbang when enabled."""
        fm = FlashbangManager(min_interval=3.0, max_interval=3.0, sound_enabled=False, enabled=True)

        with patch.object(fm, "trigger_flash") as mock_trigger:
            # We mock uniform to return a tiny timeout so the loop fires immediately
            with patch("random.uniform", return_value=0.05):
                fm.start_scheduler()
                time.sleep(0.15)
                fm.stop_scheduler()

            assert mock_trigger.call_count >= 1

    def test_scheduler_does_not_trigger_when_disabled(self):
        """Test that the scheduler respects enabled=False and skips flashbangs."""
        fm = FlashbangManager(min_interval=3.0, max_interval=3.0, sound_enabled=False, enabled=False)

        with patch.object(fm, "trigger_flash") as mock_trigger:
            with patch("random.uniform", return_value=0.05):
                fm.start_scheduler()
                time.sleep(0.15)
                fm.stop_scheduler()

            assert mock_trigger.call_count == 0

    def test_trigger_flash_worker_concurrency_lock(self):
        """Test that overlapping flashbang triggers are guarded by _is_flashing."""
        fm = FlashbangManager(fade_duration=0.5, sound_enabled=False)

        executed = 0
        def fake_effect(duration: float):
            nonlocal executed
            executed += 1
            time.sleep(0.1)

        with patch.object(fm, "_run_win32_flashbang", side_effect=fake_effect), \
             patch.object(fm, "_run_tk_flashbang", side_effect=fake_effect):
            # Fire first flash
            t1 = threading.Thread(target=fm._run_flashbang_effect, args=(0.1,))
            t2 = threading.Thread(target=fm._run_flashbang_effect, args=(0.1,))
            t1.start()
            time.sleep(0.01)  # Ensure t1 acquires the lock and sets _is_flashing
            t2.start()
            t1.join()
            t2.join()

            # Second trigger should have been skipped because first was in progress
            assert executed == 1
            assert not fm._is_flashing

    def test_sound_playback_mp3(self):
        """Test sound playback attempts to play MP3 audio on Windows via MCI."""
        fm = FlashbangManager(sound_enabled=True)
        if sys.platform == "win32":
            with patch("ctypes.windll.winmm.mciSendStringW", return_value=0) as mock_mci:
                fm._play_sound()
                assert mock_mci.call_count >= 2  # open and play
        else:
            fm._play_sound()

    def test_sound_playback_fallback_beep(self):
        """Test sound playback falls back to winsound.Beep if MP3 is missing."""
        fm = FlashbangManager(sound_enabled=True, audio_path="nonexistent_audio.mp3")
        if sys.platform == "win32":
            with patch("winsound.Beep") as mock_beep:
                fm._play_sound()
                assert mock_beep.call_count == 2
        else:
            fm._play_sound()

    def test_sound_disabled(self):
        """Test sound playback is skipped when sound_enabled is False."""
        fm = FlashbangManager(sound_enabled=False)
        with patch("winsound.Beep", create=True) as mock_beep:
            fm._play_sound()
            mock_beep.assert_not_called()

    def test_real_flashbang_execution_win32(self):
        """Test real execution of the Win32 flashbang overlay with a micro duration."""
        if sys.platform != "win32":
            pytest.skip("Win32 test only")

        fm = FlashbangManager(sound_enabled=False)
        # Detonate with 0.05s fade duration to verify window creation, dimming, and cleanup
        fm._run_win32_flashbang(duration=0.05)
        assert not fm._is_flashing

    def test_tray_integration(self):
        """Test TrayUI interaction with FlashbangManager."""
        randomizer = ButtonRandomizer()
        hook_mgr = MouseHookManager(randomizer=randomizer)
        flashbang_mgr = FlashbangManager(enabled=True)

        tray = TrayUI(
            randomizer=randomizer,
            hook_manager=hook_mgr,
            flashbang_manager=flashbang_mgr,
        )

        assert tray.flashbang_manager is flashbang_mgr

        # Test toggle via TrayUI
        assert tray.toggle_flashbang() is False
        assert flashbang_mgr.enabled is False
        assert tray.toggle_flashbang() is True
        assert flashbang_mgr.enabled is True

        # Test trigger via TrayUI
        with patch.object(flashbang_mgr, "trigger_flash") as mock_trigger:
            tray.trigger_flashbang_now()
            mock_trigger.assert_called_once()
