# ClickChaos - User Guide & Technical Documentation

**ClickChaos** is a desktop systems utility for Windows that intercepts system-wide mouse events and randomly swaps the functionality of the **Left**, **Right**, and **Middle** mouse buttons.

When active, clicking the left mouse button might trigger a right-click, a middle-click might trigger a left-click, etc. The mapping automatically reshuffles at configurable intervals (or on demand) and can be easily toggled ON or OFF via the Windows system tray.

---

## Table of Contents
1. [Core Features](#core-features)
2. [Architecture & Safety Mechanisms](#architecture--safety-mechanisms)
3. [Prerequisites](#prerequisites)
4. [Installation & Setup](#installation--setup)
5. [Usage & CLI Options](#usage--cli-options)
6. [Keyboard Shortcuts (Global Hotkeys)](#keyboard-shortcuts-global-hotkeys)
7. [System Tray Controls](#system-tray-controls)
8. [Automated Testing](#automated-testing)
9. [Troubleshooting & FAQ](#troubleshooting--faq)

---

## Core Features

- **Global Low-Level Mouse Hook (`WH_MOUSE_LL`)**: Intercepts mouse click events across all Windows applications and suppresses the original hardware events before other applications receive them.
- **Ultra-Fast Movement Bypass**: Mouse movements (`WM_MOUSEMOVE`) and wheel scroll events bypass hook processing in nanoseconds, guaranteeing 0% cursor lag even on 1000Hz+ gaming mice.
- **Recursion-Proof Virtual Input Injection**: Injects synthetic clicks using Windows `SendInput` tagged with a unique 32-bit signature (`dwExtraInfo = 0xC11C4CA0`) and checks `LLMHF_INJECTED` flags to guarantee **zero hook feedback loops or system lockups**.
- **Bijective Randomization Engine**: Generates valid 1-to-1 permutations of `[LEFT, RIGHT, MIDDLE]` so no button functionality is ever lost or orphaned. Includes derangement mode ensuring every button behaves differently when chaos is active.
- **Stateful Button Tracking**: Remembers which virtual button was dispatched on `DOWN` to ensure the matching `UP` event is sent on release, preventing stuck or sticky buttons even if the mapping shuffles mid-click.
- **Lightweight System Tray UI**: Resides quietly in the Windows notification area with dynamic visual icon indicators and a context menu.

---

## Architecture & Safety Mechanisms

### Repository Layout
```text
.
├── src/
│   ├── __init__.py          # Package exports & version
│   ├── main.py              # Main orchestrator & CLI entry point
│   ├── hook_manager.py      # Low-level WH_MOUSE_LL hook, suppression & SendInput
│   ├── hotkey_manager.py    # Native Win32 RegisterHotKey global shortcuts
│   ├── randomizer.py        # 1-to-1 bijective mapping & auto-shuffle thread
│   └── tray_ui.py           # Pystray system tray UI & icon rendering
├── assets/
│   └── icon.ico             # Multi-resolution application icon
├── tests/
│   └── test_clickchaos.py   # Unit & functional test suite
├── main.py                  # Root launcher
├── run.bat                  # One-click Windows runner (detects PM, venv & launches)
├── run.sh                   # Bash runner (detects PM, venv & launches)
├── pyproject.toml           # Project metadata & uv dependencies
├── requirements.txt         # Standard pip-compatible dependencies
├── INSTRUCTIONS.md          # Comprehensive user & technical guide
└── README.md                # Preserved repository overview
```

### Hook & Injection Pipeline
```
[Physical Mouse Click]
         │
         ▼
[WH_MOUSE_LL Hook Callback (LowLevelMouseProc)]
         │
    Is event injected (LLMHF_INJECTED) or dwExtraInfo == 0xC11C4CA0?
         ├── YES ──► Pass through to CallNextHookEx (Zero recursion!)
         └── NO
              │
         Is Chaos Mode Active?
              ├── NO ──► Pass through to CallNextHookEx (Normal behavior)
              └── YES
                   │
                   ├── 1. Suppress physical event (return 1)
                   ├── 2. Map physical button ➔ target button
                   └── 3. SendInput(target_button) with dwExtraInfo signature
```

---

## Prerequisites

- **Operating System**: Windows 10 or Windows 11 (64-bit or 32-bit)
- **Python**: Python 3.10 or newer (tested with Python 3.14)
- **Package Manager**: [uv](https://github.com/astral-sh/uv) (recommended) or standard `pip`

---

## Installation & Setup

### Option 1: Using `uv` (Recommended)
`uv` automatically manages dependencies, virtual environments, and fast execution:

```powershell
# In the project directory:
uv sync
```

### Option 2: Using standard `pip`
If you prefer standard Python virtual environments:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## Usage & CLI Options

### Starting ClickChaos

#### Option A: One-Click Runner (Windows)
Double-click `run.bat` in File Explorer or run from CMD / PowerShell:
```cmd
run.bat
```
*(Automatically detects your Python package manager, checks/creates a compatible `.venv`, installs dependencies, activates the environment, and runs ClickChaos).*

#### Option B: One-Click Runner (Bash / Git Bash / macOS / Linux)
```bash
./run.sh
```

#### Option C: Direct Launch via `uv` or `python`
```powershell
uv run main.py
```
or
```powershell
python main.py
```

### Command-Line Arguments

| Flag | Description | Default |
|---|---|---|
| `--autostart` | Starts ClickChaos with Chaos Mode immediately **ACTIVE**. | `False` |
| `--lock-cursor` | Starts with mouse cursor immediately **LOCKED/FROZEN**. | `False` |
| `--teleport` | Starts with mouse cursor teleportation (jump on click) **ACTIVE**. | `False` |
| `--no-scroll-chaos` | Disables chaotic scroll wheel inversion. | `False` |
| `--no-xbuttons` | Excludes mouse side hotkeys (XButton1 and XButton2) from swapping. | `False` |
| `--interval <sec>` | Specifies the automatic reshuffle interval in seconds. | `5.0` |
| `--debug` | Enables verbose diagnostic logging in the terminal. | `False` |
| `--no-hotkeys` | Disables global keyboard shortcuts. | `False` |

#### Examples:
```powershell
# Start with Chaos Mode immediately on, reshuffling every 5 seconds (default):
uv run python -m src.main --autostart

# Start with Chaos Mode, Cursor Lock, and Mouse Teleportation active:
uv run python -m src.main --autostart --lock-cursor --teleport

# Start with a custom 15-second reshuffle interval:
uv run python -m src.main --autostart --interval 15

# Run in debug mode to see every intercepted event and mapping change:
uv run python -m src.main --debug
```

---

## Keyboard Shortcuts (Global Hotkeys)

ClickChaos registers native Windows hotkeys (`RegisterHotKey`) that work system-wide across all applications, even when your mouse buttons are scrambled.

| Shortcut | Alternative | Action | Description |
|---|---|---|---|
| <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>C</kbd> | <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>C</kbd> | **Toggle Chaos Mode** | Toggles Chaos Mode ON (swapping clicks) or OFF (normal mouse). |
| <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>R</kbd> | <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>R</kbd> | **Randomize Buttons** | Reshuffles mouse button permutations immediately. |
| <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>L</kbd> | — | **Lock Cursor (Freeze)** | Instantly freezes the mouse cursor in place or restores movement. |
| <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>T</kbd> | — | **Toggle Teleportation** | Toggles mouse cursor teleportation/jumping on clicks. |
| <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>W</kbd> | — | **Toggle Scroll Chaos** | Inverts and scrambles mouse wheel scrolling. |
| <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>K</kbd> | — | **Shuffle Hotkeys** | Randomly changes which keyboard letters control the actions. |
| <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>X</kbd> | — | **Emergency Panic Disable** | Instantly turns OFF Chaos Mode, unlocks cursor, stops teleport, and restores defaults. |
| <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>M</kbd> | — | **Cycle Button Mode** | Cycles between 5-Button (L/R/M/X1/X2), 3-Button, and 2-Button modes. |
| <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>Q</kbd> | — | **Exit ClickChaos** | Cleanly shuts down the hook, unlocks cursor, and exits. |

> **Safety Guarantee**: Native `RegisterHotKey` does not install an intrusive low-level keyboard hook (`WH_KEYBOARD_LL`), ensuring zero keylogger flags from antivirus software and zero typing lag. `Ctrl+Alt+X` is immutable and always functions as an emergency release.

---

## System Tray Controls

When ClickChaos runs, an icon appears in the Windows notification area (system tray, bottom right of the taskbar):

> **Tip**: If the icon is hidden, click the small upward arrow (`^`) on the Windows taskbar to reveal overflow icons.

### Dynamic Icon States
- **Vibrant Glowing Green/Cyan Icon**: Chaos Mode is **ACTIVE** (clicks are being swapped).
- **Orange Rim Glow**: Cursor is **LOCKED / FROZEN**.
- **Subtle Slate Gray Icon**: Chaos Mode is **INACTIVE** (mouse operates normally).

### Tray Context Menu (Right-Click)

Right-click the ClickChaos tray icon to access:
1. **Status Readout**: Displays current mode, cursor lock state, teleport badge, and mapping.
2. **Chaos Mode (Toggle)**: Turn the swapping effect ON or OFF (or double-click the tray icon).
3. **Lock Cursor (Freeze)**: Freezes the mouse cursor in place using Win32 `ClipCursor`.
4. **Mouse Teleportation (Jump)**: Teleports cursor to a random screen spot whenever a click occurs.
5. **Scroll Wheel Inversion**: Inverts and randomizes mouse wheel scrolling direction.
6. **Randomize Buttons Now**: Immediately shuffles button mapping to a new permutation.
7. **Emergency Disable**: Instantly turns off Chaos Mode, unlocks cursor, disables teleport, and releases buttons.
8. **Button Mode & Hotkeys**: Select between 5-Button (L, R, M, X1, X2 Side Hotkeys), 3-Button, and 2-Button modes.
9. **Keyboard Hotkeys Settings**: Shuffle shortcuts on demand, view current active key assignments, or reset back to default shortcuts.
10. **Auto-Shuffle Settings**:
   - Enable/Disable timer-based reshuffling.
   - Set interval presets: **5s**, **10s**, **30s**, **60s**, or **120s**.
11. **Exit ClickChaos**: Cleanly unhooks the Windows hook, releases any pressed buttons, unlocks cursor, and terminates safely.

---

## Automated Testing

Run the test suite using `uv`:

```powershell
uv run pytest -v
```

The test suite validates:
- Bijective properties of generated button mappings.
- Pure derangements (guaranteeing every button changes when randomized).
- Multi-threaded thread safety under high-frequency shuffles.
- Background auto-shuffle timer behavior.
- Windows `ctypes` data structure alignment (`INPUT`, `MOUSEINPUT`, `MSLLHOOKSTRUCT`).
- Mouse event message decoding.
- Tray icon image generation in both active and inactive states.
- Tray toggle and menu generation.

---

## Troubleshooting & FAQ

### 1. Does ClickChaos slow down my PC?
No. Its CPU usage is virtually **0.0%** and it uses only ~25 MB of RAM. Mouse movements bypass the hook in nanoseconds, so there is zero input lag even on 1000Hz gaming mice.

### 2. The mouse buttons aren't swapping inside certain games or Task Manager
Windows User Interface Privilege Isolation (UIPI) prevents standard-user hooks from receiving or injecting events into processes running with higher privileges (such as Task Manager or games running as Administrator).  
**Solution**: Right-click your terminal or PowerShell and choose **"Run as administrator"**, then launch `uv run python -m src.main`.

### 3. Can I get locked out if the mapping shuffles while I'm holding a mouse button?
No. `MouseHookManager` tracks physical button down states and matches every `DOWN` event to its corresponding `UP` event upon release. Additionally, disabling Chaos Mode automatically sends synthetic release events for any active buttons.

### 4. How do I stop ClickChaos?
Right-click the system tray icon and select **Exit ClickChaos**, or press `Ctrl + C` in the terminal where it was launched.

---

## Linux Support (Direct Kernel evdev Backend)

ClickChaos includes full Linux support, designed specifically to bypass modern X11 and Wayland display server restrictions by communicating directly with the Linux kernel input subsystem via `python-evdev`.

### Technical Architecture on Linux
- **Device Discovery**: Scans `/dev/input/` for physical pointer devices with `EV_REL` (`REL_X`, `REL_Y`) and `EV_KEY` (`BTN_LEFT`). **Strictly ignores keyboards** by excluding alphanumeric keys (`KEY_A`, `KEY_ENTER`, etc.).
- **Exclusive Device Grabbing (`EVIOCGRAB`)**: Calls `device.grab()` to lock the physical mouse at the kernel level so the OS and display server do not receive raw hardware events.
- **Virtual Injection (`evdev.UInput`)**: Instantiates a virtual mouse device (`ClickChaos-Virtual-Mouse`) capable of `EV_KEY` clicks, `EV_REL` movement, and `REL_WHEEL` scrolling.
- **Event Translation (The Chaos)**:
  - **Button Derangement**: Bijectively maps Left, Right, Middle (and side buttons if present) so no button maps to itself.
  - **Scroll Wheel Inversion**: Inverts `REL_WHEEL` deltas (+1 becomes -1).
  - **Cursor Drift (Slippery Cursor)**: Intercepts `REL_X` and `REL_Y` to inject small random offsets ($\pm 1$ or $\pm 2$ px) making the cursor feel slippery.
  - **Zero Keyboard Impact**: Affects only mouse/cursor events; keyboard devices are completely untouched.
- **CPU Efficiency**: Uses `select.select()` with epoll kernel wait queues (0% CPU usage when idle).

### Linux Permissions Setup

Grabbing raw input devices from `/dev/input/` and writing to `/dev/uinput` requires elevated permissions:

#### Option A: Run with `sudo` (Fastest)
```bash
sudo python3 clickchaos_linux.py
# or
sudo python3 main.py
```

#### Option B: Configure `udev` rules (Run without `sudo`)
1. Add your user to the `input` group:
   ```bash
   sudo usermod -a -G input $USER
   ```
2. Grant read/write access to `/dev/uinput`:
   ```bash
   echo 'KERNEL=="uinput", GROUP="input", MODE="0660"' | sudo tee /etc/udev/rules.d/99-uinput.rules
   sudo udevadm control --reload-rules && sudo udevadm trigger
   sudo modprobe uinput
   ```
3. Log out and log back in for group membership to take effect.

### Linux Safety Failsafes

Because ClickChaos exclusively grabs the physical mouse, multiple safety mechanisms guarantee you will never be locked out:
1. **Dual-Button Hold Panic**: Press and hold **[Left Click + Right Click] simultaneously for 5.0 seconds**. ClickChaos will instantly ungrab the physical mouse, close virtual devices, and exit cleanly.
2. **Auto-Exit Timer**: Specify `--auto-exit <seconds>` (e.g. `--auto-exit 30`) to automatically terminate after N seconds.
3. **Graceful Signal Handling**: `SIGINT` (`Ctrl+C`) and `SIGTERM` always trigger the `finally` block to ungrab hardware devices and restore normal mouse operation.

### Linux CLI Options
```bash
python3 clickchaos_linux.py [OPTIONS]

Options:
  --device /dev/input/eventX  Explicit path to mouse event device (default: auto-detected)
  --interval 5.0              Seconds between button reshuffles (default: 5.0s)
  --no-scroll-chaos           Disable scroll wheel inversion
  --drift                     Enable slippery cursor drift chaos
  --auto-exit 30              Automatically exit after 30 seconds
  --no-xbuttons               Disable side buttons (Mouse 4 and 5)
```

