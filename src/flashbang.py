"""Flashbang chaos utility for ClickChaos.

Creates a blinding fullscreen pure white overlay across all monitors with maximum brightness
that gradually dims over time to simulate a flashbang detonation.
Includes click-through support (WS_EX_TRANSPARENT) so input is never blocked,
an optional high-pitch ear ringing audio effect, and a background random interval scheduler.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
from pathlib import Path
import random
import sys
import threading
import time
from typing import Optional

logger = logging.getLogger("ClickChaos.Flashbang")

DEFAULT_AUDIO_PATH = Path(__file__).resolve().parent.parent / "assets" / "audio" / "flashbang.mp3"

# Win32 Constants
WS_EX_TOPMOST = 0x00000008
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_POPUP = 0x80000000
LWA_ALPHA = 0x00000002
SW_SHOW = 5
SW_HIDE = 0

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

WM_DESTROY = 0x0002
WM_PAINT = 0x000F

LRESULT = ctypes.c_int64


class FlashbangManager:
    """Manages spawning flashbangs and scheduling them at random points in time."""

    def __init__(
        self,
        min_interval: float = 1.0,
        max_interval: float = 30.0,
        fade_duration: float = 3.0,
        sound_enabled: bool = True,
        audio_path: Optional[str | Path] = None,
        enabled: bool = True,
    ) -> None:
        """Initialize the FlashbangManager.

        :param min_interval: Minimum seconds between random flashbang detonations.
        :param max_interval: Maximum seconds between random flashbang detonations.
        :param fade_duration: Total duration in seconds for the flashbang to dim from full white to transparent.
        :param sound_enabled: Whether to play a flashbang sound / ringing tone.
        :param audio_path: Path to the audio file to play (defaults to assets/audio/flashbang.mp3).
        :param enabled: Whether the flashbang chaos is active.
        """
        self.min_interval = max(1.0, float(min_interval))
        self.max_interval = max(self.min_interval, float(max_interval))
        self.fade_duration = max(0.5, float(fade_duration))
        self.sound_enabled = sound_enabled
        self.audio_path = Path(audio_path) if audio_path is not None else DEFAULT_AUDIO_PATH
        self._enabled = enabled

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._timer_thread: Optional[threading.Thread] = None
        self._is_flashing = False

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        with self._lock:
            self._enabled = bool(value)
        logger.info("Flashbang chaos: %s", "ENABLED" if self._enabled else "DISABLED")

    def toggle(self) -> bool:
        """Toggle flashbang chaos enabled/disabled."""
        with self._lock:
            self._enabled = not self._enabled
            new_state = self._enabled
        logger.info("Flashbang chaos toggled: %s", "ENABLED" if new_state else "DISABLED")
        return new_state

    def trigger_flash(self, fade_duration: Optional[float] = None) -> None:
        """Trigger a flashbang overlay immediately in a background worker thread."""
        duration = fade_duration if fade_duration is not None else self.fade_duration
        worker = threading.Thread(
            target=self._run_flashbang_effect,
            args=(duration,),
            name="FlashbangWorker",
            daemon=True,
        )
        worker.start()

    def _play_sound(self) -> None:
        """Play flashbang MP3 audio or fallback high-pitch ear ringing."""
        if not self.sound_enabled or sys.platform != "win32":
            return

        # Attempt to play MP3 audio file via Windows multimedia MCI
        if self.audio_path and self.audio_path.is_file():
            try:
                winmm = ctypes.windll.winmm
                alias = f"fb_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
                cmd_open = f'open "{self.audio_path.resolve()}" type mpegvideo alias {alias}'
                res = winmm.mciSendStringW(cmd_open, None, 0, None)
                if res == 0:
                    winmm.mciSendStringW(f"play {alias} from 0", None, 0, None)

                    # Close the MCI alias after allowing sufficient time for playback
                    def _cleanup_mci(alias_name: str) -> None:
                        time.sleep(10.0)
                        try:
                            ctypes.windll.winmm.mciSendStringW(f"stop {alias_name}", None, 0, None)
                            ctypes.windll.winmm.mciSendStringW(f"close {alias_name}", None, 0, None)
                        except Exception:
                            pass

                    threading.Thread(target=_cleanup_mci, args=(alias,), daemon=True).start()
                    return
            except Exception as e:
                logger.debug("Failed to play MP3 audio with MCI: %s", e)

        # Fallback synthesized tinnitus ringing frequency
        try:
            import winsound
            winsound.Beep(2400, 70)
            winsound.Beep(4200, 300)
        except Exception:
            pass

    def _run_flashbang_effect(self, duration: float) -> None:
        """Render fullscreen white window across all monitors and smoothly dim."""
        with self._lock:
            if self._is_flashing:
                return
            self._is_flashing = True

        try:
            if sys.platform == "win32":
                self._run_win32_flashbang(duration)
            else:
                self._run_tk_flashbang(duration)
        finally:
            with self._lock:
                self._is_flashing = False

    def _run_win32_flashbang(self, duration: float) -> None:
        """Native Windows layered window for full multi-monitor click-through flashbang."""
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        kernel32 = ctypes.windll.kernel32

        # Configure 64-bit argument and return types
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = LRESULT
        WNDPROCTYPE = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        def _wnd_proc(hwnd, msg, wParam, lParam):
            if msg == WM_PAINT:
                ps = (ctypes.c_byte * 72)()
                hdc = user32.BeginPaint(hwnd, ps)
                rect = wintypes.RECT()
                user32.GetClientRect(hwnd, ctypes.byref(rect))
                hbrush = gdi32.GetStockObject(0)  # WHITE_BRUSH
                user32.FillRect(hdc, ctypes.byref(rect), hbrush)
                user32.EndPaint(hwnd, ps)
                return 0
            elif msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wParam, lParam)

        proc_ref = WNDPROCTYPE(_wnd_proc)

        class WNDCLASSEXW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROCTYPE),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HCURSOR),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
                ("hIconSm", wintypes.HICON),
            ]

        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE

        user32.RegisterClassExW.argtypes = [ctypes.c_void_p]
        user32.RegisterClassExW.restype = wintypes.ATOM

        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        user32.UnregisterClassW.restype = wintypes.BOOL

        h_instance = kernel32.GetModuleHandleW(None)
        class_name = f"ClickChaosFlashbang_{int(time.time() * 1000)}"

        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.style = 0x0002 | 0x0001
        wc.lpfnWndProc = proc_ref
        wc.hInstance = h_instance
        wc.hbrBackground = gdi32.GetStockObject(0)  # WHITE_BRUSH
        wc.lpszClassName = class_name
        user32.RegisterClassExW(ctypes.byref(wc))

        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND

        # Dimensions covering all connected monitors
        vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        if vw <= 0 or vh <= 0:
            vx, vy, vw, vh = 0, 0, 1920, 1080

        hwnd = user32.CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW,
            class_name,
            "ClickChaos Flashbang",
            WS_POPUP,
            vx, vy, vw, vh,
            None, None, h_instance, None,
        )

        if not hwnd:
            user32.UnregisterClassW(class_name, h_instance)
            return

        try:
            # Play audio ringing asynchronously
            threading.Thread(target=self._play_sound, daemon=True).start()

            # Display immediately at 100% maximum brightness
            user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
            user32.ShowWindow(hwnd, SW_SHOW)

            # Hold peak brightness briefly, then dim smoothly
            hold_time = min(0.35, duration * 0.2)
            dim_time = max(0.05, duration - hold_time)
            start_time = time.monotonic()

            msg = wintypes.MSG()
            PM_REMOVE = 0x0001

            while True:
                while user32.PeekMessageW(ctypes.byref(msg), hwnd, 0, 0, PM_REMOVE):
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))

                now = time.monotonic()
                elapsed = now - start_time
                if elapsed < hold_time:
                    alpha = 255
                else:
                    progress = (elapsed - hold_time) / dim_time
                    if progress >= 1.0:
                        break
                    # Non-linear easing (dissipating smoke/flash)
                    alpha = int(255 * ((1.0 - progress) ** 1.8))

                user32.SetLayeredWindowAttributes(hwnd, 0, max(0, min(255, alpha)), LWA_ALPHA)
                time.sleep(0.02)
        finally:
            user32.DestroyWindow(hwnd)
            user32.UnregisterClassW(class_name, h_instance)

    def _run_tk_flashbang(self, duration: float) -> None:
        """Fallback Tkinter fullscreen overlay for non-Windows systems."""
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            top = tk.Toplevel(root)
            top.title("ClickChaos Flashbang")
            top.config(bg="white")
            top.attributes("-topmost", True)
            top.attributes("-fullscreen", True)
            top.attributes("-alpha", 1.0)
            top.overrideredirect(True)

            start = time.monotonic()
            hold = 0.35
            fade = max(0.5, duration - hold)

            def fade_step():
                elapsed = time.monotonic() - start
                if elapsed < hold:
                    top.attributes("-alpha", 1.0)
                else:
                    progress = (elapsed - hold) / fade
                    if progress >= 1.0:
                        top.destroy()
                        root.destroy()
                        return
                    top.attributes("-alpha", max(0.0, (1.0 - progress) ** 1.8))
                top.after(25, fade_step)

            top.after(25, fade_step)
            root.mainloop()
        except Exception as e:
            logger.debug("Tk flashbang error: %s", e)

    def start_scheduler(self) -> None:
        """Start the background scheduler that detonates flashbangs at random intervals."""
        if self._timer_thread and self._timer_thread.is_alive():
            return

        self._stop_event.clear()

        def _worker() -> None:
            while not self._stop_event.is_set():
                interval = random.uniform(self.min_interval, self.max_interval)
                if self._stop_event.wait(timeout=interval):
                    break

                if self.enabled:
                    logger.info("💥 Flashbang detonated! Screen blinded with maximum brightness.")
                    self.trigger_flash()

        self._timer_thread = threading.Thread(
            target=_worker, name="ClickChaosFlashbangScheduler", daemon=True
        )
        self._timer_thread.start()

    def stop_scheduler(self) -> None:
        """Stop the background flashbang scheduler."""
        self._stop_event.set()
        if self._timer_thread and self._timer_thread.is_alive():
            self._timer_thread.join(timeout=1.0)
        self._timer_thread = None
