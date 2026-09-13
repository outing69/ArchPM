# Changelog

All notable changes, newest first. Versions are git tags on
[github.com/outing69/ArchPM](https://github.com/outing69/ArchPM).

## Unreleased

- New **Network** tab, between Processes and Startup: your interfaces with
  speed, address and a VPN mark; an "open doors" card naming the programs
  other devices on your network can reach; and every program with connections,
  its TCP download and upload, and each remote address with the service name
  (https, ssh, Steam). Filter by program, address or port. Refreshes every five
  seconds from one `ss` call; no root, no lookups on the internet.
- New Plasma widget **ArchPM Network**: "↓ 1.2 MB/s ↑ 88 KB/s VPN" in the panel,
  and a popup with interfaces, the programs using the most bandwidth and the
  open doors. The ArchPM Monitor widget is unchanged.
- The agent's status file carries a `net` section for the widget.
- Help explains connection, port, open door, TCP versus UDP and VPN interfaces.

## 0.1.7 — 2026-09-13

- Plasma's task manager and tooltips show "ArchPM" instead of "python3": the
  install script rebuilds Plasma's service cache after installing the menu entry.
- End the detected game from the tray icon's menu or from the widget's popup
  (second click within five seconds confirms), without opening the app.
- The widget says GB and MB like the app.
- Overview reads in plain words: Download/Upload, GPU load, Disk read/write,
  Processor for the CPU temperature, "58% of 15 G"; labels start with a capital.
  Help explains each of them. The CPU tile names the processor ("7800X3D"),
  the temperature tile has no subtitle, and sizes say GB and MB everywhere.
- Tray icon menu: "Always keep on foreground" (off by default) keeps the window
  above everything, to watch a measurement while something else has the screen.
- Overview: a red "End game" button on the game card asks the detected game and
  its whole process tree to quit, after a confirmation.
- Sampling costs less than half of what it did: sensors are read every fifth
  tick, command lines and user names are cached. The agent is back to about 1%
  of one core.
- Startup: "running" detection works for programs whose path contains a space.
- Closing the window while a Cleanup scan or System gather is still running no
  longer risks a crash.

## 0.1.6 — 2026-09-13

- Widget in the panel: a strip in the app's colours (CPU, GPU, RAM), the game's
  name in front when one runs, red above 85 °C; percentages, temperatures or
  both as a setting. The popup shows the game and has "Open ArchPM".
- Tray icon menu: the running game, Root tasks, and "Keep running in background
  when closing" (off by default).
- Help tab: a searchable glossary in plain language, what the colours mean, and
  About with version, links and this changelog.
- Game card tiles of equal width; card titles in the colour of their data.

## 0.1.5 — 2026-09-13

- New Cleanup tab: per-program caches, Steam shader caches per game across all
  libraries, thumbnails, old package versions (the last two of each are kept)
  and archived logs beyond 100 MB, each with its size and a plain reason.
  Explains itself on first open and asks for the password once; nothing is
  removed until ticked, pressed and confirmed. Marks caches of programs running
  right now. Rescans after removing.
- Root helper: two fixed cleanup commands that accept no arguments.
- README: install lines per package manager and an Updating section.

## 0.1.4 — 2026-09-13

- Game card on the Overview: the running game's whole tree (CPU as a share of
  the machine, GPU, VRAM, RAM, threads, cores allowed), how long it runs, and a
  graph of its last minutes.
- History per process: select a row and its last minutes of CPU, GPU and memory
  appear under the list; a collapsed program shows its whole tree. The panel
  stays on a killed process until you pick another.
- Steam games hang directly under Steam and Steam opens when one starts; the
  game tree's root carries the game's name.
- Widget: core strip colours fixed; friendly names in its top list.

## 0.1.3 — 2026-09-13

- Processes: programs first. The default view shows your own programs plus
  anything actually busy; "Show all processes" shows everything. A collapsed
  program row carries the totals of its whole tree.
- Category column and filter; Started column.
- New Startup tab: what starts at login, with a switch per entry, plain
  descriptions, and a keep-on warning for parts of the desktop.
- New System tab: the machine's specs on one card, with Copy as text.
- Always opens on Overview.

## 0.1.2 — 2026-09-13

- Process tree by parent pid, collapsed by default below init and the user
  session; sorted by name by default, the chosen sort is remembered.
- "Terminate with children" takes a whole process tree down.
- Real names and icons from menu entries and Steam; wrapper scripts named after
  their script. No fallback icons.
- README: AI-transparency note.

## 0.1.1 — 2026-09-13

- One GUI instance per user; a second launch raises the existing window.
- Closing the window quits; no more lingering tray icons.
- Root helper hardened after an adversarial review: signals only reach regular
  users' processes, no .target units or shutdown services, protected units
  matched by every alias and by what a socket triggers.
- Core strip capped at 64 bars; AMD via sysfs gets a real card name and power.
- Packaging: pyproject.toml, console scripts, PKGBUILD.

## 0.1.0 — 2026-09-13

- First public release: PySide6 GUI, systemd --user sampler agent and a Plasma 6
  widget, with a pkexec/polkit root helper for privileged actions.
