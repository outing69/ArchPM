# Changelog

All notable changes, newest first. Versions are git tags on
[github.com/outing69/ArchPM](https://github.com/outing69/ArchPM).

## 0.2.9 (2026-09-15)

- Network: a program that holds sockets in more than one process, like a
  browser, shows one row per process between the program and its sockets,
  with the process name and pid and, while the row is closed, a summary of
  the ports it listens on and talks to. A program with a single such process
  looks as before. The filter also finds a process by name or pid.

## 0.2.8 (2026-09-15)

- The memory reads for the Grouped view are spread by process over four of
  every five sampling ticks, and the fifth tick reads the temperature sensors
  instead of sharing a tick with them. The slowest tick in twenty drops from
  about 125 ms to about 85 ms; before 0.2.7 it was 143 ms.

## 0.2.7 (2026-09-14)

- Fixed: with the agent service running, the window wrote status.json as
  well, every two seconds each, and the widget alternated between two
  producers with different content. The window now leaves the file to the
  agent while the service is active.
- The memory reads for the Grouped view are spread over the ticks instead of
  landing on one, so no sampling cycle is three times as long as the rest.
- The process list is not rebuilt while another page is on screen; it takes
  the newest sample the moment it comes back. One refresh of all pages drops
  from about 29 ms to about 4 ms per tick in that case.
- The NVIDIA per-process helper polls every 2 seconds, the sampling interval,
  instead of every second; it cost as much as the agent itself.

## 0.2.6 (2026-09-14)

- Fixed: the navigation rail had no background of its own, so the page showed
  through its icons and labels when it widened, and the collapsed strip took
  the window colour instead of its own. It now paints an opaque surface in
  both states and stays above the page.

## 0.2.5 (2026-09-14)

- The tabs across the top are replaced by a navigation rail on the left: a
  narrow strip of icons with a menu button on top. Hover it and it widens to
  icon and label over the page; the menu button pins it open, which is
  remembered. Tab reaches the rail, the arrow keys move along it and Enter
  selects; every item has a tooltip while collapsed and an accessible name.
  Icons come from your icon theme, each with a fallback name.

## 0.2.4 (2026-09-14)

- Processes: a Grouped view, now the default, next to Tree and Flat. One row
  per application, opened for its processes, with CPU, memory, threads, disk
  and GPU added up and the number of processes. Grouped by the systemd unit
  the desktop assigns at launch, then the program file, then the name; a
  browser that registers its main process in a scope of its own is folded
  back together with its helpers. Sorting orders the applications by their
  totals; a search finds a process and keeps its application row. Ending an
  application row asks first and names every process it reaches.
- Group memory counts shared pages once: the proportional share (PSS) of the
  processes in a group, read every ten seconds, so the figure can be up to ten
  seconds old. A process not measured yet counts its RSS and the tooltip says so.
- Hover tooltips in the process list wrap at about 600 pixels and cut a long
  command line short; the Command column keeps the whole thing.
- Help: "Swap and zram" is now "Swap in RAM", and zram is explained as a piece
  of RAM the kernel uses as compressed swap.

## 0.2.3 (2026-09-14)

- Per-process GPU usage on AMD and Intel: read from the kernel's DRM fdinfo
  (amdgpu, i915, xe), without root or an extra package. NVIDIA keeps
  `nvidia-smi pmon`, which fills in only what fdinfo cannot see; a process on
  both cards keeps both. The Intel path is written from the kernel
  documentation and has not run on Intel hardware yet.

## 0.2.2 (2026-09-14)

- Processes: searching in Tree mode opens every branch on the way to a match,
  so a matching child is no longer hidden under a collapsed parent. The
  ancestors are shown as context; clearing the search puts the tree back the
  way it was.
- Signals: a check before every Terminate, Force kill and Suspend. ArchPM
  itself, whatever started it and the leader of your login session are refused.
  A force kill, a process of another user, or a piece of the desktop itself
  (plasmashell, kwin, pipewire, wireplumber, the desktop portal) asks first,
  showing the program, who runs it and its command line, and naming what you
  would lose: sound, the panel, the window borders.
- Services: ArchPM manages only the services of your own login session, through
  `systemctl --user` and without a password. The root helper no longer knows
  about services at all, since a root process running `systemctl --user` would
  address root's own session, not yours. The panel refuses to stop plasmashell,
  pipewire, wireplumber and the desktop portal and says why; restarting them is
  allowed. System services are not managed.
- Polkit: the password prompt says in plain words what the helper can do and
  no longer mentions how long the authentication is kept; SECURITY.md explains
  that, and how to be asked every time, for a manual install and for the
  package. The project is English only; the Dutch texts are gone.
- Tests use invented data: no real home path or network address in the
  repository. .gitignore covers the runtime status file and build output.
- Hover over anything and it explains itself: every tile, graph, top list and
  column header has a one-line tooltip, and the Overview tiles add an "is this
  normal?" line with the ranges to expect at idle and in a game.
- Right-click a tile, graph or column header → "Explain … in Help" opens the
  Help tab on that term, highlighted.
- Processes: right-click a column header to tick columns on and off. Nice,
  User and Status start hidden; the choice is remembered.
- Help: the terms Category and User.
- Fixed: Top processes on the Overview showed "0%" for everything on an idle
  desktop. Shares of the whole machine now have one decimal below 10%, and the
  bars are relative to the busiest entry, like the memory and VRAM lists.

## 0.1.8 — 2026-09-13

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
