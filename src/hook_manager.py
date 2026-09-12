"""Low-level Windows mouse hook and synthetic input injection for ClickChaos.

Intercepts system-wide mouse events using WH_MOUSE_LL, suppresses the original
hardware events, and injects mapped synthetic clicks and scroll events asynchronously.
Supports Left, Right, Middle, XButton1/XButton2 mouse hotkeys, cursor locking,
mouse teleportation, and scroll wheel inversion/randomization.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import queue
import random
import threading
import time
from typing import Any, Callable, Dict, Optional, Set

from src.randomizer import ButtonRandomizer, ButtonType

logger = logging.getLogger("ClickChaos.HookManager")

# --- Windows Constants ---
WH_MOUSE_LL = 14
WM_QUIT = 0x0012

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_MOUSEWHEEL = 0x020A
WM_MOUSEHWHEEL = 0x020E

CLICK_MESSAGES = {
    WM_LBUTTONDOWN,
    WM_LBUTTONUP,
    WM_RBUTTONDOWN,
    WM_RBUTTONUP,
    WM_MBUTTONDOWN,
    WM_MBUTTONUP,
    WM_XBUTTONDOWN,
    WM_XBUTTONUP,
}

SCROLL_MESSAGES = {
    WM_MOUSEWHEEL,
    WM_MOUSEHWHEEL,
}

# LLMHF Flags
LLMHF_INJECTED = 0x00000001
LLMHF_LOWER_IL_INJECTED = 0x00000002

# SendInput / mouse_event Constants
INPUT_MOUSE = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000

XBUTTON1 = 0x0001
XBUTTON2 = 0x0002

SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

# Custom signature to tag ClickChaos injected events
CHAOS_EXTRA_INFO = 0xC11C4CA0

# Types
LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


# --- Windows Structs ---
class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


PMSLLHOOKSTRUCT = ctypes.POINTER(MSLLHOOKSTRUCT)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _INPUTunion(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", _INPUTunion),
    ]


# --- Load Win32 API Functions ---
if hasattr(ctypes, "windll"):
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    kernel32.GetCurrentThreadId.argtypes = []

    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    user32.SetWindowsHookExW.argtypes = [
        ctypes.c_int,
        HOOKPROC,
        wintypes.HINSTANCE,
        wintypes.DWORD,
    ]

    user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]

    user32.CallNextHookEx.restype = LRESULT
    user32.CallNextHookEx.argtypes = [
        wintypes.HHOOK,
        ctypes.c_int,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]

    user32.SendInput.restype = wintypes.UINT
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]

    user32.mouse_event.restype = None
    user32.mouse_event.argtypes = [
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ULONG_PTR,
    ]

    user32.GetMessageW.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
    ]

    user32.PostThreadMessageW.restype = wintypes.BOOL
    user32.PostThreadMessageW.argtypes = [
        wintypes.DWORD,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]

    user32.GetCursorPos.restype = wintypes.BOOL
    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]

    user32.SetCursorPos.restype = wintypes.BOOL
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]

    user32.ClipCursor.restype = wintypes.BOOL
    user32.ClipCursor.argtypes = [ctypes.POINTER(RECT)]

    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
else:
    user32 = None
    kernel32 = None


class MouseHookManager:
    """Manages low-level mouse hooks, event filtering, cursor locking, teleportation, and synthetic injection."""

    def __init__(self, randomizer: ButtonRandomizer) -> None:
        self.randomizer = randomizer
        self._is_active = False
        self._is_cursor_locked = False
        self._is_teleport_enabled = False
        self._is_scroll_chaos_enabled = True

        self._lock = threading.RLock()

        self._hook_handle: Optional[wintypes.HHOOK] = None
        self._hook_thread: Optional[threading.Thread] = None
        self._hook_thread_id: Optional[int] = None
        self._ready_event = threading.Event()
        self._running = False

        # Decoupled injection queue supporting clicks, scroll, and teleportation
        self._injection_queue: queue.SimpleQueue[Any] = queue.SimpleQueue()
        self._injector_thread: Optional[threading.Thread] = None

        # Store callback reference to prevent Python garbage collection
        self._hook_proc = HOOKPROC(self._low_level_mouse_proc)

        # Track active physical button presses to map DOWN and UP coherently
        self._active_presses: Dict[ButtonType, ButtonType] = {}

        self._click_count = 0
        self._locked_pos: Optional[tuple[int, int]] = None
        self._on_stuck_callback: Optional[Callable[[], None]] = None

    def set_on_stuck_callback(self, callback: Callable[[], None]) -> None:
        with self._lock:
            self._on_stuck_callback = callback

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._is_active

    @property
    def is_cursor_locked(self) -> bool:
        with self._lock:
            return self._is_cursor_locked

    @property
    def is_teleport_enabled(self) -> bool:
        with self._lock:
            return self._is_teleport_enabled

    def set_teleport_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._is_teleport_enabled = bool(enabled)
            logger.info("Mouse Teleportation: %s", "ENABLED" if enabled else "DISABLED")

    def toggle_teleport(self) -> bool:
        """Toggle mouse teleportation on/off."""
        with self._lock:
            self._is_teleport_enabled = not self._is_teleport_enabled
            new_state = self._is_teleport_enabled
        logger.info("Mouse Teleportation toggled: %s", "ENABLED" if new_state else "DISABLED")
        return new_state

    def teleport_cursor(self) -> tuple[int, int]:
        """Teleport mouse cursor to a random screen coordinate across all monitors."""
        with self._lock:
            if self._is_cursor_locked:
                if self._locked_pos:
                    return self._locked_pos
                return (0, 0)

        vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        if vw <= 0 or vh <= 0:
            vx, vy, vw, vh = 0, 0, user32.GetSystemMetrics(SM_CXSCREEN), user32.GetSystemMetrics(SM_CYSCREEN)
        if vw <= 0:
            vw = 1920
        if vh <= 0:
            vh = 1080

        rx = random.randint(vx + 50, max(vx + 50, vx + vw - 50))
        ry = random.randint(vy + 50, max(vy + 50, vy + vh - 50))
        user32.SetCursorPos(rx, ry)
        logger.info("🌀 Mouse cursor teleported to (%d, %d)", rx, ry)
        return (rx, ry)

    @property
    def is_scroll_chaos_enabled(self) -> bool:
        with self._lock:
            return self._is_scroll_chaos_enabled

    def set_scroll_chaos_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._is_scroll_chaos_enabled = bool(enabled)
            logger.info("Scroll Wheel Chaos: %s", "ENABLED" if enabled else "DISABLED")

    def toggle_scroll_chaos(self) -> bool:
        """Toggle scroll wheel inversion on/off."""
        with self._lock:
            self._is_scroll_chaos_enabled = not self._is_scroll_chaos_enabled
            new_state = self._is_scroll_chaos_enabled
        logger.info("Scroll Wheel Chaos toggled: %s", "ENABLED" if new_state else "DISABLED")
        return new_state

    def lock_cursor(self) -> bool:
        """Freeze/lock the mouse cursor at its current screen coordinate."""
        with self._lock:
            pt = POINT(0, 0)
            user32.GetCursorPos(ctypes.byref(pt))
            self._locked_pos = (pt.x, pt.y)
            rect = RECT(pt.x, pt.y, pt.x + 1, pt.y + 1)
            success = bool(user32.ClipCursor(ctypes.byref(rect)))
            self._is_cursor_locked = True
            logger.info("Cursor locked at (%d, %d) (ClipCursor=%s)", pt.x, pt.y, success)
            return True

    def unlock_cursor(self) -> bool:
        """Release any active cursor lock, restoring free movement."""
        with self._lock:
            self._locked_pos = None
            user32.ClipCursor(None)
            self._is_cursor_locked = False
            logger.info("Cursor unlocked.")
            return True

    def toggle_cursor_lock(self) -> bool:
        """Toggle cursor locking state."""
        with self._lock:
            if self._is_cursor_locked:
                self.unlock_cursor()
                return False
            else:
                self.lock_cursor()
                return True

    def set_active(self, active: bool) -> None:
        """Toggle Chaos Mode ON or OFF."""
        with self._lock:
            if self._is_active == active:
                return
            self._is_active = active
            logger.info("Chaos Mode toggled: %s", "ACTIVE" if active else "INACTIVE")

            if not active:
                self._release_all_active_synthetic_buttons()
                if self._is_cursor_locked:
                    self.unlock_cursor()

    def toggle(self) -> bool:
        """Toggle the active state and return the new state."""
        with self._lock:
            new_state = not self._is_active
        self.set_active(new_state)
        return new_state

    def start(self) -> None:
        """Start the decoupled injector worker and low-level hook threads."""
        if self._running:
            return

        self._running = True
        self._ready_event.clear()

        # 1. Dedicated asynchronous input injection worker
        self._injector_thread = threading.Thread(
            target=self._run_injector_loop,
            name="ClickChaosInjectorThread",
            daemon=True,
        )
        self._injector_thread.start()

        # 2. Low-level hook message loop
        self._hook_thread = threading.Thread(
            target=self._run_hook_loop,
            name="ClickChaosHookThread",
            daemon=True,
        )
        self._hook_thread.start()

        if not self._ready_event.wait(timeout=5.0):
            logger.error("Timed out waiting for mouse hook to register.")

    def stop(self) -> None:
        """Stop the low-level hook thread, worker, and unhook."""
        if not self._running:
            return

        self._running = False
        self.set_active(False)
        self.unlock_cursor()
        self.set_teleport_enabled(False)

        # Signal injector thread to exit
        self._injection_queue.put(None)
        if self._injector_thread and self._injector_thread.is_alive():
            self._injector_thread.join(timeout=1.0)
        self._injector_thread = None

        # Signal hook message loop to exit
        if self._hook_thread_id:
            user32.PostThreadMessageW(self._hook_thread_id, WM_QUIT, 0, 0)

        if self._hook_thread and self._hook_thread.is_alive():
            self._hook_thread.join(timeout=2.0)

        self._hook_thread = None
        self._hook_thread_id = None

    def _run_injector_loop(self) -> None:
        """Dedicated high-priority worker for dispatching synthetic mouse events."""
        while self._running:
            try:
                item = self._injection_queue.get()
                if item is None:
                    break

                if isinstance(item, tuple) and len(item) == 3 and item[0] == "SCROLL":
                    _, delta, is_horizontal = item
                    self._inject_scroll_input(delta, is_horizontal)
                elif isinstance(item, tuple) and len(item) == 3 and item[0] == "TELEPORT":
                    self.teleport_cursor()
                else:
                    button, is_down = item
                    self._inject_mouse_input(button, is_down)
            except Exception as e:
                logger.error("Error in injector worker: %s", e)

    def _run_hook_loop(self) -> None:
        """Thread loop running GetMessage for WH_MOUSE_LL."""
        self._hook_thread_id = kernel32.GetCurrentThreadId()
        h_mod = kernel32.GetModuleHandleW(None)

        self._hook_handle = user32.SetWindowsHookExW(
            WH_MOUSE_LL,
            self._hook_proc,
            h_mod,
            0,
        )

        if not self._hook_handle:
            err = ctypes.GetLastError()
            logger.error("Failed to install WH_MOUSE_LL hook. Error code: %d", err)
            self._ready_event.set()
            return

        logger.debug("WH_MOUSE_LL hook installed successfully.")
        self._ready_event.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        if self._hook_handle:
            user32.UnhookWindowsHookEx(self._hook_handle)
            self._hook_handle = None
            logger.info("WH_MOUSE_LL hook removed.")

    def _low_level_mouse_proc(self, nCode: int, wParam: int, lParam: int) -> int:
        """Low-level mouse hook procedure."""
        if nCode < 0:
            return user32.CallNextHookEx(self._hook_handle, nCode, wParam, lParam)

        try:
            is_move = (wParam == WM_MOUSEMOVE)
            is_click = wParam in CLICK_MESSAGES
            is_scroll = wParam in SCROLL_MESSAGES

            # Fast path: Non-move, non-click, and non-scroll events pass through instantly
            if not is_move and not is_click and not is_scroll:
                return user32.CallNextHookEx(self._hook_handle, nCode, wParam, lParam)

            hook_struct = ctypes.cast(lParam, PMSLLHOOKSTRUCT).contents

            # Recursion check
            is_injected = bool(hook_struct.flags & (LLMHF_INJECTED | LLMHF_LOWER_IL_INJECTED))
            is_our_event = (hook_struct.dwExtraInfo == CHAOS_EXTRA_INFO)

            if is_injected or is_our_event:
                return user32.CallNextHookEx(self._hook_handle, nCode, wParam, lParam)

            # Enforce Cursor Lock: If cursor is locked, strictly freeze it and block input
            with self._lock:
                locked = self._is_cursor_locked
                locked_pos = self._locked_pos

            if locked:
                if locked_pos:
                    lx, ly = locked_pos
                    rect = RECT(lx, ly, lx + 1, ly + 1)
                    user32.ClipCursor(ctypes.byref(rect))
                    user32.SetCursorPos(lx, ly)
                return 1

            # Fast path: Mouse movement passes through when not locked
            if is_move:
                return user32.CallNextHookEx(self._hook_handle, nCode, wParam, lParam)

            # If Chaos Mode is not active, let clicks and scrolls pass through
            if not self._is_active:
                return user32.CallNextHookEx(self._hook_handle, nCode, wParam, lParam)

            # Handle Scroll Wheel Events
            if is_scroll:
                if not self._is_scroll_chaos_enabled:
                    return user32.CallNextHookEx(self._hook_handle, nCode, wParam, lParam)

                raw_delta = ctypes.c_short((hook_struct.mouseData >> 16) & 0xFFFF).value
                # Invert scroll direction (pure chaos: down scrolls up, up scrolls down)
                inverted_delta = -raw_delta
                is_horizontal = (wParam == WM_MOUSEHWHEEL)
                self._injection_queue.put(("SCROLL", inverted_delta, is_horizontal))
                return 1

            # Handle Click Messages
            event_info = self._decode_mouse_event(wParam, hook_struct.mouseData)
            if event_info is None:
                return user32.CallNextHookEx(self._hook_handle, nCode, wParam, lParam)

            phys_button, is_down = event_info

            # Map button and track state
            with self._lock:
                if is_down:
                    target_button = self.randomizer.map_button(phys_button)
                    self._active_presses[phys_button] = target_button

                    self._click_count += 1
                    if self._click_count % 5 == 0:
                        self.lock_cursor()
                        if self._on_stuck_callback:
                            # Call asynchronously to not block the low level hook thread
                            threading.Thread(target=self._on_stuck_callback, daemon=True).start()
                        # Do not teleport or inject synthetic click when cursor is now locked
                        return 1

                    # If teleportation is enabled, teleport cursor on non-locking click down
                    if self._is_teleport_enabled:
                        self._injection_queue.put(("TELEPORT", 0, 0))
                else:
                    target_button = self._active_presses.pop(
                        phys_button, self.randomizer.map_button(phys_button)
                    )

            self._injection_queue.put((target_button, is_down))
            return 1
        except Exception as e:
            logger.debug("Error in _low_level_mouse_proc: %s", e)
            return user32.CallNextHookEx(self._hook_handle, nCode, wParam, lParam)

    def _decode_mouse_event(self, wParam: int, mouseData: int = 0) -> Optional[tuple[ButtonType, bool]]:
        """Map Windows message and mouseData to (ButtonType, is_down). Returns None for non-clicks."""
        if wParam == WM_LBUTTONDOWN:
            return (ButtonType.LEFT, True)
        elif wParam == WM_LBUTTONUP:
            return (ButtonType.LEFT, False)
        elif wParam == WM_RBUTTONDOWN:
            return (ButtonType.RIGHT, True)
        elif wParam == WM_RBUTTONUP:
            return (ButtonType.RIGHT, False)
        elif wParam == WM_MBUTTONDOWN:
            return (ButtonType.MIDDLE, True)
        elif wParam == WM_MBUTTONUP:
            return (ButtonType.MIDDLE, False)
        elif wParam in (WM_XBUTTONDOWN, WM_XBUTTONUP):
            is_down = (wParam == WM_XBUTTONDOWN)
            xbtn = (mouseData >> 16) & 0xFFFF
            if xbtn == XBUTTON2 or xbtn == 2:
                return (ButtonType.XBUTTON2, is_down)
            else:
                return (ButtonType.XBUTTON1, is_down)
        return None

    def _get_input_flags_and_data(self, button: ButtonType, is_down: bool) -> tuple[int, int]:
        """Return (flags, mouseData) for the specified button action."""
        if button == ButtonType.LEFT:
            return (MOUSEEVENTF_LEFTDOWN if is_down else MOUSEEVENTF_LEFTUP, 0)
        elif button == ButtonType.RIGHT:
            return (MOUSEEVENTF_RIGHTDOWN if is_down else MOUSEEVENTF_RIGHTUP, 0)
        elif button == ButtonType.MIDDLE:
            return (MOUSEEVENTF_MIDDLEDOWN if is_down else MOUSEEVENTF_MIDDLEUP, 0)
        elif button == ButtonType.XBUTTON1:
            return (MOUSEEVENTF_XDOWN if is_down else MOUSEEVENTF_XUP, XBUTTON1)
        elif button == ButtonType.XBUTTON2:
            return (MOUSEEVENTF_XDOWN if is_down else MOUSEEVENTF_XUP, XBUTTON2)
        return (0, 0)

    def _get_input_flags(self, button: ButtonType, is_down: bool) -> int:
        """Backwards-compatible helper returning just flags."""
        flags, _ = self._get_input_flags_and_data(button, is_down)
        return flags

    def _inject_mouse_input(self, button: ButtonType, is_down: bool) -> None:
        """Send synthetic mouse input with custom extra info."""
        flags, mouse_data = self._get_input_flags_and_data(button, is_down)
        if not flags:
            return

        try:
            user32.mouse_event(flags, 0, 0, mouse_data, CHAOS_EXTRA_INFO)
        except Exception:
            inp = INPUT()
            inp.type = INPUT_MOUSE
            inp.mi.dx = 0
            inp.mi.dy = 0
            inp.mi.mouseData = mouse_data
            inp.mi.dwFlags = flags
            inp.mi.time = 0
            inp.mi.dwExtraInfo = CHAOS_EXTRA_INFO
            user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    def _inject_scroll_input(self, delta: int, is_horizontal: bool = False) -> None:
        """Inject synthetic scroll wheel event with custom extra info."""
        flags = MOUSEEVENTF_HWHEEL if is_horizontal else MOUSEEVENTF_WHEEL
        try:
            user32.mouse_event(flags, 0, 0, ctypes.c_uint(delta & 0xFFFFFFFF).value, CHAOS_EXTRA_INFO)
        except Exception:
            inp = INPUT()
            inp.type = INPUT_MOUSE
            inp.mi.dx = 0
            inp.mi.dy = 0
            inp.mi.mouseData = delta & 0xFFFFFFFF
            inp.mi.dwFlags = flags
            inp.mi.time = 0
            inp.mi.dwExtraInfo = CHAOS_EXTRA_INFO
            user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    def _release_all_active_synthetic_buttons(self) -> None:
        """Release all synthetic buttons currently marked as pressed down."""
        with self._lock:
            for phys_btn, target_btn in list(self._active_presses.items()):
                self._injection_queue.put((target_btn, False))
            self._active_presses.clear()
