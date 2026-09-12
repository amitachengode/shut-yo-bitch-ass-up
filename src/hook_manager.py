"""Low-level Windows mouse hook and synthetic input injection for ClickChaos.

Intercepts system-wide mouse events using WH_MOUSE_LL, suppresses the original
hardware events, and injects mapped synthetic clicks asynchronously.
Decoupled architecture prevents Windows LowLevelHooksTimeout cursor freezes.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import queue
import threading
import time
from typing import Callable, Dict, Optional, Set

from src.randomizer import ButtonRandomizer, ButtonType

logger = logging.getLogger("ClickChaos.HookManager")

# --- Windows Constants ---
WH_MOUSE_LL = 14
WM_QUIT = 0x0012

# Mouse Window Messages
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208

CLICK_MESSAGES = {
    WM_LBUTTONDOWN,
    WM_LBUTTONUP,
    WM_RBUTTONDOWN,
    WM_RBUTTONUP,
    WM_MBUTTONDOWN,
    WM_MBUTTONUP,
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

# Custom signature to tag ClickChaos injected events
CHAOS_EXTRA_INFO = 0xC11C4CA0

# Types
LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


# --- Windows Structs ---
class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


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


class MouseHookManager:
    """Manages low-level mouse hooks, event filtering, and asynchronous input injection."""

    def __init__(self, randomizer: ButtonRandomizer) -> None:
        self.randomizer = randomizer
        self._is_active = False
        self._lock = threading.RLock()

        self._hook_handle: Optional[wintypes.HHOOK] = None
        self._hook_thread: Optional[threading.Thread] = None
        self._hook_thread_id: Optional[int] = None
        self._ready_event = threading.Event()
        self._running = False

        # Decoupled injection queue to guarantee the hook callback returns in microseconds
        self._injection_queue: queue.SimpleQueue[Optional[tuple[ButtonType, bool]]] = (
            queue.SimpleQueue()
        )
        self._injector_thread: Optional[threading.Thread] = None

        # Store callback reference to prevent Python garbage collection
        self._hook_proc = HOOKPROC(self._low_level_mouse_proc)

        # Track active physical button presses to map DOWN and UP coherently
        self._active_presses: Dict[ButtonType, ButtonType] = {}

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._is_active

    def set_active(self, active: bool) -> None:
        """Toggle Chaos Mode ON or OFF."""
        with self._lock:
            if self._is_active == active:
                return
            self._is_active = active
            logger.info("Chaos Mode toggled: %s", "ACTIVE" if active else "INACTIVE")

            if not active:
                self._release_all_active_synthetic_buttons()

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

        # 1. Start dedicated asynchronous input injection worker
        self._injector_thread = threading.Thread(
            target=self._run_injector_loop,
            name="ClickChaosInjectorThread",
            daemon=True,
        )
        self._injector_thread.start()

        # 2. Start low-level hook message loop
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
        """Dedicated high-priority worker for dispatching synthetic mouse events.
        
        Running injection outside of the WH_MOUSE_LL callback completely eliminates
        win32k input lock contention and prevents LowLevelHooksTimeout unhooking.
        """
        while self._running:
            try:
                item = self._injection_queue.get()
                if item is None:
                    break
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

        logger.info("WH_MOUSE_LL hook installed successfully.")
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
        """Low-level mouse hook procedure.
        
        Designed to execute and return within 2-3 microseconds. Non-click messages
        and injected events are forwarded immediately. Click messages are queued
        asynchronously and suppressed.
        """
        # Ultra-fast path: Mouse movement, wheel, and non-clicks pass through instantly
        if nCode < 0 or wParam not in CLICK_MESSAGES:
            return user32.CallNextHookEx(self._hook_handle, nCode, wParam, lParam)

        # Inspect hook structure
        hook_struct = ctypes.cast(lParam, PMSLLHOOKSTRUCT).contents

        # Recursion check: If synthetic/injected or tagged with our signature, forward immediately
        is_injected = bool(hook_struct.flags & (LLMHF_INJECTED | LLMHF_LOWER_IL_INJECTED))
        is_our_event = (hook_struct.dwExtraInfo == CHAOS_EXTRA_INFO)

        if is_injected or is_our_event:
            return user32.CallNextHookEx(self._hook_handle, nCode, wParam, lParam)

        # If Chaos Mode is not active, let everything pass through
        if not self._is_active:
            return user32.CallNextHookEx(self._hook_handle, nCode, wParam, lParam)

        event_info = self._decode_mouse_event(wParam)
        if event_info is None:
            return user32.CallNextHookEx(self._hook_handle, nCode, wParam, lParam)

        phys_button, is_down = event_info

        # Map button and track state
        with self._lock:
            if is_down:
                target_button = self.randomizer.map_button(phys_button)
                self._active_presses[phys_button] = target_button
            else:
                target_button = self._active_presses.pop(
                    phys_button, self.randomizer.map_button(phys_button)
                )

        # Decoupled injection: Queue mapped event and return 1 immediately
        self._injection_queue.put((target_button, is_down))
        return 1

    def _decode_mouse_event(self, wParam: int) -> Optional[tuple[ButtonType, bool]]:
        """Map Windows message to (ButtonType, is_down). Returns None for non-clicks."""
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
        return None

    def _inject_mouse_input(self, button: ButtonType, is_down: bool) -> None:
        """Send synthetic mouse input with custom extra info."""
        flags = self._get_input_flags(button, is_down)
        if not flags:
            return

        # Direct mouse_event injection for ultra-low latency
        try:
            user32.mouse_event(flags, 0, 0, 0, CHAOS_EXTRA_INFO)
        except Exception:
            inp = INPUT()
            inp.type = INPUT_MOUSE
            inp.mi.dx = 0
            inp.mi.dy = 0
            inp.mi.mouseData = 0
            inp.mi.dwFlags = flags
            inp.mi.time = 0
            inp.mi.dwExtraInfo = CHAOS_EXTRA_INFO
            user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    def _get_input_flags(self, button: ButtonType, is_down: bool) -> int:
        if button == ButtonType.LEFT:
            return MOUSEEVENTF_LEFTDOWN if is_down else MOUSEEVENTF_LEFTUP
        elif button == ButtonType.RIGHT:
            return MOUSEEVENTF_RIGHTDOWN if is_down else MOUSEEVENTF_RIGHTUP
        elif button == ButtonType.MIDDLE:
            return MOUSEEVENTF_MIDDLEDOWN if is_down else MOUSEEVENTF_MIDDLEUP
        return 0

    def _release_all_active_synthetic_buttons(self) -> None:
        """Release all synthetic buttons currently marked as pressed down."""
        with self._lock:
            for phys_btn, target_btn in list(self._active_presses.items()):
                self._injection_queue.put((target_btn, False))
            self._active_presses.clear()
