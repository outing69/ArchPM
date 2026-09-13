# ArchPM

> **Built with AI, in the open.** This project was written with Claude (via Claude
> Code), from the first line of code to this README. I set the direction, decided
> what goes in and what stays out, and tested everything on my own machine; the
> AI wrote most of the code. I'm saying so up front because you deserve to know
> that when you read a root helper written by someone else. About me: three years
> on Linux, almost a year on CachyOS. Not an expert in Linux or Arch, but not a
> beginner either. Read the code, and `SECURITY.md`, with that in mind.

Process management and monitoring for a Linux gaming PC. Three parts that share
the same measurement core:

| Component | What it is |
|---|---|
| **GUI** (`python3 -m archpm`) | PySide6 window: Overview, Processes, Startup and System tabs |
| **Agent** (`archpm-agent`) | systemd --user service that samples every 2 s and writes `status.json` |
| **Widget** | Plasma 6 plasmoid on your desktop that reads that `status.json` |

## Screenshots

**Overview** — CPU, GPU, memory and I/O at a glance, plus the heaviest processes.

![Overview tab](docs/overview.png)

**Processes** — the full list with CPU, memory, per-process GPU usage, nice and disk I/O. Right-click a row to terminate, suspend, renice or pin it to cores.

![Processes tab](docs/processes.png)

**Widget** — the Plasma plasmoid, fed by the agent, so it keeps working when the GUI is closed.

<img src="docs/widget.png" width="320" alt="Plasma widget">

## Status and support

Built for and tested on one machine: CachyOS (Arch), KDE Plasma 6 on Wayland,
an AMD Ryzen 7800X3D and an NVIDIA RTX 5070. It will probably work on any Arch
derivative with Plasma 6 and an NVIDIA card. AMD GPUs use a sysfs
fallback that has only been exercised on the Ryzen's integrated Radeon (which it
reports as "AMD Raphael", with temperature, power and clock). Other
desktops get the GUI but not the widget.

This is a personal tool that I am sharing in case it is useful to you. There
is **no support**: if it does not work on your PC, I probably cannot help. Bug
reports and patches are welcome, but there is no promise that I will act on
them. The license is MIT, so feel free to fork it and make it your own.

See `SECURITY.md` for what the root helper does and does not protect against.

## Requirements

Arch Linux or a derivative (CachyOS, EndeavourOS, Manjaro). Package names below
are Arch's; on another distribution find the equivalents.

| For | Packages | Notes |
|---|---|---|
| GUI and agent | `python` (3.10+), `pyside6` (6.5+), `python-psutil` (5.9+), `git` | the only hard requirements |
| Widget | KDE Plasma 6 (`plasma-desktop`, `kpackage`) | other desktops get the GUI but no widget |
| Root tasks | `polkit` | provides `pkexec`; your user must be allowed to authenticate as admin (in Arch that is the `wheel` group) |
| NVIDIA telemetry | `nvidia-utils` | provides `nvidia-smi`; without it the GPU falls back to sysfs |
| AMD telemetry | nothing extra | read from sysfs; `hwdata` gives the card a proper name |
| Agent as a service | a systemd user session | standard on any systemd desktop |

## Installing

First the packages. Pick the one line for the package manager you use; the
commands are the same in fish, bash and zsh.

```bash
# pacman (plain Arch, CachyOS)
sudo pacman -S --needed python pyside6 python-psutil polkit git

# paru
paru -S --needed python pyside6 python-psutil polkit git

# yay
yay -S --needed python pyside6 python-psutil polkit git
```

Optional, for the full experience: `plasma-desktop` (the widget),
`nvidia-utils` (NVIDIA telemetry), `hwdata` (proper AMD GPU names).

Then ArchPM itself:

```bash
git clone https://github.com/outing69/ArchPM.git && cd ArchPM
./install.sh          # agent, widget, menu entry  (no root needed)
./install.sh --root   # the pkexec helper and the polkit policy
```

Then: right-click your desktop → *Add Widgets* → **ArchPM Monitor**.

The GUI and agent are also a regular Python package (`pyproject.toml`, console
scripts `archpm` and `archpm-agent`), so `pipx install git+https://github.com/outing69/ArchPM`
works too. That gives you the window and the sampler, but not the widget, the
systemd unit or the root helper; those still come from `install.sh`.

Requirements: Python 3.10+, PySide6 6.5+, psutil 5.9+. Tested with newer versions of all three.

### As a package

`packaging/aur/` holds a PKGBUILD that installs everything in its proper place:
console scripts in `/usr/bin`, the root helper in `/usr/lib/archpm`, the polkit
policy, a systemd user unit and the widget. Until it is on the AUR, build it
yourself:

```bash
cd packaging/aur && makepkg -si
systemctl --user enable --now archpm-agent
```

Do not mix the two routes: run `./install.sh --uninstall-root` before installing
the package, or the polkit policy file will conflict.

## What it measures

- **CPU** — total, per logical core, frequency, load and Tctl temperature. The
  per-core strip shows at most 64 bars in the GUI and 32 in the widget; bigger
  CPUs are shown as group averages (labelled "0-1", "2-3", …).
- **GPU** — SM utilisation, VRAM, temperature, power draw and clock speed, plus
  **per-process GPU usage** via `nvidia-smi pmon` (works for games too, not
  just CUDA). AMD/Intel fall back to sysfs, without per-process data.
- **Processes** — CPU, RSS, threads, nice, disk I/O, VRAM, affinity, start time.
  Shown as a tree by parent (Steam → reaper → Proton → game) or flat. Programs
  with a `.desktop` entry get their proper name, icon and category; Steam games
  get the game's name and Steam's icon for it. No icon is shown for anything
  that has none. By default you see your programs plus whatever is busy; "Show
  all processes" shows everything. A collapsed program shows the totals of its
  whole tree, so a browser reads as one row with its real memory use.
- **Game** — a card on the Overview for whatever game is running: its whole
  process tree's CPU, GPU, VRAM, RAM and threads, how many cores it may use, and
  a graph of its last minutes. Steam games are found by app id; anything else
  doing real GPU work qualifies too.
- **History** — select a process and the last minutes of its CPU, GPU and memory
  appear under the list; a collapsed program shows its whole tree.
- **Startup** — what starts when you log in (XDG autostart), with a switch per
  entry and whether it is running now. Switching off writes an override in your
  own `~/.config/autostart`; nothing outside your home is touched.
- **System** — the machine's specs on one card: CPU, memory, GPUs and drivers,
  motherboard, kernel, desktop, disks, network. "Copy as text" for forum posts.
- **System** — network and disk throughput, swap, sensors

## What you can do with it

Right-click in the process list: terminate (SIGTERM), force kill (SIGKILL),
suspend/resume (SIGSTOP/SIGCONT), set nice, set disk priority, and choose CPU
affinity per process — with presets for "physical cores only" (no SMT
siblings) and each half. In tree view, "Terminate with children" takes a whole
process tree down at once, so a killed game does not leave its launcher behind.

## Permissions

The app runs as your own user. In that mode you can only control your own
processes and only raise nice. Everything that needs more sits behind a single
button: **Overview → Root tasks**.

That separation is the core of the design:

- `archpm/root/helper.py` is the **only** file that runs as root. It lives
  root-owned in `/usr/lib/archpm/archpm-helper` (`/usr/local/lib/…` when installed
  from a checkout; pkexec refuses a program that
  a regular user can modify), imports nothing from this project and never
  starts a shell.
- `polkit/io.github.outing69.archpm.policy` decides who may authenticate. With
  `auth_admin_keep` polkit asks for your password once and remembers it for
  about five minutes.
- `archpm/root/client.py` only builds the `pkexec` call and reads the JSON reply.
  The GUI never sees a password.
- The helper validates on its own: fixed subcommands, numeric bounds, a
  unit-name regex, and a list of services (dbus, logind, polkit, the display
  manager) it refuses to stop.

`ElevatedBackend` tries every action without privileges first. Only when that
is denied does it go through the helper — so you never get a password prompt
for something you were already allowed to do.

### What the root panel contains

| Group | Actions |
|---|---|
| Processes | negative nice, realtime IO, acting on other users' processes |
| Services and memory | start/stop/restart systemd units, swappiness, drop caches |

**GPU tuning is deliberately left out.** Power limit, clock cap and persistence
mode used to be here and were removed: it is not process management. The helper
no longer knows those commands, so not via the command line either.

The GPU is still fully *measured* — including per-process VRAM and SM usage.
Just not adjusted.

## Architecture

```
archpm/sampler.py   psutil sampling; keeps Process objects between ticks
   ↑ gpu.py      two long-running nvidia-smi processes (stats + pmon)
   ↓
   ├─ ui/worker.py  QThread → signals → dashboard.py / procview.py
   └─ agent.py      → publisher.py → $XDG_RUNTIME_DIR/archpm/status.json
                                     ~/.cache/archpm/status.json (symlink)
                                        ↑ plasmoid reads here
```

The GUI and the agent sample independently of each other; you only need the
agent for the widget.

The widget reads that JSON through the `executable` data engine (`cat`), not
through `XMLHttpRequest`: Qt 6 blocks XHR on `file://` unless
`QML_XHR_ALLOW_FILE_READ` is set, and that is an environment variable for all of
plasmashell.

Root runs alongside the measurement chain, not through it:

```
archpm/ui/rootpanel.py ─ pkexec ─→ /usr/lib/archpm/archpm-helper   (root)
        │                            ↑ polkit: io.github.outing69.archpm.helper.run
        └─ ElevatedBackend ──────────┘   (only on AccessDenied)
```

## Useful commands

```bash
systemctl --user status archpm-agent        # is the agent running?
systemctl --user restart archpm-agent
python3 -m archpm.agent --once              # one sample to stdout
journalctl --user -u archpm-agent -f        # logs
kpackagetool6 -t Plasma/Applet -u plasmoid/package   # update the widget
/usr/local/lib/archpm/archpm-helper status           # test the helper (without root)
pkaction --action-id io.github.outing69.archpm.helper.run --verbose    # inspect the polkit rules
./install.sh --uninstall-root                        # remove the root part
```

After changing the widget: `kpackagetool6 ... -u` and then
`systemctl --user restart plasma-plasmashell` (or `kquitapp6 plasmashell &&
plasmashell &`) to reload it.
