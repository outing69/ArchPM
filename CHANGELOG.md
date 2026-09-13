# Changelog

All notable changes, newest first. Versions are git tags on
[github.com/outing69/ArchPM](https://github.com/outing69/ArchPM).

## Unreleased

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
