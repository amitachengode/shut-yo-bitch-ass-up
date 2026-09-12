"""Tests for the stuck cursor popup notification overlay."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from src.popup import StuckPopup, show_stuck_popup, dismiss_stuck_popup


class TestStuckPopup:
    def test_stuck_popup_initialization(self):
        popup = StuckPopup()
        assert popup._proc is None

    def test_dismiss_when_no_process(self):
        popup = StuckPopup()
        # Dismissing without an active process should not throw
        popup.dismiss()

    def test_dismiss_with_active_process(self):
        popup = StuckPopup()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        popup._proc = mock_proc
        popup.dismiss()
        mock_proc.terminate.assert_called_once()

    def test_show_spawns_subprocess(self):
        popup = StuckPopup()
        with patch("subprocess.Popen") as mock_popen:
            popup.show("K")
            mock_popen.assert_called_once()
            args, kwargs = mock_popen.call_args
            cmd = args[0]
            assert cmd[-1] == "K"

    def test_convenience_functions(self):
        with patch("src.popup._global_popup.show") as mock_show, \
             patch("src.popup._global_popup.dismiss") as mock_dismiss:
            show_stuck_popup("Z")
            mock_show.assert_called_once_with("Z")
            dismiss_stuck_popup()
            mock_dismiss.assert_called_once()
