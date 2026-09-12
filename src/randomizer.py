"""Button randomization logic for ClickChaos.

Provides thread-safe bijective (1-to-1) mapping for Left, Right, Middle,
and Side/Hotkeys (XButton1, XButton2) mouse buttons, ensuring no buttons
are lost or duplicated. Includes vibrant ANSI color formatting for terminal displays.
"""

from __future__ import annotations

import enum
import random
import sys
import threading
import time
from typing import Callable, Dict, List, Optional


class ButtonType(enum.Enum):
    LEFT = "Left"
    RIGHT = "Right"
    MIDDLE = "Middle"
    XBUTTON1 = "XButton1"  # Mouse 4 / Back hotkey
    XBUTTON2 = "XButton2"  # Mouse 5 / Forward hotkey

    @property
    def short_name(self) -> str:
        if self == ButtonType.XBUTTON1:
            return "X1"
        elif self == ButtonType.XBUTTON2:
            return "X2"
        return self.value[0]


STANDARD_BUTTONS: List[ButtonType] = [
    ButtonType.LEFT,
    ButtonType.RIGHT,
    ButtonType.MIDDLE,
]

ALL_BUTTONS: List[ButtonType] = [
    ButtonType.LEFT,
    ButtonType.RIGHT,
    ButtonType.MIDDLE,
    ButtonType.XBUTTON1,
    ButtonType.XBUTTON2,
]

# ANSI Terminal Colors (Duo-color palette: terminal default white/black and cyan)
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[96m"
GRAY = "\033[90m"
WHITE = "\033[97m"

BUTTON_COLORS: Dict[ButtonType, str] = {
    ButtonType.LEFT: CYAN,
    ButtonType.RIGHT: CYAN,
    ButtonType.MIDDLE: CYAN,
    ButtonType.XBUTTON1: CYAN,
    ButtonType.XBUTTON2: CYAN,
}


def enable_windows_ansi() -> None:
    """Enable ANSI escape codes and UTF-8 output on Windows consoles."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.windll.kernel32
            h_stdout = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = wintypes.DWORD()
            if kernel32.GetConsoleMode(h_stdout, ctypes.byref(mode)):
                ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                kernel32.SetConsoleMode(h_stdout, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# Automatically configure console on module import
enable_windows_ansi()


def get_button_colored_name(btn: ButtonType, short: bool = False) -> str:
    """Return ANSI-colored string for a given ButtonType."""
    color = BUTTON_COLORS.get(btn, WHITE)
    name = btn.short_name if short else btn.value
    return f"{color}{BOLD}{name}{RESET}"


def detect_mouse_button_count() -> int:
    """Return the number of mouse buttons reported by Windows."""
    try:
        import ctypes
        SM_CMOUSEBUTTONS = 43
        return int(ctypes.windll.user32.GetSystemMetrics(SM_CMOUSEBUTTONS))
    except Exception:
        return 3


def are_buttons_4_and_5_present() -> bool:
    """Check if buttons 4 and 5 (XButton1 and XButton2) are physically present on the system."""
    return detect_mouse_button_count() >= 5


class ButtonRandomizer:
    """Manages the mapping of mouse buttons and periodic reshuffling."""

    def __init__(
        self,
        interval_seconds: float = 3.0,
        derangement_only: bool = True,
        include_middle: bool = True,
        include_xbuttons: Optional[bool] = False,
        on_change_callback: Optional[Callable[[Dict[ButtonType, ButtonType]], None]] = None,
    ) -> None:
        """Initialize randomizer.

        :param interval_seconds: Seconds between automatic reshuffles.
        :param derangement_only: If True, guarantees no button maps to itself (pure chaos).
        :param include_middle: Include Middle mouse click in random swap.
        :param include_xbuttons: Include XButton1 and XButton2 (Mouse 4/5 hotkeys). Default is False.
        :param on_change_callback: Optional callable triggered when mapping updates.
        """
        self._interval_seconds = max(1.0, float(interval_seconds))
        self._derangement_only = derangement_only
        self._include_middle = include_middle
        if include_xbuttons is None:
            self._include_xbuttons = are_buttons_4_and_5_present()
        else:
            self._include_xbuttons = bool(include_xbuttons)

        self._lock = threading.RLock()
        self._mapping: Dict[ButtonType, ButtonType] = {b: b for b in ALL_BUTTONS}
        self._last_shuffle_time: float = 0.0

        self._callbacks: List[Callable[[Dict[ButtonType, ButtonType]], None]] = []
        if on_change_callback:
            self._callbacks.append(on_change_callback)

        self._auto_timer: Optional[threading.Thread] = None
        self._timer_stop_event = threading.Event()
        self._auto_shuffle_enabled = False

        # Initialize with a randomized mapping
        self.shuffle(force_different=False)

    @property
    def _on_change_callback(self) -> Optional[Callable[[Dict[ButtonType, ButtonType]], None]]:
        with self._lock:
            return self._callbacks[0] if self._callbacks else None

    @_on_change_callback.setter
    def _on_change_callback(self, callback: Optional[Callable[[Dict[ButtonType, ButtonType]], None]]) -> None:
        with self._lock:
            if callback is None:
                self._callbacks.clear()
            elif callback not in self._callbacks:
                self._callbacks.append(callback)

    def add_change_callback(self, callback: Callable[[Dict[ButtonType, ButtonType]], None]) -> None:
        """Register an observer callback invoked whenever button mapping shuffles."""
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)

    def remove_change_callback(self, callback: Callable[[Dict[ButtonType, ButtonType]], None]) -> None:
        """Remove a registered observer callback."""
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

    @property
    def auto_shuffle_enabled(self) -> bool:
        return self._auto_shuffle_enabled

    @property
    def include_middle(self) -> bool:
        with self._lock:
            return self._include_middle

    @include_middle.setter
    def include_middle(self, value: bool) -> None:
        with self._lock:
            self._include_middle = bool(value)
        self.shuffle(force_different=False)

    @property
    def include_xbuttons(self) -> bool:
        with self._lock:
            return self._include_xbuttons

    @include_xbuttons.setter
    def include_xbuttons(self, value: bool) -> None:
        with self._lock:
            self._include_xbuttons = bool(value)
        self.shuffle(force_different=False)

    def get_active_buttons(self) -> List[ButtonType]:
        """Return the list of buttons participating in the randomization."""
        with self._lock:
            active = [ButtonType.LEFT, ButtonType.RIGHT]
            if self._include_middle:
                active.append(ButtonType.MIDDLE)
            if self._include_xbuttons:
                active.extend([ButtonType.XBUTTON1, ButtonType.XBUTTON2])
            return active

    @property
    def interval_seconds(self) -> float:
        with self._lock:
            return self._interval_seconds

    @interval_seconds.setter
    def interval_seconds(self, value: float) -> None:
        with self._lock:
            self._interval_seconds = max(1.0, float(value))

    def get_mapping(self) -> Dict[ButtonType, ButtonType]:
        """Return a copy of the current button mapping."""
        with self._lock:
            return dict(self._mapping)

    def map_button(self, button: ButtonType) -> ButtonType:
        """Translate an input button to its mapped target."""
        with self._lock:
            return self._mapping.get(button, button)

    def generate_mapping(self, force_different_from_current: bool = True) -> Dict[ButtonType, ButtonType]:
        """Generate a valid bijective mapping of the active buttons."""
        active = self.get_active_buttons()
        base_mapping = {b: b for b in ALL_BUTTONS}

        if len(active) <= 1:
            return base_mapping

        max_attempts = 200
        for _ in range(max_attempts):
            shuffled = list(active)
            random.shuffle(shuffled)
            candidate_active = dict(zip(active, shuffled))

            if self._derangement_only:
                # Every active button must map to a different button
                if any(candidate_active[b] == b for b in active):
                    continue

            full_candidate = dict(base_mapping)
            full_candidate.update(candidate_active)

            with self._lock:
                if force_different_from_current and full_candidate == self._mapping and len(active) > 1:
                    continue

            return full_candidate

        # Deterministic circular shift fallback
        shift = 1
        with self._lock:
            current_active = {b: self._mapping.get(b, b) for b in active}

        fallback_active = {active[i]: active[(i + shift) % len(active)] for i in range(len(active))}
        if force_different_from_current and fallback_active == current_active and len(active) > 2:
            shift = 2
            fallback_active = {active[i]: active[(i + shift) % len(active)] for i in range(len(active))}

        base_mapping.update(fallback_active)
        return base_mapping

    def _notify_callbacks(self, current_copy: Dict[ButtonType, ButtonType]) -> None:
        with self._lock:
            callbacks_list = list(self._callbacks)
        for cb in callbacks_list:
            try:
                cb(current_copy)
            except Exception:
                pass

    def shuffle(self, force_different: bool = True) -> Dict[ButtonType, ButtonType]:
        """Generate and apply a new button mapping. Thread-safe."""
        new_mapping = self.generate_mapping(force_different_from_current=force_different)
        with self._lock:
            self._mapping = new_mapping
            self._last_shuffle_time = time.time()
            current_copy = dict(self._mapping)

        self._notify_callbacks(current_copy)
        return current_copy

    def reset_to_identity(self) -> Dict[ButtonType, ButtonType]:
        """Reset mapping to normal 1-to-1 hardware mapping."""
        with self._lock:
            self._mapping = {b: b for b in ALL_BUTTONS}
            self._last_shuffle_time = time.time()
            current_copy = dict(self._mapping)

        self._notify_callbacks(current_copy)
        return current_copy

    def get_summary_string(self) -> str:
        """Return human-readable summary of the active mapping."""
        active = self.get_active_buttons()
        with self._lock:
            m = self._mapping
            parts = [f"{b.short_name} ➔ {m.get(b, b).short_name}" for b in active]
            return " | ".join(parts)

    def get_colored_summary_string(self, short: bool = False) -> str:
        """Return duo-colored (terminal default and cyan) one-line summary of the current mapping."""
        active = self.get_active_buttons()
        with self._lock:
            m = self._mapping
            parts = [
                f"{RESET}{b.short_name if short else b.value}{RESET} {CYAN}➔{RESET} {CYAN}{BOLD}{m.get(b, b).short_name if short else m.get(b, b).value}{RESET}"
                for b in active
            ]
            sep = f" {RESET}│{RESET} "
            return sep.join(parts)

    def get_colored_mapping_line(self, short: bool = False) -> str:
        """Return a formatted, duo-color single-line display showing the current button remap."""
        now = time.strftime("%H:%M:%S")
        return f"[{now}] {CYAN}{BOLD}Remap:{RESET} {self.get_colored_summary_string(short=short)}"

    def get_colored_mapping_card(self) -> str:
        """Return a formatted, duo-color card display showing the complete button translation."""
        active = self.get_active_buttons()
        now = time.strftime("%H:%M:%S")
        with self._lock:
            m = self._mapping
            header = f"{CYAN}┌─ {BOLD}[MOUSE BUTTONS RANDOMIZED]{RESET} [{now}] "
            card_lines = [
                header + f"{CYAN}" + ("─" * max(4, 58 - len(header) + 32)) + f"┐{RESET}"
            ]
            for b in active:
                target = m.get(b, b)
                line = (
                    f"{CYAN}│{RESET}  {RESET}{b.value:<10}{RESET} "
                    f"{CYAN}➔{RESET}  "
                    f"{CYAN}{BOLD}{target.value:<10}{RESET}"
                )
                card_lines.append(f"{line:<68} {CYAN}│{RESET}")
            
            # Add one-line summary footer inside the card
            summary_line = f"{CYAN}│{RESET}  {BOLD}Summary:{RESET} {self.get_colored_summary_string(short=True)}"
            card_lines.append(f"{CYAN}├──────────────────────────────────────────────────────────┤{RESET}")
            card_lines.append(f"{summary_line}")
            card_lines.append(f"{CYAN}└──────────────────────────────────────────────────────────┘{RESET}")
            return "\n".join(card_lines)

    def start_auto_shuffle(self) -> None:
        """Start background thread that periodically reshuffles the mapping."""
        if self._auto_shuffle_enabled:
            return

        self._auto_shuffle_enabled = True
        self._timer_stop_event.clear()

        def _worker() -> None:
            while not self._timer_stop_event.is_set():
                interval = self.interval_seconds
                if self._timer_stop_event.wait(timeout=interval):
                    break
                self.shuffle(force_different=True)

        self._auto_timer = threading.Thread(target=_worker, name="ClickChaosTimerThread", daemon=True)
        self._auto_timer.start()

    def stop_auto_shuffle(self) -> None:
        """Stop the background auto-reshuffle timer."""
        self._auto_shuffle_enabled = False
        self._timer_stop_event.set()
        if self._auto_timer and self._auto_timer.is_alive():
            self._auto_timer.join(timeout=1.0)
        self._auto_timer = None
