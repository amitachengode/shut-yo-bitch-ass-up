"""Global keyboard shortcut manager for ClickChaos using native Win32 RegisterHotKey.

Provides system-wide hotkeys without invasive low-level keyboard hooks (WH_KEYBOARD_LL),
ensuring zero keylogger flags by antivirus software and zero input latency.
Includes support for cursor locking toggle, mouse teleportation, scroll chaos,
and dynamic keyboard hotkey shuffling.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import random
import threading
from typing import Callable, Dict, List, NamedTuple, Optional

logger = logging.getLogger("ClickChaos.HotkeyManager")

# Win32 Constants
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_USER = 0x0400
WM_RELOAD_HOTKEYS = WM_USER + 1

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
VK_L = 0x4C  # L key (Lock Cursor)
VK_K = 0x4B  # K key (Keyboard Hotkeys Shuffle)
VK_T = 0x54  # T key (Teleport Mouse)
VK_W = 0x57  # W key (Wheel Scroll Chaos)

if hasattr(ctypes, "windll"):
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
else:
    user32 = None
    kernel32 = None


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
    HOTKEY_ID_TOGGLE_CURSOR_LOCK = 1008
    HOTKEY_ID_SHUFFLE_HOTKEYS = 1009
    HOTKEY_ID_TOGGLE_TELEPORT = 1010
    HOTKEY_ID_TOGGLE_SCROLL = 1011

    DEFAULT_ACTION_KEYS = {
        "toggle_chaos": (VK_C, "C"),
        "randomize": (VK_R, "R"),
        "toggle_cursor": (VK_L, "L"),
        "toggle_teleport": (VK_T, "T"),
        "toggle_scroll": (VK_W, "W"),
        "toggle_middle": (VK_M, "M"),
        "shuffle_hotkeys": (VK_K, "K"),
        "emergency_disable": (VK_X, "X"),  # Immutable safety panic key
        "exit": (VK_Q, "Q"),
    }

    def __init__(
        self,
        on_toggle_chaos: Optional[Callable[[], None]] = None,
        on_randomize: Optional[Callable[[], None]] = None,
        on_emergency_disable: Optional[Callable[[], None]] = None,
        on_toggle_middle: Optional[Callable[[], None]] = None,
        on_toggle_cursor_lock: Optional[Callable[[], None]] = None,
        on_toggle_teleport: Optional[Callable[[], None]] = None,
        on_toggle_scroll: Optional[Callable[[], None]] = None,
        on_shuffle_hotkeys: Optional[Callable[[], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
        on_hotkeys_changed: Optional[Callable[[List[HotkeyConfig]], None]] = None,
    ) -> None:
        self.on_toggle_chaos = on_toggle_chaos
        self.on_randomize = on_randomize
        self.on_emergency_disable = on_emergency_disable
        self.on_toggle_middle = on_toggle_middle
        self.on_toggle_cursor_lock = on_toggle_cursor_lock
        self.on_toggle_teleport = on_toggle_teleport
        self.on_toggle_scroll = on_toggle_scroll
        self.on_shuffle_hotkeys = on_shuffle_hotkeys
        self.on_exit = on_exit
        self.on_hotkeys_changed = on_hotkeys_changed

        self._lock = threading.Lock()
        self._action_keys = dict(self.DEFAULT_ACTION_KEYS)

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._thread_id: Optional[int] = None
        self._ready_event = threading.Event()
        self._registered_ids: List[int] = []
        self._handlers: Dict[int, Callable[[], None]] = {}
        self._active_configs: List[HotkeyConfig] = []

    def _build_hotkeys(self) -> List[HotkeyConfig]:
        """Construct the list of hotkey configurations based on current action keys."""
        configs: List[HotkeyConfig] = []
        mod_ctrl_alt = MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
        mod_ctrl_shift = MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT

        with self._lock:
            c_vk, c_char = self._action_keys["toggle_chaos"]
            r_vk, r_char = self._action_keys["randomize"]
            l_vk, l_char = self._action_keys["toggle_cursor"]
            t_vk, t_char = self._action_keys["toggle_teleport"]
            w_vk, w_char = self._action_keys["toggle_scroll"]
            m_vk, m_char = self._action_keys["toggle_middle"]
            k_vk, k_char = self._action_keys["shuffle_hotkeys"]
            x_vk, x_char = self._action_keys["emergency_disable"]
            q_vk, q_char = self._action_keys["exit"]

        if self.on_toggle_chaos:
            configs.append(
                HotkeyConfig(
                    self.HOTKEY_ID_TOGGLE_CHAOS,
                    mod_ctrl_alt,
                    c_vk,
                    f"Ctrl+Alt+{c_char} (Toggle Chaos)",
                    self.on_toggle_chaos,
                )
            )
            configs.append(
                HotkeyConfig(
                    self.HOTKEY_ID_TOGGLE_CHAOS_ALT,
                    mod_ctrl_shift,
                    c_vk,
                    f"Ctrl+Shift+{c_char} (Toggle Chaos Secondary)",
                    self.on_toggle_chaos,
                )
            )

        if self.on_randomize:
            configs.append(
                HotkeyConfig(
                    self.HOTKEY_ID_RANDOMIZE,
                    mod_ctrl_alt,
                    r_vk,
                    f"Ctrl+Alt+{r_char} (Randomize Now)",
                    self.on_randomize,
                )
            )
            configs.append(
                HotkeyConfig(
                    self.HOTKEY_ID_RANDOMIZE_ALT,
                    mod_ctrl_shift,
                    r_vk,
                    f"Ctrl+Shift+{r_char} (Randomize Now Secondary)",
                    self.on_randomize,
                )
            )

        if self.on_toggle_cursor_lock:
            configs.append(
                HotkeyConfig(
                    self.HOTKEY_ID_TOGGLE_CURSOR_LOCK,
                    mod_ctrl_alt,
                    l_vk,
                    f"Ctrl+Alt+{l_char} (Toggle Cursor Lock)",
                    self.on_toggle_cursor_lock,
                )
            )

        if self.on_toggle_teleport:
            configs.append(
                HotkeyConfig(
                    self.HOTKEY_ID_TOGGLE_TELEPORT,
                    mod_ctrl_alt,
                    t_vk,
                    f"Ctrl+Alt+{t_char} (Toggle Mouse Teleportation)",
                    self.on_toggle_teleport,
                )
            )

        if self.on_toggle_scroll:
            configs.append(
                HotkeyConfig(
                    self.HOTKEY_ID_TOGGLE_SCROLL,
                    mod_ctrl_alt,
                    w_vk,
                    f"Ctrl+Alt+{w_char} (Toggle Scroll Chaos)",
                    self.on_toggle_scroll,
                )
            )

        if self.on_shuffle_hotkeys:
            configs.append(
                HotkeyConfig(
                    self.HOTKEY_ID_SHUFFLE_HOTKEYS,
                    mod_ctrl_alt,
                    k_vk,
                    f"Ctrl+Alt+{k_char} (Shuffle Keyboard Hotkeys)",
                    self.on_shuffle_hotkeys,
                )
            )

        if self.on_emergency_disable:
            configs.append(
                HotkeyConfig(
                    self.HOTKEY_ID_EMERGENCY_DISABLE,
                    mod_ctrl_alt,
                    x_vk,
                    f"Ctrl+Alt+{x_char} (Emergency Panic Disable)",
                    self.on_emergency_disable,
                )
            )

        if self.on_toggle_middle:
            configs.append(
                HotkeyConfig(
                    self.HOTKEY_ID_TOGGLE_MIDDLE,
                    mod_ctrl_alt,
                    m_vk,
                    f"Ctrl+Alt+{m_char} (Toggle Button Mode)",
                    self.on_toggle_middle,
                )
            )

        if self.on_exit:
            configs.append(
                HotkeyConfig(
                    self.HOTKEY_ID_EXIT,
                    mod_ctrl_alt,
                    q_vk,
                    f"Ctrl+Alt+{q_char} (Exit ClickChaos)",
                    self.on_exit,
                )
            )

        return configs

    def randomize_action_hotkeys(self) -> List[HotkeyConfig]:
        """Randomly re-assign letter keys to actions (preserving emergency panic Ctrl+Alt+X)."""
        candidate_pool = [
            chr(code) for code in range(ord('A'), ord('Z') + 1)
            if chr(code) not in ('X', 'Q')
        ]
        random.shuffle(candidate_pool)

        keys_needed = [
            "toggle_chaos",
            "randomize",
            "toggle_cursor",
            "toggle_teleport",
            "toggle_scroll",
            "toggle_middle",
            "shuffle_hotkeys",
        ]
        chosen = candidate_pool[:len(keys_needed)]

        with self._lock:
            for action, letter in zip(keys_needed, chosen):
                self._action_keys[action] = (ord(letter), letter)

        logger.info("Randomized keyboard action keys: %s", self._action_keys)
        self.reload_hotkeys()
        return self.get_active_configs()

    def reset_to_default_hotkeys(self) -> List[HotkeyConfig]:
        """Reset keyboard shortcuts to defaults."""
        with self._lock:
            self._action_keys = dict(self.DEFAULT_ACTION_KEYS)
        self.reload_hotkeys()
        return self.get_active_configs()

    def reload_hotkeys(self) -> None:
        """Trigger message thread to unregister and re-register hotkeys."""
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_RELOAD_HOTKEYS, 0, 0)

    def get_active_configs(self) -> List[HotkeyConfig]:
        """Return a copy of currently configured hotkeys."""
        with self._lock:
            return list(self._active_configs)

    def get_summary_list(self) -> List[str]:
        """Return human-readable list of current hotkeys."""
        with self._lock:
            return [cfg.name for cfg in self._active_configs]

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

    def _register_hotkeys_on_thread(self) -> None:
        """Register all hotkeys in the current thread context."""
        for hid in self._registered_ids:
            user32.UnregisterHotKey(None, hid)
        self._registered_ids.clear()
        self._handlers.clear()

        configs = self._build_hotkeys()
        with self._lock:
            self._active_configs = list(configs)

        for cfg in configs:
            self._handlers[cfg.hotkey_id] = cfg.callback
            success = user32.RegisterHotKey(None, cfg.hotkey_id, cfg.modifiers, cfg.vk_code)
            if success:
                self._registered_ids.append(cfg.hotkey_id)
                logger.debug("Registered global hotkey: %s", cfg.name)
            else:
                err = ctypes.GetLastError()
                logger.warning(
                    "Could not register hotkey %s (error code: %d). May be in use by another app.",
                    cfg.name,
                    err,
                )

        if self.on_hotkeys_changed:
            try:
                self.on_hotkeys_changed(list(configs))
            except Exception as e:
                logger.exception("Error executing on_hotkeys_changed callback: %s", e)

    def _run_message_loop(self) -> None:
        """Thread loop running GetMessage for WM_HOTKEY."""
        self._thread_id = kernel32.GetCurrentThreadId()

        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)

        self._register_hotkeys_on_thread()
        self._ready_event.set()

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
            elif msg.message == WM_RELOAD_HOTKEYS:
                logger.info("Reloading hotkeys on message thread...")
                self._register_hotkeys_on_thread()

        for hid in self._registered_ids:
            user32.UnregisterHotKey(None, hid)
        self._registered_ids.clear()
        self._handlers.clear()
        logger.info("All global hotkeys unregistered.")
