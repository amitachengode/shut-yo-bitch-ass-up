"""ClickChaos - Desktop Mouse Button Chaos Utility

Main entry point. Coordinates the low-level mouse hook, button randomizer,
system tray interface, cursor locking, and keyboard failsafes.
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
        "--lock-cursor",
        action="store_true",
        help="Start with mouse cursor immediately locked/frozen.",
    )
    parser.add_argument(
        "--teleport",
        action="store_true",
        help="Start with mouse cursor teleportation immediately active.",
    )
    parser.add_argument(
        "--no-scroll-chaos",
        action="store_true",
        help="Disable chaotic scroll wheel inversion.",
    )
    parser.add_argument(
        "--no-xbuttons",
        action="store_true",
        help="Disable swapping side mouse hotkey buttons (XButton1 and XButton2).",
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
    # Linux-specific arguments
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="[Linux] Explicit path to /dev/input/eventX device.",
    )
    parser.add_argument(
        "--drift",
        action="store_true",
        help="[Linux] Enable slippery cursor drift chaos.",
    )
    parser.add_argument(
        "--auto-exit",
        type=float,
        default=0.0,
        help="[Linux/Failsafe] Automatically exit after N seconds (0 = disabled).",
    )

    args = parser.parse_args()
    setup_logging(args.debug)
    logger = logging.getLogger("ClickChaos.Main")

    # --- Operating System Detection ---
    if sys.platform.startswith("linux"):
        from src.linux_manager import run_linux_chaos
        run_linux_chaos(args)
        return

    logger.info("Initializing ClickChaos...")
    logger.info("Controls:")
    logger.info("  • System Tray Icon: Right-click for menu, double-click to toggle")
    logger.info("  • Keyboard Shortcuts:")
    logger.info("      [Ctrl + Alt + C] or [Ctrl + Shift + C] : Toggle Chaos Mode")
    logger.info("      [Ctrl + Alt + R]                       : Randomize Button Mapping Now")
    logger.info("      [Ctrl + Alt + L]                       : Toggle Cursor Lock (Freeze Cursor)")
    logger.info("      [Ctrl + Alt + T]                       : Toggle Mouse Teleportation")
    logger.info("      [Ctrl + Alt + W]                       : Toggle Scroll Wheel Chaos")
    logger.info("      [Ctrl + Alt + K]                       : Shuffle Keyboard Shortcuts")
    logger.info("      [Ctrl + Alt + X]                       : Emergency Panic Disable")
    logger.info("      [Ctrl + Alt + M]                       : Cycle Button Swap Mode (5 / 3 / 2 buttons)")
    logger.info("      [Ctrl + Alt + Q]                       : Exit ClickChaos")

    from src.randomizer import are_buttons_4_and_5_present, detect_mouse_button_count

    btn_count = detect_mouse_button_count()
    has_xbtns = are_buttons_4_and_5_present()

    if args.no_xbuttons:
        include_x = False
        logger.info("Mouse hardware: %d buttons detected. Buttons 4 & 5 disabled via --no-xbuttons flag.", btn_count)
    elif has_xbtns:
        include_x = True
        logger.info(
            "Mouse hardware: %d buttons detected. Buttons 4 & 5 (X1 & X2 side hotkeys) are PRESENT and ENABLED for randomizing.",
            btn_count,
        )
    else:
        include_x = False
        logger.info(
            "Mouse hardware: %d buttons detected. Buttons 4 & 5 (X1 & X2) are NOT present on this mouse and will be IGNORED for randomizing.",
            btn_count,
        )

    # 1. Initialize Randomizer
    randomizer = ButtonRandomizer(
        interval_seconds=args.interval,
        derangement_only=True,
        include_middle=True,
        include_xbuttons=include_x,
    )

    def print_colored_mapping(mapping: Dict[ButtonType, ButtonType]) -> None:
        try:
            print("\n" + randomizer.get_colored_mapping_card() + "\n", flush=True)
        except Exception:
            logger.info("New Mapping: %s", randomizer.get_summary_string())

    randomizer.add_change_callback(print_colored_mapping)
    # Display initial randomized mapping on startup
    print_colored_mapping(randomizer.get_mapping())

    # Enable background auto-shuffle
    randomizer.start_auto_shuffle()

    # 2. Initialize Low-level Hook Manager
    hook_manager = MouseHookManager(randomizer=randomizer)
    if args.teleport:
        logger.info("Teleport mode requested: Enabling mouse cursor teleportation on startup.")
        hook_manager.set_teleport_enabled(True)
    if args.no_scroll_chaos:
        hook_manager.set_scroll_chaos_enabled(False)

    hook_manager.start()

    if args.autostart:
        logger.info("Autostart requested: Enabling Chaos Mode immediately.")
        hook_manager.set_active(True)

    if args.lock_cursor:
        logger.info("Lock cursor requested: Locking mouse cursor immediately.")
        hook_manager.lock_cursor()

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
            on_toggle_cursor_lock=tray.toggle_cursor_lock,
            on_toggle_teleport=tray.toggle_teleport,
            on_toggle_scroll=tray.toggle_scroll_chaos,
            on_shuffle_hotkeys=tray.shuffle_hotkeys,
            on_exit=shutdown,
        )
        tray.hotkey_manager = hotkey_manager
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
