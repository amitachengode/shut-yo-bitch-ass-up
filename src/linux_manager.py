"""ClickChaos - Linux evdev Kernel Input Subsystem Port

Directly interfaces with the Linux kernel input subsystem using `python-evdev`,
bypassing X11 and Wayland display server restrictions.
Exclusively grabs the physical mouse via EVIOCGRAB, injects chaos through a
virtual UInput mouse, and implements dual-button hold and timeout safety failsafes.
"""

from __future__ import annotations

import logging
import os
import random
import select
import signal
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("ClickChaos.Linux")

# ANSI Terminal Colors
BOLD = "\033[1m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
RESET = "\033[0m"

# Standard Linux Kernel Input Subsystem UAPI Constants (<linux/input-event-codes.h>)
EV_SYN = 0x00
EV_KEY = 0x01
EV_REL = 0x02

REL_X = 0x00
REL_Y = 0x01
REL_HWHEEL = 0x06
REL_WHEEL = 0x08

BTN_LEFT = 0x110
BTN_RIGHT = 0x111
BTN_MIDDLE = 0x112
BTN_SIDE = 0x113    # XButton 1 / Mouse 4
BTN_EXTRA = 0x114   # XButton 2 / Mouse 5


def check_linux_permissions() -> Tuple[bool, str]:
    """Check if the current process has permissions to read /dev/input and write /dev/uinput."""
    if not sys.platform.startswith("linux"):
        return False, "Current operating system is not Linux."

    issues = []
    # Check /dev/input access
    if not os.path.exists("/dev/input"):
        issues.append("Directory '/dev/input' does not exist.")
    elif not os.access("/dev/input", os.R_OK):
        issues.append("No read permission for '/dev/input'.")

    # Check /dev/uinput access
    uinput_paths = ["/dev/uinput", "/dev/input/uinput"]
    has_uinput = False
    for p in uinput_paths:
        if os.path.exists(p):
            if os.access(p, os.W_OK | os.R_OK):
                has_uinput = True
                break
            else:
                issues.append(f"No read/write permission for '{p}'.")
                has_uinput = True
                break

    if not has_uinput and not issues:
        issues.append("Neither '/dev/uinput' nor '/dev/input/uinput' was found. Try 'sudo modprobe uinput'.")

    if issues:
        msg = (
            f"{RED}{BOLD}[PERMISSION ERROR]{RESET}\n"
            + "\n".join(f"  • {issue}" for issue in issues)
            + f"\n\n{YELLOW}To fix this, either:{RESET}\n"
            f"  1. Run with root privileges: {CYAN}sudo python main.py{RESET}\n"
            f"  2. Or add your user to the 'input' group and grant /dev/uinput access:\n"
            f"     {CYAN}sudo usermod -a -G input $USER{RESET}\n"
            f"     {CYAN}echo 'KERNEL==\"uinput\", GROUP=\"input\", MODE=\"0660\"' | sudo tee /etc/udev/rules.d/99-uinput.rules{RESET}\n"
            f"     {CYAN}sudo udevadm control --reload-rules && sudo udevadm trigger{RESET}\n"
            f"     (Note: Log out and log back in for group changes to take effect)\n"
        )
        return False, msg

    return True, "Permissions OK"


class LinuxMouseChaosManager:
    """Manages evdev mouse grabbing, virtual mouse injection, button & scroll chaos."""

    # Default button code mappings
    BTN_LEFT = 0x110
    BTN_RIGHT = 0x111
    BTN_MIDDLE = 0x112
    BTN_SIDE = 0x113    # XButton 1 / Mouse 4
    BTN_EXTRA = 0x114   # XButton 2 / Mouse 5

    BUTTON_NAMES = {
        0x110: "Left Click (BTN_LEFT)",
        0x111: "Right Click (BTN_RIGHT)",
        0x112: "Middle Click (BTN_MIDDLE)",
        0x113: "Side Button 1 (BTN_SIDE)",
        0x114: "Side Button 2 (BTN_EXTRA)",
    }

    BUTTON_COLORS = {
        0x110: "\033[94m",  # Blue
        0x111: "\033[91m",  # Red
        0x112: "\033[92m",  # Green
        0x113: "\033[93m",  # Yellow
        0x114: "\033[95m",  # Magenta
    }

    # Keys that identify keyboards to exclude them
    KEYBOARD_EXCLUDE_KEYS = {
        1,   # KEY_ESC
        28,  # KEY_ENTER
        30,  # KEY_A
        31,  # KEY_S
        57,  # KEY_SPACE
    }

    def __init__(
        self,
        device_path: Optional[str] = None,
        shuffle_interval: float = 5.0,
        scroll_chaos: bool = True,
        cursor_drift: bool = False,
        failsafe_hold_duration: float = 5.0,
        auto_exit_seconds: float = 0.0,
        include_side_buttons: bool = True,
    ) -> None:
        self.device_path = device_path
        self.shuffle_interval = shuffle_interval
        self.scroll_chaos = scroll_chaos
        self.cursor_drift = cursor_drift
        self.failsafe_hold_duration = failsafe_hold_duration
        self.auto_exit_seconds = auto_exit_seconds
        self.include_side_buttons = include_side_buttons

        self._running = False
        self._device: Any = None
        self._uinput: Any = None

        self._available_buttons: List[int] = [self.BTN_LEFT, self.BTN_RIGHT, self.BTN_MIDDLE]
        self._button_mapping: Dict[int, int] = {}
        self._active_presses: Dict[int, int] = {}  # physical_code -> synthetic_code

        self._left_down_time: Optional[float] = None
        self._right_down_time: Optional[float] = None
        self._last_shuffle_time: float = 0.0
        self._start_time: float = 0.0

    @classmethod
    def find_mouse_devices(cls) -> List[Any]:
        """Scan /dev/input/ for physical mouse devices, strictly ignoring keyboards."""
        try:
            import evdev
        except ImportError:
            raise RuntimeError("python-evdev is required on Linux. Install via 'pip install evdev'.")

        devices = []
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
                caps = dev.capabilities()

                # Must have relative axes (REL_X and REL_Y)
                if EV_REL not in caps:
                    continue
                rel_axes = caps[EV_REL]
                if REL_X not in rel_axes or REL_Y not in rel_axes:
                    continue

                # Must have key capabilities including BTN_LEFT
                if EV_KEY not in caps:
                    continue
                keys = caps[EV_KEY]
                if BTN_LEFT not in keys:
                    continue

                # Must NOT be an alphanumeric keyboard
                if any(k in keys for k in cls.KEYBOARD_EXCLUDE_KEYS):
                    logger.debug("Skipping device %s (%s) - contains keyboard keys", dev.name, path)
                    continue

                devices.append(dev)
            except Exception as e:
                logger.debug("Error inspecting device at %s: %s", path, e)
                continue

        return devices

    def generate_derangement(self, buttons: List[int]) -> Dict[int, int]:
        """Generate a random derangement (no button mapped to itself) among the given buttons."""
        n = len(buttons)
        if n <= 1:
            return {b: b for b in buttons}
        if n == 2:
            return {buttons[0]: buttons[1], buttons[1]: buttons[0]}

        max_attempts = 100
        for _ in range(max_attempts):
            shuffled = list(buttons)
            random.shuffle(shuffled)
            if all(buttons[i] != shuffled[i] for i in range(n)):
                return dict(zip(buttons, shuffled))

        # Fallback cyclic shift
        return {buttons[i]: buttons[(i + 1) % n] for i in range(n)}

    def shuffle_mapping(self) -> None:
        """Shuffle the active button mapping with a fresh derangement."""
        new_mapping = self.generate_derangement(self._available_buttons)
        self._button_mapping = new_mapping
        self._last_shuffle_time = time.monotonic()
        self.print_mapping_card()

    def get_colored_mapping_card(self) -> str:
        """Generate a colored terminal card displaying current button translations."""
        lines = []
        border = f"{CYAN}═" * 60 + f"{RESET}"
        lines.append(border)
        lines.append(f"{CYAN}║{RESET}  {BOLD}{MAGENTA}LINUX CLICKCHAOS: ACTIVE MOUSE BUTTON MAPPING{RESET}")
        lines.append(f"{CYAN}║{RESET}  {YELLOW}Kernel Subsystem: evdev + EVIOCGRAB virtual injection{RESET}")
        lines.append(border)

        for src in self._available_buttons:
            dst = self._button_mapping.get(src, src)
            src_name = self.BUTTON_NAMES.get(src, f"0x{src:x}")
            dst_name = self.BUTTON_NAMES.get(dst, f"0x{dst:x}")
            src_col = self.BUTTON_COLORS.get(src, CYAN)
            dst_col = self.BUTTON_COLORS.get(dst, YELLOW)

            lines.append(
                f"{CYAN}║{RESET}  {src_col}{BOLD}{src_name:<26}{RESET} ➔ {dst_col}{BOLD}{dst_name}{RESET}"
            )

        lines.append(border)
        scroll_status = f"{GREEN}INVERTED (Chaotic){RESET}" if self.scroll_chaos else f"{YELLOW}NORMAL{RESET}"
        drift_status = f"{MAGENTA}ENABLED (Slippery){RESET}" if self.cursor_drift else f"{YELLOW}DISABLED{RESET}"
        lines.append(f"{CYAN}║{RESET}  Scroll Wheel Chaos : {scroll_status}")
        lines.append(f"{CYAN}║{RESET}  Cursor Drift       : {drift_status}")
        lines.append(
            f"{CYAN}║{RESET}  {RED}{BOLD}SAFETY FAILSAFE    : Hold [Left + Right Click] for 5.0s to Exit!{RESET}"
        )
        lines.append(border)
        return "\n".join(lines)

    def print_mapping_card(self) -> None:
        """Print the colored mapping card to stdout."""
        try:
            print("\n" + self.get_colored_mapping_card() + "\n", flush=True)
        except Exception as e:
            logger.info("Button Mapping: %s", self._button_mapping)

    def setup_devices(self) -> None:
        """Select physical mouse device, grab it, and create UInput virtual mouse."""
        import evdev
        from evdev import UInput

        if self.device_path:
            logger.info("Connecting to specified device: %s", self.device_path)
            self._device = evdev.InputDevice(self.device_path)
        else:
            candidates = self.find_mouse_devices()
            if not candidates:
                raise RuntimeError(
                    "No physical mouse devices found under /dev/input/. "
                    "Ensure a mouse is connected or specify a device with --device /dev/input/eventX."
                )
            self._device = candidates[0]
            logger.info("Auto-detected primary physical mouse: '%s' (%s)", self._device.name, self._device.path)

        caps = self._device.capabilities()
        key_caps = caps.get(EV_KEY, [])

        # Check for side buttons (Mouse 4 / Mouse 5)
        self._available_buttons = [self.BTN_LEFT, self.BTN_RIGHT, self.BTN_MIDDLE]
        if self.include_side_buttons:
            if BTN_SIDE in key_caps and BTN_EXTRA in key_caps:
                self._available_buttons.extend([self.BTN_SIDE, self.BTN_EXTRA])
                logger.info("Hardware side buttons (BTN_SIDE, BTN_EXTRA) detected and enabled.")
            else:
                logger.info("Hardware side buttons not found on device; using standard 3-button mode.")

        # Construct virtual mouse capabilities
        uinput_caps = {
            EV_KEY: [BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA],
            EV_REL: [REL_X, REL_Y, REL_WHEEL, REL_HWHEEL],
        }

        # Include any extra relative or button capabilities from physical mouse
        if EV_REL in caps:
            for rel_code in caps[EV_REL]:
                if rel_code not in uinput_caps[EV_REL]:
                    uinput_caps[EV_REL].append(rel_code)

        logger.info("Instantiating virtual UInput device 'ClickChaos-Virtual-Mouse'...")
        self._uinput = UInput(uinput_caps, name="ClickChaos-Virtual-Mouse")

        # Exclusive device grabbing
        logger.info("Exclusively grabbing physical mouse via EVIOCGRAB...")
        self._device.grab()
        logger.info("Physical mouse successfully locked! Chaos Mode is active.")

    def run(self) -> None:
        """Main event loop: process events from physical mouse, translate, and inject."""
        import evdev
        from evdev import ecodes

        self.setup_devices()
        self.shuffle_mapping()

        self._running = True
        self._start_time = time.monotonic()
        self._last_shuffle_time = self._start_time

        # Setup graceful signal handlers
        def sig_handler(signum, frame):
            logger.info("Signal received (%s). Triggering clean shutdown...", signum)
            self._running = False

        old_sigint = signal.signal(signal.SIGINT, sig_handler)
        old_sigterm = signal.signal(signal.SIGTERM, sig_handler)

        try:
            while self._running:
                now = time.monotonic()

                # Check auto-exit timer
                if self.auto_exit_seconds > 0:
                    if (now - self._start_time) >= self.auto_exit_seconds:
                        logger.warning(
                            "Auto-exit timer (%.1fs) expired! Cleaning up and exiting...",
                            self.auto_exit_seconds,
                        )
                        break

                # Check failsafe: Left + Right held for 5.0 seconds
                if self._left_down_time is not None and self._right_down_time is not None:
                    hold_time = min(now - self._left_down_time, now - self._right_down_time)
                    if hold_time >= self.failsafe_hold_duration:
                        print(
                            f"\n{RED}{BOLD}🚨 SAFETY FAILSAFE TRIGGERED! "
                            f"Left + Right click held for {hold_time:.1f}s. Emergency ungrab and exiting! 🚨{RESET}\n",
                            flush=True,
                        )
                        logger.warning("Emergency failsafe triggered: exiting immediately.")
                        break

                # Check automatic re-shuffle timer
                if self.shuffle_interval > 0 and (now - self._last_shuffle_time) >= self.shuffle_interval:
                    self.shuffle_mapping()

                # Poll device using select with 0.05s timeout to prevent CPU busy-waiting
                r, _, _ = select.select([self._device.fd], [], [], 0.05)
                if not r:
                    continue

                for event in self._device.read():
                    self._process_event(event)

        finally:
            self.cleanup()
            signal.signal(signal.SIGINT, old_sigint)
            signal.signal(signal.SIGTERM, old_sigterm)

    def _process_event(self, event: Any) -> None:
        """Translate a single input event and write to virtual UInput mouse."""
        now = time.monotonic()

        # 1. EV_KEY: Mouse button events
        if event.type == EV_KEY:
            code = event.code
            value = event.value  # 1 = Press, 0 = Release

            # Track physical press times for failsafe
            if code == BTN_LEFT:
                self._left_down_time = now if value == 1 else None
            elif code == BTN_RIGHT:
                self._right_down_time = now if value == 1 else None

            # Check if this button is part of chaos mapping
            if code in self._available_buttons:
                if value == 1:
                    # Button Press: Map to destination button
                    target_btn = self._button_mapping.get(code, code)
                    self._active_presses[code] = target_btn
                    self._uinput.write(EV_KEY, target_btn, 1)
                else:
                    # Button Release: Release whatever target button was pressed
                    target_btn = self._active_presses.pop(code, self._button_mapping.get(code, code))
                    self._uinput.write(EV_KEY, target_btn, 0)
            else:
                # Forward other buttons unchanged
                self._uinput.write(EV_KEY, code, value)

            self._uinput.syn()
            return

        # 2. EV_REL: Relative movement & scroll wheel
        if event.type == EV_REL:
            code = event.code
            value = event.value

            # Scroll wheel chaos: Invert scroll delta
            if code == REL_WHEEL:
                if self.scroll_chaos:
                    value = -value
                self._uinput.write(EV_REL, code, value)
                self._uinput.syn()
                return

            # Cursor drift: Add random offset to REL_X / REL_Y
            if self.cursor_drift and code in (REL_X, REL_Y):
                # 30% chance to add a small offset (-2 to +2 pixels)
                if random.random() < 0.30:
                    offset = random.choice([-2, -1, 1, 2])
                    value += offset

            self._uinput.write(EV_REL, code, value)
            self._uinput.syn()
            return

        # 3. Forward all other events (EV_SYN, etc.)
        self._uinput.write(event.type, event.code, event.value)
        if event.type == EV_SYN:
            self._uinput.syn()

    def cleanup(self) -> None:
        """Strictly release all pressed buttons, ungrab the physical mouse, and close UInput."""
        logger.info("Cleaning up Linux ClickChaos resources...")
        self._running = False

        # Release any stuck virtual buttons
        if self._uinput is not None:
            try:
                for phys, target in list(self._active_presses.items()):
                    self._uinput.write(EV_KEY, target, 0)
                self._uinput.syn()
            except Exception as e:
                logger.debug("Error releasing virtual buttons during cleanup: %s", e)

        # Ungrab physical mouse (EVIOCGRAB release)
        if self._device is not None:
            try:
                logger.info("Ungrabbing physical device %s...", self._device.path)
                self._device.ungrab()
                logger.info("Physical mouse successfully ungrabbed.")
            except Exception as e:
                logger.warning("Error ungrabbing device %s: %s", self._device.path, e)
            self._device = None

        # Close virtual UInput device
        if self._uinput is not None:
            try:
                self._uinput.close()
                logger.info("Virtual UInput device closed.")
            except Exception as e:
                logger.debug("Error closing UInput: %s", e)
            self._uinput = None


def run_linux_chaos(args: Any) -> None:
    """Entry point when executed on Linux."""
    print(f"\n{GREEN}{BOLD}======================================================{RESET}")
    print(f"{GREEN}{BOLD}      🐧 LINUX OPERATING SYSTEM DETECTED 🐧           {RESET}")
    print(f"{GREEN}{BOLD}======================================================{RESET}")
    print(f"Activating Linux Kernel Input Subsystem backend (`evdev` + `EVIOCGRAB`).")
    print(f"Bypassing X11/Wayland display server restrictions.\n")

    has_perm, perm_msg = check_linux_permissions()
    if not has_perm:
        print(perm_msg)
        sys.exit(1)

    device_arg = getattr(args, "device", None)
    interval_arg = getattr(args, "interval", 5.0)
    no_scroll = getattr(args, "no_scroll_chaos", False)
    no_xbuttons = getattr(args, "no_xbuttons", False)
    drift = getattr(args, "drift", False)
    auto_exit = getattr(args, "auto_exit", 0.0)

    manager = LinuxMouseChaosManager(
        device_path=device_arg,
        shuffle_interval=interval_arg,
        scroll_chaos=not no_scroll,
        cursor_drift=drift,
        failsafe_hold_duration=5.0,
        auto_exit_seconds=auto_exit,
        include_side_buttons=not no_xbuttons,
    )

    try:
        manager.run()
    except Exception as e:
        logger.exception("Linux ClickChaos terminated with error: %s", e)
        manager.cleanup()
        sys.exit(1)
