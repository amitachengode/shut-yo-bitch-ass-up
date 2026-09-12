#!/usr/bin/env python3
"""ClickChaos - Linux Kernel Input Subsystem Edition

A utility that randomizes mouse button clicks and scroll wheel directions
using the Linux kernel input subsystem (`python-evdev` and `uinput`).
Bypasses X11 and Wayland display server restrictions.

Strictly affects only the mouse/cursor and leaves the keyboard completely untouched.

Usage:
    sudo python3 clickchaos_linux.py
    sudo python3 clickchaos_linux.py --interval 3.0 --drift --auto-exit 60

Safety Failsafe:
    Hold [Left Click + Right Click] simultaneously for 5.0 seconds to emergency exit
    and restore normal hardware mouse control.
"""

from __future__ import annotations

import argparse
import sys

from src.linux_manager import run_linux_chaos


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ClickChaos Linux: Randomize mouse button clicks and invert scroll wheels using evdev.",
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="Explicit path to /dev/input/eventX mouse device (default: auto-detect)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Interval in seconds between random shuffles (default: 5.0s)",
    )
    parser.add_argument(
        "--no-scroll-chaos",
        action="store_true",
        help="Disable chaotic scroll wheel inversion",
    )
    parser.add_argument(
        "--drift",
        action="store_true",
        help="Enable slippery cursor drift chaos",
    )
    parser.add_argument(
        "--auto-exit",
        type=float,
        default=0.0,
        help="Auto-exit after N seconds (0 = disabled)",
    )
    parser.add_argument(
        "--no-xbuttons",
        action="store_true",
        help="Do not randomize side buttons (Mouse 4 & 5)",
    )

    args = parser.parse_args()
    run_linux_chaos(args)


if __name__ == "__main__":
    main()
