"""Button randomization logic for ClickChaos.

Provides thread-safe bijective (1-to-1) mapping for Left, Right, and Middle
mouse buttons, ensuring no buttons are lost or duplicated.
"""

from __future__ import annotations

import enum
import random
import threading
import time
from typing import Callable, Dict, List, Optional


class ButtonType(enum.Enum):
    LEFT = "Left"
    RIGHT = "Right"
    MIDDLE = "Middle"

    @property
    def short_name(self) -> str:
        return self.value[0]


ALL_BUTTONS: List[ButtonType] = [
    ButtonType.LEFT,
    ButtonType.RIGHT,
    ButtonType.MIDDLE,
]


class ButtonRandomizer:
    """Manages the mapping of mouse buttons and periodic reshuffling."""

    def __init__(
        self,
        interval_seconds: float = 5.0,
        derangement_only: bool = True,
        on_change_callback: Optional[Callable[[Dict[ButtonType, ButtonType]], None]] = None,
    ) -> None:
        """Initialize randomizer.

        :param interval_seconds: Seconds between automatic reshuffles.
        :param derangement_only: If True, guarantees no button maps to itself (pure chaos).
        :param on_change_callback: Optional callable triggered when mapping updates.
        """
        self._interval_seconds = max(1.0, float(interval_seconds))
        self._derangement_only = derangement_only
        self._include_middle = True
        self._on_change_callback = on_change_callback

        self._lock = threading.Lock()
        self._mapping: Dict[ButtonType, ButtonType] = {b: b for b in ALL_BUTTONS}
        self._last_shuffle_time: float = 0.0

        self._auto_timer: Optional[threading.Thread] = None
        self._timer_stop_event = threading.Event()
        self._auto_shuffle_enabled = False

        # Initialize with a randomized mapping
        self.shuffle(force_different=False)

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
        """Generate a valid bijective mapping of the buttons."""
        with self._lock:
            include_mid = self._include_middle

        if not include_mid:
            # 2-button swap: Left <-> Right, Middle remains untouched
            return {
                ButtonType.LEFT: ButtonType.RIGHT,
                ButtonType.RIGHT: ButtonType.LEFT,
                ButtonType.MIDDLE: ButtonType.MIDDLE,
            }

        buttons = list(ALL_BUTTONS)
        max_attempts = 100

        for _ in range(max_attempts):
            shuffled = list(buttons)
            random.shuffle(shuffled)
            candidate = dict(zip(buttons, shuffled))

            if self._derangement_only:
                # Every button must map to a different button
                if any(candidate[b] == b for b in buttons):
                    continue

            # Check if it differs from current mapping if requested
            with self._lock:
                if force_different_from_current and candidate == self._mapping and len(buttons) > 1:
                    continue

            return candidate

        # Fallback to deterministic derangement
        fallback = {
            ButtonType.LEFT: ButtonType.RIGHT,
            ButtonType.RIGHT: ButtonType.MIDDLE,
            ButtonType.MIDDLE: ButtonType.LEFT,
        }
        return fallback


    def shuffle(self, force_different: bool = True) -> Dict[ButtonType, ButtonType]:
        """Generate and apply a new button mapping. Thread-safe."""
        new_mapping = self.generate_mapping(force_different_from_current=force_different)
        with self._lock:
            self._mapping = new_mapping
            self._last_shuffle_time = time.time()
            current_copy = dict(self._mapping)

        if self._on_change_callback:
            try:
                self._on_change_callback(current_copy)
            except Exception:
                pass

        return current_copy

    def reset_to_identity(self) -> Dict[ButtonType, ButtonType]:
        """Reset mapping to normal 1-to-1 hardware mapping (L->L, R->R, M->M)."""
        with self._lock:
            self._mapping = {b: b for b in ALL_BUTTONS}
            self._last_shuffle_time = time.time()
            current_copy = dict(self._mapping)

        if self._on_change_callback:
            try:
                self._on_change_callback(current_copy)
            except Exception:
                pass

        return current_copy

    def get_summary_string(self) -> str:
        """Return human-readable summary of the current mapping."""
        with self._lock:
            m = self._mapping
            return (
                f"L ➔ {m.get(ButtonType.LEFT, ButtonType.LEFT).short_name} | "
                f"R ➔ {m.get(ButtonType.RIGHT, ButtonType.RIGHT).short_name} | "
                f"M ➔ {m.get(ButtonType.MIDDLE, ButtonType.MIDDLE).short_name}"
            )

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
