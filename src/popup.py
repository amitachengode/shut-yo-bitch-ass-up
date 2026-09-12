"""Popup overlay utility for ClickChaos cursor-stuck notifications.

Displays an eye-catching, top-most notification window on screen
informing the user that their cursor is frozen and which key they need to press
to unlock it.

Runs in an isolated child process to ensure 100% thread safety and eliminate
Tcl/Tkinter cross-thread async delete crashes on Windows.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
from typing import Optional

logger = logging.getLogger("ClickChaos.Popup")

POPUP_SCRIPT = r"""
import sys
import tkinter as tk

letter = sys.argv[1] if len(sys.argv) > 1 else 'A'

root = tk.Tk()
root.title("ClickChaos - Cursor Locked")
root.attributes("-topmost", True)
root.attributes("-alpha", 0.96)
root.overrideredirect(True)
root.configure(bg="#0F141C")

w, h = 440, 220
screen_w = root.winfo_screenwidth()
screen_h = root.winfo_screenheight()
x = (screen_w - w) // 2
y = max(80, (screen_h - h) // 3)
root.geometry(f"{w}x{h}+{x}+{y}")

# Outer glowing border
outer_border = tk.Frame(root, bg="#FF3C64", bd=2)
outer_border.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

container = tk.Frame(outer_border, bg="#141A26")
container.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

# Header
title_lbl = tk.Label(
    container,
    text="🔒 CURSOR STUCK!",
    font=("Segoe UI", 16, "bold"),
    fg="#FF3C64",
    bg="#141A26",
)
title_lbl.pack(pady=(16, 4))

# Instructions
sub_lbl = tk.Label(
    container,
    text="There is a secret key on your keyboard.\nYou have to figure it out to unlock!",
    font=("Segoe UI", 11),
    fg="#E0E6ED",
    bg="#141A26",
    justify=tk.CENTER,
)
sub_lbl.pack(pady=(4, 10))

# Mystery key badge
key_badge = tk.Label(
    container,
    text="  [ ? ]  ",
    font=("Consolas", 24, "bold"),
    fg="#0F141C",
    bg="#FFB800",
    padx=16,
    pady=4,
    relief=tk.RAISED,
)
key_badge.pack(pady=(0, 10))

tip_lbl = tk.Label(
    container,
    text="Start pressing keys to escape...",
    font=("Segoe UI", 9, "italic"),
    fg="#717D8A",
    bg="#141A26",
)
tip_lbl.pack(pady=(0, 8))

# Non-blocking stdin monitoring using a background daemon thread
def _watch_stdin():
    try:
        line = sys.stdin.readline()
        if not line or "QUIT" in line:
            root.after(0, root.destroy)
    except Exception:
        root.after(0, root.destroy)

import threading
t = threading.Thread(target=_watch_stdin, daemon=True)
t.start()

root.lift()
root.focus_force()
root.mainloop()
"""


class StuckPopup:
    """Manages spawning and cleanly dismissing the on-screen cursor stuck popup dialog."""

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    def show(self, letter: str) -> None:
        """Launch the on-screen unlock prompt popup."""
        with self._lock:
            # Dismiss any previous popup process first
            self._close_process_locked()

            try:
                # Spawn isolated child process with hidden console
                startupinfo = None
                if sys.platform == "win32":
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

                self._proc = subprocess.Popen(
                    [sys.executable, "-c", POPUP_SCRIPT, letter.upper()],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    startupinfo=startupinfo,
                )
            except Exception as e:
                logger.debug("Failed to spawn popup child process: %s", e)

    def dismiss(self) -> None:
        """Dismiss the currently visible popup."""
        with self._lock:
            self._close_process_locked()

    def _close_process_locked(self) -> None:
        """Helper to terminate the active popup child process safely."""
        proc = self._proc
        self._proc = None
        if proc and proc.poll() is None:
            try:
                if proc.stdin and not proc.stdin.closed:
                    proc.stdin.write(b"QUIT\n")
                    proc.stdin.flush()
                    proc.stdin.close()
            except Exception:
                pass

            try:
                proc.terminate()
                try:
                    proc.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    proc.kill()
            except Exception:
                pass


_global_popup = StuckPopup()


def show_stuck_popup(letter: str) -> None:
    """Convenience helper to display the stuck popup."""
    _global_popup.show(letter)


def dismiss_stuck_popup() -> None:
    """Convenience helper to dismiss the stuck popup."""
    _global_popup.dismiss()
