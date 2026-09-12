"""System tray user interface for ClickChaos.

Provides system tray integration using pystray with dynamic menu updates,
status indication, and icon state switching without keyboard hooks.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from PIL import Image, ImageDraw
import pystray
from pystray import Menu, MenuItem

from src.hook_manager import MouseHookManager
from src.randomizer import ButtonRandomizer, ButtonType

logger = logging.getLogger("ClickChaos.TrayUI")


def generate_tray_image(size: int = 64, active: bool = False) -> Image.Image:
    """Generate a high-res PIL Image for the system tray icon."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = size * 0.08
    w = size - 2 * pad
    h = size - 2 * pad

    if active:
        body_color = (20, 26, 38, 255)
        rim_color = (0, 240, 180, 255)
        l_color = (255, 60, 100, 255)
        r_color = (30, 190, 255, 255)
        m_color = (255, 200, 0, 255)
        chaos_line = (255, 255, 255, 240)
    else:
        body_color = (40, 44, 52, 255)
        rim_color = (120, 130, 145, 255)
        l_color = (100, 105, 115, 255)
        r_color = (100, 105, 115, 255)
        m_color = (130, 135, 145, 255)
        chaos_line = (140, 145, 155, 180)

    mx1, my1 = pad, pad
    mx2, my2 = pad + w, pad + h
    radius = w * 0.35
    draw.rounded_rectangle(
        [mx1, my1, mx2, my2],
        radius=radius,
        fill=body_color,
        outline=rim_color,
        width=max(2, int(size * 0.05)),
    )

    cx = size / 2
    btn_h = pad + h * 0.42
    draw.line(
        [(cx, my1 + radius * 0.3), (cx, btn_h)],
        fill=rim_color,
        width=max(1, int(size * 0.03)),
    )
    draw.line(
        [(mx1, btn_h), (mx2, btn_h)],
        fill=rim_color,
        width=max(1, int(size * 0.03)),
    )

    # Mouse button dots
    draw.ellipse(
        [mx1 + w * 0.15, my1 + h * 0.1, mx1 + w * 0.35, my1 + h * 0.28],
        fill=l_color,
    )
    draw.ellipse(
        [mx2 - w * 0.35, my1 + h * 0.1, mx2 - w * 0.15, my1 + h * 0.28],
        fill=r_color,
    )
    draw.rounded_rectangle(
        [cx - w * 0.06, my1 + h * 0.14, cx + w * 0.06, my1 + h * 0.34],
        radius=w * 0.03,
        fill=m_color,
    )

    # Crossing chaos pattern on lower palm
    draw.line(
        [(mx1 + w * 0.25, btn_h + h * 0.15), (mx2 - w * 0.25, my2 - h * 0.15)],
        fill=chaos_line,
        width=max(2, int(size * 0.04)),
    )
    draw.line(
        [(mx2 - w * 0.25, btn_h + h * 0.15), (mx1 + w * 0.25, my2 - h * 0.15)],
        fill=chaos_line,
        width=max(2, int(size * 0.04)),
    )

    return img


class TrayUI:
    """Manages the system tray icon and context menu."""

    def __init__(
        self,
        randomizer: ButtonRandomizer,
        hook_manager: MouseHookManager,
        on_exit_callback: Optional[Callable[[], None]] = None,
    ) -> None:
        self.randomizer = randomizer
        self.hook_manager = hook_manager
        self.on_exit_callback = on_exit_callback

        self._active_icon_img = generate_tray_image(64, active=True)
        self._inactive_icon_img = generate_tray_image(64, active=False)

        self._icon: Optional[pystray.Icon] = None

        # Link randomizer changes to menu updates
        self.randomizer._on_change_callback = self._on_mapping_changed

    def stop(self) -> None:
        """Stop the tray icon."""
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None

    def start(self) -> None:
        """Initialize and run the system tray icon."""
        self._create_tray_icon()

    def _on_mapping_changed(self, mapping: dict[ButtonType, ButtonType]) -> None:
        """Callback when button mapping changes."""
        if self._icon:
            self._icon.update_menu()

    def _update_icon_visual(self) -> None:
        """Switch icon image between active (glowing) and inactive."""
        if not self._icon:
            return
        is_active = self.hook_manager.is_active
        self._icon.icon = self._active_icon_img if is_active else self._inactive_icon_img
        self._icon.title = (
            f"ClickChaos: {'ACTIVE' if is_active else 'INACTIVE'} ({self.randomizer.get_summary_string()})"
        )

    def update_ui(self) -> None:
        """Refresh icon visual and tray context menu."""
        self._update_icon_visual()
        if self._icon:
            try:
                self._icon.update_menu()
            except Exception:
                pass

    def toggle_chaos(self) -> bool:
        """Toggle Chaos Mode and refresh UI."""
        new_state = self.hook_manager.toggle()
        self.update_ui()
        logger.info("Chaos Mode toggled: %s", "ACTIVE" if new_state else "INACTIVE")
        return new_state

    def randomize_now(self) -> None:
        """Trigger re-shuffle and refresh UI."""
        self.randomizer.shuffle(force_different=True)
        self.update_ui()
        logger.info("Mapping randomized: %s", self.randomizer.get_summary_string())

    def emergency_disable(self) -> None:
        """Immediately turn off Chaos Mode and restore normal mouse controls."""
        self.hook_manager.set_active(False)
        self.update_ui()
        logger.info("Emergency Disable: Chaos Mode is INACTIVE.")

    def toggle_button_mode(self) -> bool:
        """Toggle between 3-button and 2-button swap modes."""
        self.randomizer.include_middle = not self.randomizer.include_middle
        self.update_ui()
        logger.info("Button Swap Mode: 3-button mode is %s", self.randomizer.include_middle)
        return self.randomizer.include_middle

    def _toggle_chaos(self, icon: Optional[pystray.Icon], item: Optional[MenuItem]) -> None:
        """Menu handler for Chaos Mode toggle."""
        self.toggle_chaos()

    def _randomize_now(self, icon: Optional[pystray.Icon], item: Optional[MenuItem]) -> None:
        """Menu handler for manual randomization."""
        self.randomize_now()

    def _emergency_disable(self, icon: Optional[pystray.Icon], item: Optional[MenuItem]) -> None:
        """Menu handler for emergency disable."""
        self.emergency_disable()

    def _toggle_auto_shuffle(self, icon: Optional[pystray.Icon], item: Optional[MenuItem]) -> None:
        """Toggle auto-shuffle on or off."""
        if self.randomizer.auto_shuffle_enabled:
            self.randomizer.stop_auto_shuffle()
        else:
            self.randomizer.start_auto_shuffle()
        if icon:
            icon.update_menu()

    def _set_interval(self, seconds: int) -> Callable[[Optional[pystray.Icon], Optional[MenuItem]], None]:
        """Factory for setting the auto-shuffle interval."""
        def handler(icon: Optional[pystray.Icon], item: Optional[MenuItem]) -> None:
            self.randomizer.interval_seconds = seconds
            if icon:
                icon.update_menu()
        return handler


    def _exit_app(self, icon: Optional[pystray.Icon], item: Optional[MenuItem]) -> None:
        """Gracefully exit the application."""
        logger.info("Exiting ClickChaos...")
        self.hook_manager.set_active(False)
        self.hook_manager.stop()
        self.randomizer.stop_auto_shuffle()
        self.stop()

        if self.on_exit_callback:
            self.on_exit_callback()

    def _build_menu(self) -> Menu:
        """Construct the dynamic tray context menu."""
        def get_status_label(item: MenuItem) -> str:
            state = "🟢 ACTIVE" if self.hook_manager.is_active else "⚪ INACTIVE"
            return f"Status: {state} [{self.randomizer.get_summary_string()}]"

        def is_chaos_active(item: MenuItem) -> bool:
            return self.hook_manager.is_active

        def is_auto_shuffle_on(item: MenuItem) -> bool:
            return self.randomizer.auto_shuffle_enabled

        def is_interval_selected(seconds: int) -> Callable[[MenuItem], bool]:
            return lambda item: int(self.randomizer.interval_seconds) == seconds

        interval_menu = Menu(
            MenuItem(
                "Enable Auto-Shuffle",
                self._toggle_auto_shuffle,
                checked=is_auto_shuffle_on,
            ),
            Menu.SEPARATOR,
            MenuItem(
                "Every 5 seconds",
                self._set_interval(5),
                checked=is_interval_selected(5),
            ),
            MenuItem(
                "Every 10 seconds",
                self._set_interval(10),
                checked=is_interval_selected(10),
            ),
            MenuItem(
                "Every 30 seconds",
                self._set_interval(30),
                checked=is_interval_selected(30),
            ),
            MenuItem(
                "Every 60 seconds",
                self._set_interval(60),
                checked=is_interval_selected(60),
            ),
            MenuItem(
                "Every 120 seconds",
                self._set_interval(120),
                checked=is_interval_selected(120),
            ),
        )

        def is_mode_3_buttons(item: MenuItem) -> bool:
            return self.randomizer.include_middle

        def is_mode_2_buttons(item: MenuItem) -> bool:
            return not self.randomizer.include_middle

        def set_mode(include_middle: bool) -> Callable[[Optional[pystray.Icon], Optional[MenuItem]], None]:
            def handler(icon: Optional[pystray.Icon], item: Optional[MenuItem]) -> None:
                self.randomizer.include_middle = include_middle
                if icon:
                    icon.update_menu()
            return handler

        mode_menu = Menu(
            MenuItem(
                "All 3 Buttons (Left, Right, Middle)",
                set_mode(True),
                checked=is_mode_3_buttons,
            ),
            MenuItem(
                "Left & Right Only (No Middle Auto-Pan)",
                set_mode(False),
                checked=is_mode_2_buttons,
            ),
        )

        menu_items = [
            MenuItem(get_status_label, None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(
                "Chaos Mode (Toggle) [Ctrl+Alt+C]",
                self._toggle_chaos,
                checked=is_chaos_active,
                default=True,
            ),
            MenuItem("Randomize Now [Ctrl+Alt+R]", self._randomize_now),
            MenuItem("Emergency Disable [Ctrl+Alt+X]", self._emergency_disable),
            MenuItem("Button Swap Mode [Ctrl+Alt+M]", mode_menu),
            MenuItem("Auto-Shuffle Settings", interval_menu),
            Menu.SEPARATOR,
            MenuItem("Exit ClickChaos [Ctrl+Alt+Q]", self._exit_app),
        ]


        return Menu(*menu_items)

    def _create_tray_icon(self) -> None:
        """Create and run the pystray icon loop."""
        initial_img = self._active_icon_img if self.hook_manager.is_active else self._inactive_icon_img
        self._icon = pystray.Icon(
            name="ClickChaos",
            icon=initial_img,
            title=f"ClickChaos: {'ACTIVE' if self.hook_manager.is_active else 'INACTIVE'} ({self.randomizer.get_summary_string()})",
            menu=self._build_menu(),
        )
        self._icon.run()
