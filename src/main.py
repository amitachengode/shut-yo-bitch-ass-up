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

from src.flashbang import FlashbangManager
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
        stream=sys.stdout,
    )


def main() -> None:
    """Application entry point."""
    parser = argparse.ArgumentParser(
        description="ClickChaos: Randomize and swap mouse button functionalities.",
    )
    parser.add_argument(
        "--no-autostart",
        action="store_true",
        help="Start with Chaos Mode inactive (requires Ctrl+Alt+C or tray icon to activate).",
    )
    parser.add_argument(
        "--autostart",
        action="store_true",
        default=True,
        help="Start with Chaos Mode immediately active (default: True).",
    )
    parser.add_argument(
        "--lock-cursor",
        action="store_true",
        help="Start with mouse cursor immediately locked/frozen.",
    )
    parser.add_argument(
        "--no-teleport",
        action="store_true",
        help="Disable mouse cursor teleportation.",
    )
    parser.add_argument(
        "--teleport",
        action="store_true",
        default=True,
        help="Start with mouse cursor teleportation active (default: True).",
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
        default=3.0,
        help="Interval in seconds for automatic reshuffling (default: 3.0s).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging output.",
    )
    parser.add_argument(
        "--no-flashbang",
        action="store_true",
        help="Disable random blinding flashbang chaos.",
    )
    parser.add_argument(
        "--flash-min",
        type=float,
        default=1.0,
        help="Minimum seconds between random flashbangs (default: 1.0s).",
    )
    parser.add_argument(
        "--flash-max",
        type=float,
        default=30.0,
        help="Maximum seconds between random flashbangs (default: 30.0s).",
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
    logger.info("      [Ctrl + Alt + M]                       : Cycle Button Swap Mode (3 / 2 buttons)")
    logger.info("      [Ctrl + Alt + Q]                       : Exit ClickChaos")

    # 1. Initialize Randomizer (Buttons 4 and 5 excluded from remap)
    randomizer = ButtonRandomizer(
        interval_seconds=args.interval,
        derangement_only=True,
        include_middle=True,
        include_xbuttons=False,
    )

    def print_colored_mapping(mapping: Dict[ButtonType, ButtonType]) -> None:
        try:
            print(randomizer.get_colored_mapping_line(), flush=True)
        except Exception:
            logger.info("New Mapping: %s", randomizer.get_summary_string())

    randomizer.add_change_callback(print_colored_mapping)
    # Display initial randomized mapping on startup
    print_colored_mapping(randomizer.get_mapping())

    # Enable background auto-shuffle
    randomizer.start_auto_shuffle()

    # 2. Initialize Low-level Hook Manager
    hook_manager = MouseHookManager(randomizer=randomizer)
    if not args.no_teleport:
        logger.info("Mouse cursor teleportation ENABLED on startup (use --no-teleport or Ctrl+Alt+T to disable).")
        hook_manager.set_teleport_enabled(True)
    else:
        logger.info("Mouse cursor teleportation started DISABLED (--no-teleport).")
    if args.no_scroll_chaos:
        hook_manager.set_scroll_chaos_enabled(False)

    hook_manager.start()

    if not args.no_autostart:
        logger.info("Enabling Chaos Mode immediately on startup.")
        hook_manager.set_active(True)
    else:
        logger.info("Chaos Mode started INACTIVE (--no-autostart). Press [Ctrl + Alt + C] or double-click tray icon to activate.")

    if args.lock_cursor:
        logger.info("Lock cursor requested: Locking mouse cursor immediately.")
        hook_manager.lock_cursor()

    # 3. Initialize Flashbang Manager (Fullscreen white flash at random points in time)
    flashbang_manager = FlashbangManager(
        min_interval=args.flash_min,
        max_interval=args.flash_max,
        sound_enabled=True,
        enabled=not args.no_flashbang,
    )
    if not args.no_flashbang:
        logger.info(
            "Flashbang chaos scheduled: detonating at random intervals between %.1fs and %.1fs.",
            args.flash_min,
            args.flash_max,
        )
        flashbang_manager.start_scheduler()
    else:
        logger.info("Flashbang chaos started DISABLED (--no-flashbang).")

    # 4. Clean shutdown handler
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
        from src.popup import dismiss_stuck_popup
        dismiss_stuck_popup()
        flashbang_manager.stop_scheduler()
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

    # 5. Initialize System Tray UI
    tray = TrayUI(
        randomizer=randomizer,
        hook_manager=hook_manager,
        flashbang_manager=flashbang_manager,
        on_exit_callback=shutdown,
    )
    tray_instance = tray

    # 6. Initialize Global Hotkey Manager
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
        
        import string
        import random
        from src.popup import show_stuck_popup, dismiss_stuck_popup

        def on_stuck():
            letter = random.choice(string.ascii_uppercase)
            print(f"\n=======================================================", flush=True)
            print(f"   CURSOR STUCK! Find the secret key on your keyboard! ", flush=True)
            print(f"=======================================================\n", flush=True)
            show_stuck_popup(letter)

            def unlock_and_dismiss():
                hook_manager.unlock_cursor()
                dismiss_stuck_popup()
                tray.update_ui()

            hotkey_manager.register_unlock_key(letter, unlock_and_dismiss)
            
        hook_manager.set_on_stuck_callback(on_stuck)

    # 7. Launch System Tray UI (blocks main thread until exit)
    try:
        tray.start()
    except Exception as e:
        logger.exception("Unexpected error in tray UI loop: %s", e)
    finally:
        shutdown()


if __name__ == "__main__":
    main()
