# Glorified PM

Process management and monitoring for a Linux gaming PC. Three parts that share
the same measurement core:

| Component | What it is |
|---|---|
| **GUI** (`python3 -m gpm`) | PySide6 window with a dashboard and a full process list |
| **Agent** (`gpm-agent`) | systemd --user service that samples every 2 s and writes `status.json` |
| **Widget** | Plasma 6 plasmoid on your desktop that reads that `status.json` |

## Status and support

Built for and tested on one machine: CachyOS (Arch), KDE Plasma 6 on Wayland,
an AMD Ryzen 7800X3D and an NVIDIA RTX 5070. It will probably work on any Arch
derivative with Plasma 6 and an NVIDIA card. AMD and Intel GPUs use a sysfs
fallback that has only been exercised on the Ryzen's integrated Radeon. Other
desktops get the GUI but not the widget.

This is a personal tool that I am sharing in case it is useful to you. There
is **no support**: if it does not work on your PC, I probably cannot help. Bug
reports and patches are welcome, but there is no promise that I will act on
them. The license is MIT, so feel free to fork it and make it your own.

See `SECURITY.md` for what the root helper does and does not protect against.

## Installing

```bash
sudo pacman -S --needed pyside6 python-psutil
./install.sh          # agent, widget, menu entry  (no root needed)
./install.sh --root   # the pkexec helper and the polkit policy
```

Then: right-click your desktop → *Add Widgets* → **Glorified PM Monitor**.

## What it measures

- **CPU** — total, per logical core, frequency, load and Tctl temperature
- **GPU** — SM utilisation, VRAM, temperature, power draw and clock speed, plus
  **per-process GPU usage** via `nvidia-smi pmon` (works for games too, not
  just CUDA). AMD/Intel fall back to sysfs, without per-process data.
- **Processes** — CPU, RSS, threads, nice, disk I/O, VRAM, affinity
- **System** — network and disk throughput, swap, sensors

## What you can do with it

Right-click in the process list: terminate (SIGTERM), force kill (SIGKILL),
suspend/resume (SIGSTOP/SIGCONT), set nice, set disk priority, and choose CPU
affinity per process — with presets for "physical cores only" (no SMT
siblings) and each half.

## Permissions

The app runs as your own user. In that mode you can only control your own
processes and only raise nice. Everything that needs more sits behind a single
button: **Overview → Root tasks**.

That separation is the core of the design:

- `gpm/root/helper.py` is the **only** file that runs as root. It lives
  root-owned in `/usr/local/lib/gpm/gpm-helper` (pkexec refuses a program that
  a regular user can modify), imports nothing from this project and never
  starts a shell.
- `polkit/io.github.outing69.archpm.policy` decides who may authenticate. With
  `auth_admin_keep` polkit asks for your password once and remembers it for
  about five minutes.
- `gpm/root/client.py` only builds the `pkexec` call and reads the JSON reply.
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
gpm/sampler.py   psutil sampling; keeps Process objects between ticks
   ↑ gpu.py      two long-running nvidia-smi processes (stats + pmon)
   ↓
   ├─ ui/worker.py  QThread → signals → dashboard.py / procview.py
   └─ agent.py      → publisher.py → $XDG_RUNTIME_DIR/gpm/status.json
                                     ~/.cache/gpm/status.json (symlink)
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
gpm/ui/rootpanel.py ─ pkexec ─→ /usr/local/lib/gpm/gpm-helper   (root)
        │                            ↑ polkit: io.github.outing69.archpm.helper.run
        └─ ElevatedBackend ──────────┘   (only on AccessDenied)
```

## Useful commands

```bash
systemctl --user status gpm-agent        # is the agent running?
systemctl --user restart gpm-agent
python3 -m gpm.agent --once              # one sample to stdout
journalctl --user -u gpm-agent -f        # logs
kpackagetool6 -t Plasma/Applet -u plasmoid/package   # update the widget
/usr/local/lib/gpm/gpm-helper status                 # test the helper (without root)
pkaction --action-id io.github.outing69.archpm.helper.run --verbose    # inspect the polkit rules
./install.sh --uninstall-root                        # remove the root part
```

After changing the widget: `kpackagetool6 ... -u` and then
`systemctl --user restart plasma-plasmashell` (or `kquitapp6 plasmashell &&
plasmashell &`) to reload it.
