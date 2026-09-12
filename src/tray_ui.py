"""System tray user interface for ClickChaos.

Provides system tray integration using pystray with dynamic menu updates,
status indication, cursor locking controls, and hotkey management.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Optional

from PIL import Image, ImageDraw
import pystray
from pystray import Menu, MenuItem

from src.hook_manager import MouseHookManager
from src.randomizer import ButtonRandomizer, ButtonType

if TYPE_CHECKING:
    from src.hotkey_manager import HotkeyManager

logger = logging.getLogger("ClickChaos.TrayUI")


def generate_tray_image(size: int = 64, active: bool = False, locked: bool = False) -> Image.Image:
    """Generate a high-res PIL Image for the system tray icon."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = size * 0.08
    w = size - 2 * pad
    h = size - 2 * pad

    if active:
        body_color = (20, 26, 38, 255)
        rim_color = (0, 240, 180, 255) if not locked else (255, 100, 50, 255)
        l_color = (255, 60, 100, 255)
        r_color = (30, 190, 255, 255)
        m_color = (255, 200, 0, 255)
        x_color = (180, 80, 255, 255)
        chaos_line = (255, 255, 255, 240)
    else:
        body_color = (40, 44, 52, 255)
        rim_color = (120, 130, 145, 255)
        l_color = (100, 105, 115, 255)
        r_color = (100, 105, 115, 255)
        m_color = (130, 135, 145, 255)
        x_color = (100, 105, 115, 255)
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

    # Side Hotkey Buttons (X1 / X2) on the left flank
    draw.rounded_rectangle(
        [mx1 - max(1, int(size * 0.02)), my1 + h * 0.45, mx1 + max(2, int(size * 0.05)), my1 + h * 0.58],
        radius=w * 0.02,
        fill=x_color,
    )
    draw.rounded_rectangle(
        [mx1 - max(1, int(size * 0.02)), my1 + h * 0.62, mx1 + max(2, int(size * 0.05)), my1 + h * 0.75],
        radius=w * 0.02,
        fill=x_color,
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
        hotkey_manager: Optional[HotkeyManager] = None,
        flashbang_manager: Optional[Any] = None,
        on_exit_callback: Optional[Callable[[], None]] = None,
    ) -> None:
        self.randomizer = randomizer
        self.hook_manager = hook_manager
        self.hotkey_manager = hotkey_manager
        self.flashbang_manager = flashbang_manager
        self.on_exit_callback = on_exit_callback

        self._active_icon_img = generate_tray_image(64, active=True, locked=False)
        self._inactive_icon_img = generate_tray_image(64, active=False, locked=False)

        self._icon: Optional[pystray.Icon] = None

        # Link randomizer changes to menu updates
        self.randomizer._on_change_callback = self._on_mapping_changed

        # Link hotkey manager changes
        if self.hotkey_manager:
            self.hotkey_manager.on_hotkeys_changed = self._on_hotkeys_changed

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
            self._update_icon_visual()
            self._icon.update_menu()

    def _on_hotkeys_changed(self, configs) -> None:
        """Callback when keyboard hotkeys are shuffled or re-registered."""
        if self._icon:
            self._icon.update_menu()
            try:
                summary = ", ".join(cfg.name.split(" ")[0] for cfg in configs if "Emergency" not in cfg.name)
                self._icon.notify(f"ClickChaos Hotkeys Updated:\n{summary}", "Hotkeys Randomized")
            except Exception:
                pass

    def _update_icon_visual(self) -> None:
        """Switch icon image based on active and cursor locked states."""
        if not self._icon:
            return
        is_active = self.hook_manager.is_active
        is_locked = self.hook_manager.is_cursor_locked

        if is_locked:
            img = generate_tray_image(64, active=is_active, locked=True)
        else:
            img = self._active_icon_img if is_active else self._inactive_icon_img
        self._icon.icon = img

        lock_badge = " [🔒 LOCKED]" if is_locked else ""
        self._icon.title = (
            f"ClickChaos: {'ACTIVE' if is_active else 'INACTIVE'}{lock_badge} ({self.randomizer.get_summary_string()})"
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

    def toggle_cursor_lock(self) -> bool:
        """Toggle cursor freezing and refresh UI."""
        new_state = self.hook_manager.toggle_cursor_lock()
        if not new_state:
            try:
                from src.popup import dismiss_stuck_popup
                dismiss_stuck_popup()
            except Exception:
                pass
        self.update_ui()
        logger.info("Cursor Lock toggled: %s", "LOCKED" if new_state else "UNLOCKED")
        return new_state

    def toggle_teleport(self) -> bool:
        """Toggle mouse teleportation on/off and refresh UI."""
        new_state = self.hook_manager.toggle_teleport()
        self.update_ui()
        logger.info("Mouse Teleportation toggled: %s", "ENABLED" if new_state else "DISABLED")
        return new_state

    def toggle_scroll_chaos(self) -> bool:
        """Toggle scroll wheel inversion on/off and refresh UI."""
        new_state = self.hook_manager.toggle_scroll_chaos()
        self.update_ui()
        logger.info("Scroll Wheel Chaos toggled: %s", "ENABLED" if new_state else "DISABLED")
        return new_state

    def toggle_flashbang(self) -> bool:
        """Toggle random flashbang chaos on/off."""
        if self.flashbang_manager:
            new_state = self.flashbang_manager.toggle()
            self.update_ui()
            return new_state
        return False

    def trigger_flashbang_now(self) -> None:
        """Trigger an instant flashbang."""
        if self.flashbang_manager:
            self.flashbang_manager.trigger_flash()

    def randomize_now(self) -> None:
        """Trigger re-shuffle and refresh UI."""
        self.randomizer.shuffle(force_different=True)
        self.update_ui()
        logger.info("Mapping randomized: %s", self.randomizer.get_summary_string())

    def shuffle_hotkeys(self) -> None:
        """Trigger keyboard hotkey randomization."""
        if self.hotkey_manager:
            configs = self.hotkey_manager.randomize_action_hotkeys()
            self.update_ui()
            logger.info("Keyboard hotkeys randomized.")

    def reset_hotkeys(self) -> None:
        """Reset keyboard hotkeys to default bindings."""
        if self.hotkey_manager:
            self.hotkey_manager.reset_to_default_hotkeys()
            self.update_ui()
            logger.info("Keyboard hotkeys reset to defaults.")

    def emergency_disable(self) -> None:
        """Immediately turn off Chaos Mode, unlock cursor, and restore normal controls."""
        self.hook_manager.set_active(False)
        self.hook_manager.unlock_cursor()
        self.hook_manager.set_teleport_enabled(False)
        try:
            from src.popup import dismiss_stuck_popup
            dismiss_stuck_popup()
        except Exception:
            pass
        self.update_ui()
        logger.info("Emergency Disable: Chaos Mode is INACTIVE, cursor UNLOCKED, teleportation DISABLED.")

    def toggle_button_mode(self) -> None:
        """Cycle button mode: 5-button -> 3-button -> 2-button -> 5-button."""
        mid = self.randomizer.include_middle
        xbtn = self.randomizer.include_xbuttons

        if mid and xbtn:
            # Switch to 3-button
            self.randomizer.include_xbuttons = False
            self.randomizer.include_middle = True
        elif mid and not xbtn:
            # Switch to 2-button
            self.randomizer.include_middle = False
            self.randomizer.include_xbuttons = False
        else:
            # Switch back to 5-button
            self.randomizer.include_middle = True
            self.randomizer.include_xbuttons = True

        self.update_ui()
        logger.info("Button Mode cycled: %s", self.randomizer.get_summary_string())

    def _toggle_chaos(self, icon: Optional[pystray.Icon], item: Optional[MenuItem]) -> None:
        self.toggle_chaos()

    def _toggle_cursor_lock(self, icon: Optional[pystray.Icon], item: Optional[MenuItem]) -> None:
        self.toggle_cursor_lock()

    def _randomize_now(self, icon: Optional[pystray.Icon], item: Optional[MenuItem]) -> None:
        self.randomize_now()

    def _shuffle_hotkeys_action(self, icon: Optional[pystray.Icon], item: Optional[MenuItem]) -> None:
        self.shuffle_hotkeys()

    def _reset_hotkeys_action(self, icon: Optional[pystray.Icon], item: Optional[MenuItem]) -> None:
        self.reset_hotkeys()

    def _emergency_disable(self, icon: Optional[pystray.Icon], item: Optional[MenuItem]) -> None:
        self.emergency_disable()

    def _toggle_auto_shuffle(self, icon: Optional[pystray.Icon], item: Optional[MenuItem]) -> None:
        if self.randomizer.auto_shuffle_enabled:
            self.randomizer.stop_auto_shuffle()
        else:
            self.randomizer.start_auto_shuffle()
        if icon:
            icon.update_menu()

    def _set_interval(self, seconds: int) -> Callable[[Optional[pystray.Icon], Optional[MenuItem]], None]:
        def handler(icon: Optional[pystray.Icon], item: Optional[MenuItem]) -> None:
            self.randomizer.interval_seconds = seconds
            if icon:
                icon.update_menu()
        return handler

    def _exit_app(self, icon: Optional[pystray.Icon], item: Optional[MenuItem]) -> None:
        logger.info("Exiting ClickChaos...")
        self.hook_manager.set_active(False)
        self.hook_manager.unlock_cursor()
        self.hook_manager.stop()
        self.randomizer.stop_auto_shuffle()
        self.stop()

        if self.on_exit_callback:
            self.on_exit_callback()

    def _toggle_teleport(self, icon: Optional[pystray.Icon], item: Optional[MenuItem]) -> None:
        self.toggle_teleport()

    def _toggle_scroll_chaos(self, icon: Optional[pystray.Icon], item: Optional[MenuItem]) -> None:
        self.toggle_scroll_chaos()

    def _toggle_flashbang(self, icon: Optional[pystray.Icon], item: Optional[MenuItem]) -> None:
        self.toggle_flashbang()

    def _trigger_flashbang_now(self, icon: Optional[pystray.Icon], item: Optional[MenuItem]) -> None:
        self.trigger_flashbang_now()

    def _build_menu(self) -> Menu:
        """Construct the dynamic tray context menu."""
        def get_status_label(item: MenuItem) -> str:
            state = "🟢 ACTIVE" if self.hook_manager.is_active else "⚪ INACTIVE"
            lock_label = " [🔒 LOCKED]" if self.hook_manager.is_cursor_locked else ""
            tp_label = " [🌀 TELEPORT]" if self.hook_manager.is_teleport_enabled else ""
            return f"Status: {state}{lock_label}{tp_label} [{self.randomizer.get_summary_string()}]"

        def is_chaos_active(item: MenuItem) -> bool:
            return self.hook_manager.is_active

        def is_cursor_locked(item: MenuItem) -> bool:
            return self.hook_manager.is_cursor_locked

        def is_teleport_on(item: MenuItem) -> bool:
            return self.hook_manager.is_teleport_enabled

        def is_scroll_chaos_on(item: MenuItem) -> bool:
            return self.hook_manager.is_scroll_chaos_enabled

        def is_flashbang_on(item: MenuItem) -> bool:
            return self.flashbang_manager.enabled if self.flashbang_manager else False

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

        def is_mode_5_buttons(item: MenuItem) -> bool:
            return self.randomizer.include_middle and self.randomizer.include_xbuttons

        def is_mode_3_buttons(item: MenuItem) -> bool:
            return self.randomizer.include_middle and not self.randomizer.include_xbuttons

        def is_mode_2_buttons(item: MenuItem) -> bool:
            return not self.randomizer.include_middle and not self.randomizer.include_xbuttons

        def set_mode(include_middle: bool, include_xbuttons: bool) -> Callable[[Optional[pystray.Icon], Optional[MenuItem]], None]:
            def handler(icon: Optional[pystray.Icon], item: Optional[MenuItem]) -> None:
                self.randomizer.include_middle = include_middle
                self.randomizer.include_xbuttons = include_xbuttons
                if icon:
                    icon.update_menu()
            return handler

        mode_menu = Menu(
            MenuItem(
                "5-Button Mode (L, R, M, X1, X2 Side Hotkeys)",
                set_mode(True, True),
                checked=is_mode_5_buttons,
            ),
            MenuItem(
                "3-Button Mode (Left, Right, Middle)",
                set_mode(True, False),
                checked=is_mode_3_buttons,
            ),
            MenuItem(
                "2-Button Mode (Left & Right Only)",
                set_mode(False, False),
                checked=is_mode_2_buttons,
            ),
        )

        hotkey_menu_items = [
            MenuItem("Shuffle Keyboard Hotkeys Now", self._shuffle_hotkeys_action),
            MenuItem("Reset Hotkeys to Defaults", self._reset_hotkeys_action),
        ]
        if self.hotkey_manager:
            hotkey_menu_items.append(Menu.SEPARATOR)
            for name in self.hotkey_manager.get_summary_list():
                hotkey_menu_items.append(MenuItem(f"• {name}", None, enabled=False))

        hotkeys_submenu = Menu(*hotkey_menu_items)

        menu_items = [
            MenuItem(get_status_label, None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(
                "Chaos Mode (Toggle)",
                self._toggle_chaos,
                checked=is_chaos_active,
                default=True,
            ),
            MenuItem(
                "Lock Cursor (Freeze)",
                self._toggle_cursor_lock,
                checked=is_cursor_locked,
            ),
            MenuItem(
                "Mouse Teleportation (Jump)",
                self._toggle_teleport,
                checked=is_teleport_on,
            ),
            MenuItem(
                "Scroll Wheel Inversion",
                self._toggle_scroll_chaos,
                checked=is_scroll_chaos_on,
            ),
            MenuItem(
                "Random Flashbang Chaos",
                self._toggle_flashbang,
                checked=is_flashbang_on,
            ),
            MenuItem("Detonate Flashbang Now", self._trigger_flashbang_now),
            MenuItem("Randomize Buttons Now", self._randomize_now),
            MenuItem("Emergency Disable [Ctrl+Alt+X]", self._emergency_disable),
            Menu.SEPARATOR,
            MenuItem("Button Mode & Hotkeys", mode_menu),
            MenuItem("Keyboard Hotkeys Settings", hotkeys_submenu),
            MenuItem("Auto-Shuffle Settings", interval_menu),
            Menu.SEPARATOR,
            MenuItem("Exit ClickChaos", self._exit_app),
        ]

        return Menu(*menu_items)

    def _create_tray_icon(self) -> None:
        """Create and run the pystray icon loop."""
        initial_img = generate_tray_image(
            64,
            active=self.hook_manager.is_active,
            locked=self.hook_manager.is_cursor_locked,
        )
        self._icon = pystray.Icon(
            name="ClickChaos",
            icon=initial_img,
            title=f"ClickChaos: {'ACTIVE' if self.hook_manager.is_active else 'INACTIVE'} ({self.randomizer.get_summary_string()})",
            menu=self._build_menu(),
        )
        self._icon.run()
