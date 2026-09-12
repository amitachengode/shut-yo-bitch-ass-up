"""Global keyboard shortcut manager for ClickChaos using native Win32 RegisterHotKey.

Provides system-wide hotkeys without invasive low-level keyboard hooks (WH_KEYBOARD_LL),
ensuring zero keylogger flags by antivirus software and zero input latency.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import threading
from typing import Callable, Dict, List, NamedTuple, Optional

logger = logging.getLogger("ClickChaos.HotkeyManager")

# Win32 Constants
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

# Modifiers
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

# Virtual Key Codes
VK_C = 0x43  # C key
VK_R = 0x52  # R key
VK_X = 0x58  # X key
VK_M = 0x4D  # M key
VK_Q = 0x51  # Q key

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.RegisterHotKey.restype = wintypes.BOOL
user32.RegisterHotKey.argtypes = [
    wintypes.HWND,
    ctypes.c_int,
    wintypes.UINT,
    wintypes.UINT,
]

user32.UnregisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]

user32.GetMessageW.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
]

user32.PeekMessageW.restype = wintypes.BOOL
user32.PeekMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
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


class HotkeyConfig(NamedTuple):
    hotkey_id: int
    modifiers: int
    vk_code: int
    name: str
    callback: Callable[[], None]


class HotkeyManager:
    """Registers and handles global keyboard shortcuts on a background message thread."""

    HOTKEY_ID_TOGGLE_CHAOS = 1001
    HOTKEY_ID_TOGGLE_CHAOS_ALT = 1002
    HOTKEY_ID_RANDOMIZE = 1003
    HOTKEY_ID_RANDOMIZE_ALT = 1004
    HOTKEY_ID_EMERGENCY_DISABLE = 1005
    HOTKEY_ID_TOGGLE_MIDDLE = 1006
    HOTKEY_ID_EXIT = 1007

    def __init__(
        self,
        on_toggle_chaos: Optional[Callable[[], None]] = None,
        on_randomize: Optional[Callable[[], None]] = None,
        on_emergency_disable: Optional[Callable[[], None]] = None,
        on_toggle_middle: Optional[Callable[[], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
    ) -> None:
        self.on_toggle_chaos = on_toggle_chaos
        self.on_randomize = on_randomize
        self.on_emergency_disable = on_emergency_disable
        self.on_toggle_middle = on_toggle_middle
        self.on_exit = on_exit

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._thread_id: Optional[int] = None
        self._ready_event = threading.Event()
        self._registered_ids: List[int] = []
        self._handlers: Dict[int, Callable[[], None]] = {}

    def _build_hotkeys(self) -> List[HotkeyConfig]:
        """Construct the list of hotkey configurations."""
        configs: List[HotkeyConfig] = []
        mod_ctrl_alt = MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
        mod_ctrl_shift = MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT

        if self.on_toggle_chaos:
            configs.append(
                HotkeyConfig(
                    self.HOTKEY_ID_TOGGLE_CHAOS,
                    mod_ctrl_alt,
                    VK_C,
                    "Ctrl+Alt+C (Toggle Chaos)",
                    self.on_toggle_chaos,
                )
            )
            configs.append(
                HotkeyConfig(
                    self.HOTKEY_ID_TOGGLE_CHAOS_ALT,
                    mod_ctrl_shift,
                    VK_C,
                    "Ctrl+Shift+C (Toggle Chaos Secondary)",
                    self.on_toggle_chaos,
                )
            )

        if self.on_randomize:
            configs.append(
                HotkeyConfig(
                    self.HOTKEY_ID_RANDOMIZE,
                    mod_ctrl_alt,
                    VK_R,
                    "Ctrl+Alt+R (Randomize Now)",
                    self.on_randomize,
                )
            )
            configs.append(
                HotkeyConfig(
                    self.HOTKEY_ID_RANDOMIZE_ALT,
                    mod_ctrl_shift,
                    VK_R,
                    "Ctrl+Shift+R (Randomize Now Secondary)",
                    self.on_randomize,
                )
            )

        if self.on_emergency_disable:
            configs.append(
                HotkeyConfig(
                    self.HOTKEY_ID_EMERGENCY_DISABLE,
                    mod_ctrl_alt,
                    VK_X,
                    "Ctrl+Alt+X (Emergency Panic Disable)",
                    self.on_emergency_disable,
                )
            )

        if self.on_toggle_middle:
            configs.append(
                HotkeyConfig(
                    self.HOTKEY_ID_TOGGLE_MIDDLE,
                    mod_ctrl_alt,
                    VK_M,
                    "Ctrl+Alt+M (Toggle Middle Button Mode)",
                    self.on_toggle_middle,
                )
            )

        if self.on_exit:
            configs.append(
                HotkeyConfig(
                    self.HOTKEY_ID_EXIT,
                    mod_ctrl_alt,
                    VK_Q,
                    "Ctrl+Alt+Q (Exit ClickChaos)",
                    self.on_exit,
                )
            )

        return configs

    def start(self) -> None:
        """Start the background hotkey listener thread."""
        if self._running:
            return

        self._running = True
        self._ready_event.clear()

        self._thread = threading.Thread(
            target=self._run_message_loop,
            name="ClickChaosHotkeyThread",
            daemon=True,
        )
        self._thread.start()

        if not self._ready_event.wait(timeout=3.0):
            logger.warning("Timed out waiting for hotkey thread to initialize.")

    def stop(self) -> None:
        """Unregister all hotkeys and stop the message loop thread."""
        if not self._running:
            return

        self._running = False
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        self._thread = None
        self._thread_id = None

    def _run_message_loop(self) -> None:
        """Thread loop running GetMessage for WM_HOTKEY."""
        self._thread_id = kernel32.GetCurrentThreadId()

        # Force Windows to create a message queue for this thread
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)

        # Register hotkeys
        self._handlers.clear()
        self._registered_ids.clear()
        configs = self._build_hotkeys()

        for cfg in configs:
            self._handlers[cfg.hotkey_id] = cfg.callback
            success = user32.RegisterHotKey(None, cfg.hotkey_id, cfg.modifiers, cfg.vk_code)
            if success:
                self._registered_ids.append(cfg.hotkey_id)
                logger.info("Registered global hotkey: %s", cfg.name)
            else:
                err = ctypes.GetLastError()
                logger.warning("Could not register hotkey %s (error code: %d). May be in use by another app.", cfg.name, err)

        self._ready_event.set()

        # Message dispatch pump
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                hotkey_id = int(msg.wParam)
                handler = self._handlers.get(hotkey_id)
                if handler:
                    try:
                        logger.debug("Dispatching hotkey callback for ID %d", hotkey_id)
                        handler()
                    except Exception as e:
                        logger.exception("Error executing hotkey callback: %s", e)

        # Cleanup: Unregister all hotkeys registered on this thread
        for hid in self._registered_ids:
            user32.UnregisterHotKey(None, hid)
        self._registered_ids.clear()
        self._handlers.clear()
        logger.info("All global hotkeys unregistered.")
