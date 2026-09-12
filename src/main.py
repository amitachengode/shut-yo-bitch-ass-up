"""ClickChaos - Desktop Mouse Button Chaos Utility

Main entry point. Coordinates the low-level mouse hook, button randomizer,
system tray interface, and keyboard failsafe.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import logging
import os
import signal
import sys
import threading

from src.hook_manager import MouseHookManager
from src.hotkey_manager import HotkeyManager
from src.randomizer import ButtonRandomizer
from src.tray_ui import TrayUI


def setup_logging(debug: bool = False) -> None:
    """Configure structured logging format."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    """Application entry point."""
    parser = argparse.ArgumentParser(
        description="ClickChaos: Randomize and swap mouse button functionalities.",
    )
    parser.add_argument(
        "--autostart",
        action="store_true",
        help="Start with Chaos Mode immediately active.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Interval in seconds for automatic reshuffling (default: 5.0s).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging output.",
    )
    parser.add_argument(
        "--no-hotkeys",
        action="store_true",
        help="Disable global keyboard shortcuts.",
    )

    args = parser.parse_args()
    setup_logging(args.debug)
    logger = logging.getLogger("ClickChaos.Main")

    logger.info("Initializing ClickChaos...")
    logger.info("Controls:")
    logger.info("  • System Tray Icon: Right-click for menu, double-click to toggle")
    logger.info("  • Keyboard Shortcuts:")
    logger.info("      [Ctrl + Alt + C] or [Ctrl + Shift + C] : Toggle Chaos Mode")
    logger.info("      [Ctrl + Alt + R]                       : Randomize Mapping Now")
    logger.info("      [Ctrl + Alt + X]                       : Emergency Panic Disable")
    logger.info("      [Ctrl + Alt + M]                       : Toggle 3-Button / 2-Button Mode")
    logger.info("      [Ctrl + Alt + Q]                       : Exit ClickChaos")

    # 1. Initialize Randomizer
    randomizer = ButtonRandomizer(
        interval_seconds=args.interval,
        derangement_only=True,
    )
    # Enable background auto-shuffle
    randomizer.start_auto_shuffle()

    # 2. Initialize Low-level Hook Manager
    hook_manager = MouseHookManager(randomizer=randomizer)
    hook_manager.start()

    if args.autostart:
        logger.info("Autostart requested: Enabling Chaos Mode immediately.")
        hook_manager.set_active(True)

    # 3. Clean shutdown handler
    shutdown_lock = threading.Lock()
    is_shutting_down = False
    tray_instance = None
    hotkey_manager = None

    def shutdown() -> None:
        nonlocal is_shutting_down
        with shutdown_lock:
            if is_shutting_down:
                return
            is_shutting_down = True

        logger.info("Shutting down ClickChaos cleanly...")
        if hotkey_manager:
            hotkey_manager.stop()
        hook_manager.stop()
        randomizer.stop_auto_shuffle()
        if tray_instance:
            tray_instance.stop()

    def signal_handler(signum, frame):
        shutdown()
        # os._exit terminates immediately without raising SystemExit through ctypes callbacks
        os._exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Windows native console control handler for direct console close / Ctrl+C
    PHANDLER_ROUTINE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

    def win_console_handler(ctrl_type: int) -> bool:
        if ctrl_type in (0, 1, 2):  # CTRL_C_EVENT, CTRL_BREAK_EVENT, CTRL_CLOSE_EVENT
            shutdown()
            os._exit(0)
        return False

    _ctrl_handler = PHANDLER_ROUTINE(win_console_handler)
    ctypes.windll.kernel32.SetConsoleCtrlHandler(_ctrl_handler, True)

    # 4. Initialize System Tray UI
    tray = TrayUI(
        randomizer=randomizer,
        hook_manager=hook_manager,
        on_exit_callback=shutdown,
    )
    tray_instance = tray

    # 5. Initialize Global Hotkey Manager
    if not args.no_hotkeys:
        hotkey_manager = HotkeyManager(
            on_toggle_chaos=tray.toggle_chaos,
            on_randomize=tray.randomize_now,
            on_emergency_disable=tray.emergency_disable,
            on_toggle_middle=tray.toggle_button_mode,
            on_exit=shutdown,
        )
        hotkey_manager.start()

    # 6. Launch System Tray UI (blocks main thread until exit)
    try:
        tray.start()
    except Exception as e:
        logger.exception("Unexpected error in tray UI loop: %s", e)
    finally:
        shutdown()


if __name__ == "__main__":
    main()

