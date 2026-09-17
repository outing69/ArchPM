# Changelog

All notable changes, newest first. Versions are git tags on
[github.com/outing69/ArchPM](https://github.com/outing69/ArchPM).

## 0.2.31 (2026-09-17)

- Startup: the autostart entries stand in two groups, Enabled on top and
  Disabled under it, each with a header and its count in the process
  list's shape: the group's name in bold with the number of entries. The
  session's services underneath are read-only and stay as they were.
- A row that is switched off moves to Disabled at once, and the move is
  animated: the row lifts, travels to its place within what is on screen,
  the gap it leaves closes and the gap it goes to opens, and the row
  settles. When its place is below the viewport it slides out of view in
  that direction; the view is never scrolled. The Disabled header lights up
  briefly at the same time, so the eye finds where the row landed even
  when the row itself left the screen. One move at a time: a second switch
  while a row is still moving puts the first in its place at once. Back on
  moves the row to Enabled the same way. The confirmation for Desktop and
  System rows still comes first, and a row that is not confirmed does not
  move.

## 0.2.30 (2026-09-17)

- Startup: switching off an entry marked Desktop · keep on, or a System
  entry, asks first and names what you lose at the next login, in plain
  words: "the panel, the desktop and its widgets" for Plasma, "every
  password prompt for a root task, including ArchPM's own" for the
  PolicyKit agent, and so on. Not a password: the entry lives in your own
  autostart folder, which a text editor could change just as well, so a
  prompt would guard nothing. The wording comes from the one list of the
  session's pieces (session.py) where the entry runs one of them, and
  from a short line per entry where it does not; an entry ArchPM does not
  know gets what its menu entry says it does. Switching an entry back on
  asks nothing.
- Icons for a kind where an entry or a process has none of its own. On
  Startup a program with its own icon keeps it; the rest show the icon of
  their kind: App, System, Desktop · keep on, and a system entry with your
  own copy over it. In the process list a process without an icon shows
  the icon of the section it sits in: Apps, Background processes or
  System processes, whether or not the sections are shown. The names come
  from the icon theme, Adwaita's symbolic set tinted like the rail's icons
  when every name resolves, else Breeze's, the same all-or-nothing rule as
  the rail; no icon files are shipped.

## 0.2.29 (2026-09-17)

- Cleanup: a root row with nothing to remove says so. The two root rows
  read "asks for your password on Remove" while they could not be ticked,
  because the tick needs a size above zero and the note only looked at the
  root state; on a machine where every package is one of its last two
  versions and the journal is under the 100 MB kept, both sizes are zero.
  The note now reads "root · nothing to remove", in the quiet colour, and
  the same for a user item; the password line is shown only when there is
  something the password would remove.
- System: the "Refresh failed services" button sits on the group's title
  line, right after "Failed services", instead of at the far right under
  the page's Copy as text and Refresh, where it read as one more page
  button on a row of its own.
- A page's scrollbar no longer runs over the rows. The overlay scrollbar of
  0.2.27 told Qt every bar is transient, which lays it over the content,
  and its handle was painted over the box's edge. A page that scrolls as a
  whole (Overview, Startup, Cleanup, System) now has a bar of its own
  beside the page: a 14 px gutter with a thin track the bar's whole length
  and the handle centred on it, and it does not fade, since it has nothing
  to get out of the way of. A table's bar (Processes, Network, the
  Overview's top processes) is the overlay one still, over its own rows.

## 0.2.28 (2026-09-17)

- Stage three of the GNOME look, second part: boxed lists. Startup, Cleanup
  and System show their grouped information as rows in one rounded box with
  a line between them, a title and a subtitle per row and the group's note
  above the box, instead of tables and key-value grids. Startup: one row per
  autostart entry with its status, its kind and source and a switch, on in
  the selection blue as a ticked box is; the session's services underneath
  in a group of their own. Cleanup: one row per item with a check box, the
  reason, the note and the size, and a click anywhere on the row ticks it.
  System: the failed services as rows under the group's head, with the
  Refresh button at the head's right, and the specs as property rows, the
  name small over the value in full, wrapping and selectable, in two
  columns when the window is wide enough for them and one when it is not.
  Each of the three pages scrolls as a whole. When a row is narrow the kind
  and source on Startup go first and the name keeps its room; the window's
  minimum width is still the Overview's. The Processes and Network tables
  are untouched, since data views stay dense; the navigation rail and the
  yellow accent are as they were.
- The toast at start that named the status file's path is gone. It was the
  only message that came without the user doing anything, and the path is
  developer information. It is on the System page instead, in the ArchPM
  group as the row "Status file", and in Copy as text.

## 0.2.27 (2026-09-16)

- Stage three of the GNOME look, first part: the header bar, the controls
  and the window width. The status bar is gone. A header bar above the
  pages, to the right of the navigation rail, carries the page's name as its
  title, centred, and the Theme and Interval controls on the right, flat
  until hovered; the desktop's own title bar stays above it and no window
  buttons are drawn. Of what the status bar showed, the process count and
  the GPU note are on the Overview already and the render time is dropped.
- The transient messages are a toast: one line over the content, bottom
  centre, that fades in and goes by itself; a click dismisses it, a new
  message replaces it. The texts and times are as before: 4 s for the
  results of Terminate, Force kill and the other actions, for Startup
  switches, "System information copied to the clipboard", "Freed …",
  root on and off and the signal guard's refusal; 6 s for the status file's
  path at start; 10 s for the sampler's notice that it is not publishing.
- Focus is a 2 px ring in a second blue, FOCUS, which is not the selection
  blue, wherever focus is drawn: fields, drop-downs, buttons, check boxes,
  sliders and the failed-services link. The yellow focus border is gone;
  yellow highlights, blue selects, and the ring marks where a key press
  goes. Help's colour legend says so.
- Overlay scrollbars: a thin handle over the content's edge, no track and no
  arrows, drawn by a proxy style so it is the same on Breeze and Fusion,
  fading when nothing moves and back on a wheel turn, a scroll or the
  pointer. A scrollbar no longer takes a column of its own.
- The window can be made narrow. The minimum width was 1163 px, set by the
  Processes toolbar and the Help page's head, each on one row; it is 472 px
  now, set by the Overview's tiles at three across. Toolbars and page heads
  wrap to a second row when the window is narrow, the Overview's six tiles
  become two rows of three and its four cards one column, the Network cards
  stand one under the other, and an address or a rate elides instead of
  holding the window open. A table scrolls sideways; no page does.

## 0.2.26 (2026-09-16)

- Cleanup: no password at page entry. The sizes are read without root
  (your caches by listing them, the package cache with paccache's dry run,
  the journal with journalctl --disk-usage); only removing the package cache
  and the system logs goes through the root helper. The page said neither and
  asked for the password the moment you entered, with the sizes already on
  screen, as if for nothing. Now the page and the first-visit note say which
  is which, the two root rows read "asks for your password on Remove", they
  can be ticked as soon as the helper is installed, and the prompt comes when
  you press Remove selected with one of them ticked.
- Overview scrolling was verified at window heights where the content does
  not fit, offscreen with spontaneous wheel events over every child and by
  hand on a 700 px window: the scroll area receives the wheel and the page
  is set to resize. On a screen where the maximised window fits the whole
  Overview there is nothing to scroll, and at a 1000 px window the range is
  only a few dozen pixels, so one notch moves little; both are the whole
  overflow, not a fault.

## 0.2.25 (2026-09-16)

- Stage two of the GNOME look: shape, spacing and type, in Adwaita's
  proportions, as tokens in archpm/ui/theme.py next to the colours. Corners
  are rounder: 12 px on cards, tables, menus and group boxes, 9 px on
  buttons, fields and tooltips. More air: 18 px page margins and card
  padding, 12 px between cards. One type scale for the whole window: title
  12 pt, body 10 pt, small 8.5 pt, in the system's own font (never a named
  family), so a size is no longer set per page. Buttons and fields are 34 px
  high with 16 px of horizontal padding, as in Adwaita. Data tables stay
  dense: the row height is 26 px and the process list's cell padding is
  unchanged, since a process list is a data view. The colour tokens are
  untouched. The air made the Overview 41 px taller than before, which
  would have pushed the window's minimum height past a 1080p screen with a
  panel; the Overview now scrolls when the window is shorter than its
  content, so the window's minimum height no longer depends on it.

## 0.2.24 (2026-09-16)

- Light mode, stage one of the GNOME look: colours only, no shape, spacing or
  font changed. Every colour is a token with a dark and a light value, and no
  hex value lives outside archpm/ui/theme.py. The light values are chosen per
  token, not inverted: yellow becomes amber, the pastel series colours become
  their stronger cousins, and every text tone is checked against the light
  surface. The mode follows the system by default, from Qt's colour scheme
  where the platform reports it, else the desktop portal over D-Bus, else
  dark; a Theme setting at the bottom of the window offers Follow system,
  Light and Dark, applied at once.
- The navigation rail uses the Adwaita symbolic icons when adwaita-icon-theme
  is installed and all eight names resolve, tinted to the text colour; else the
  whole rail stays on Breeze. Breeze's light and dark icon sets are matched to
  the mode. adwaita-icon-theme is an optional dependency of the package; no
  icon file ships with ArchPM.

## 0.2.23 (2026-09-16)

- Overview: "N services failed" now reads as the link it is: pointer cursor,
  underline on hover, reachable with Tab, a focus outline, and Enter or
  Space opens the System page. "No failed services" stays plain text that
  takes no focus, not a button.
- System page: the button on the failed-services block is "Refresh failed
  services", so it no longer sits next to the page's own Refresh with the
  same label and a different effect.

## 0.2.22 (2026-09-16)

- Failed services, read-only. Once, when the window starts, ArchPM asks
  systemctl --failed and systemctl --user --failed. The Overview says "No
  failed services" in muted text next to Root tasks, or "N services failed"
  as a link to the System page, which has a block above its cards with one
  row per failed unit: the program in plain words, the unit name in smaller
  text, whether it is a service of your session or of the system, when it
  failed, and the last eight lines of its log from journalctl. If the system
  log is not readable for this user the row says so. Refresh on that block is
  the only other time the check runs; it is not on the sampling cycle and not
  on a timer. With no failures the two calls take about 5 ms together; each
  failed unit adds about 20 ms for its details and log. ArchPM still starts
  or stops no system service.

## 0.2.21 (2026-09-16)

- Processes: with "Show all processes" on, the Grouped and Flat views are
  split into three sections with a count in each header: Apps (everything in
  an app-… unit of your session, which is how Plasma files what you launch),
  Background processes (the rest of your session) and System processes
  (everything under system.slice, and the kernel's own threads). The cgroup
  the sampler already reads decides; only when it could not be read does the
  owner decide, a uid below UID_MIN being the system's. Section headers open
  and close, a closed one stays closed next time, they keep their order under
  any sort, an empty one is hidden, and they cannot be selected. Tree keeps
  its parent hierarchy. With the box off the list is exactly as before. These
  are not the Category column, which says what a program is for.
- Fixed: the cgroup line was cut at its last colon, and a dbus-activated
  unit carries a colon in its name (dbus-:1.2-org.kde.kwalletd6@0.service),
  so kwalletd6, kdeconnectd and the accessibility registry had a broken
  cgroup path: the Grouped view could not name their unit, and the root
  helper's unit check could not see it either. Both now split at the second
  colon.

## 0.2.20 (2026-09-16)

- A process that its service starts again after a kill (Restart=always,
  on-failure and the like) is now named as such in the Terminate and Force
  kill question, with the unit, and with where to stop the service instead:
  Root tasks for a service of your session, a restart hint for a piece of
  the desktop, sudo systemctl stop for a system service. Where no question
  would have been asked, one is now, since ending it would change nothing for
  long. The setting is read from systemctl only when the question is about to
  open, one call per service unit among the targets, 4 ms each; nothing is
  read on the sampling cycle. Helpers of a service, whose end the service does
  not notice, get no such note. Help: "Service that comes back".

## 0.2.19 (2026-09-16)

- Honesty, four places. The Drop caches tooltip now says what the Help page
  said all along: the memory only looks free, the kernel would have freed it
  itself, and the system is slower for a moment afterwards. The swappiness
  tooltip says the value lasts until the next restart. The journal cleanup
  says before the action, in the row and in the confirmation, that logs older
  than the newest 100 MB go for good, including those of an earlier crash
  you might still want to look up. And the Startup tab lists the services of
  your session that systemd starts at login, read-only, under the autostart
  entries, so the page no longer looks complete while it is not.
- Help: Service (and the difference between a service of your session and one
  of the system), Unit, Enabled service and Log (journal).

## 0.2.18 (2026-09-16)

- The desktop session's pieces live in one list, archpm/session.py, read by
  both the signal guard (by process name) and the service guard (by unit
  name). The two lists had drifted: the service guard did not know
  plasma-kwin_wayland, plasma-ksmserver or dbus-broker, so Stop on them went
  through without a word, while the signal guard knew kwin. Both now know
  plasmashell, kwin, ksmserver, the session bus, pipewire, wireplumber and
  the desktop portal; a dbus-activated program's unit (dbus-:1.2-…@0.service)
  is that program, not the bus, and may be stopped.
- install.sh no longer dies when kpackagetool6 is missing. It used to stop
  with exit 127 at the widget step, so the menu entry and the desktop
  shortcut were never written, and with --all the root part was skipped too.
  As the README says, other desktops get the GUI but not the widgets: the
  widgets are skipped with a line saying so, and the rest goes on. The same
  for --uninstall.

## 0.2.17 (2026-09-16)

- Tests: the PSS cadence test no longer depends on what happens to be running.
  It needed a steady application with several processes and failed in a clean
  build chroot, which made the package's check() fail. It now starts a few
  sleep children of its own, which form a group, and checks the cadence on
  those. Two helper tests had the same flaw: they took pid 2 (kthreadd) as a
  root process that exists everywhere, and a chroot with its own pid
  namespace has none. They now make the helper see the test's own process
  as root's, or nobody's, and the kthreadd check runs only where pid 2 is
  really root's. Verified in an empty pid namespace and in a clean
  container build of the package.

## 0.2.16 (2026-09-16)

- Fixed: Priority, Disk priority and CPU affinity on a group row (a browser
  and its helpers, say) did nothing and said nothing. The row carries a
  negative pid that no kernel call can take; psutil raised a ValueError that
  nothing caught, and Qt dropped it on stderr. The view now expands a group
  row into the processes shown under it, so "Low" on Brave goes to every
  Brave process, and the status bar counts them. And whatever goes wrong
  inside an action is shown in the failure box, never swallowed; with nothing
  selected the status bar says so.
- Root tasks: the service list shows the unit's description before its name,
  "Brave - Web Browser  (app-brave\x2dbrowser@8918….service)", sorted by that
  description, so the opaque names Plasma gives launched apps can be told
  apart. A typed unit name still works.

## 0.2.15 (2026-09-16)

- Security (root helper): nice, affinity and IO class now get the target
  check that signals had. Before, they only checked that the pid existed and
  was above 1, so with root a user could renice journald or the display
  manager, pin it to one core or give it realtime IO. All four process
  commands now refuse anything but a regular user's process outside the
  protected units, and pin the target with a pidfd: a signal goes through the
  pidfd, and for the other three the helper checks afterwards that the pinned
  process is still alive, so a pid recycled mid-call is reported instead of
  changed in silence.
- Security (root helper): a regular user is now what /etc/login.defs says,
  UID_MIN to UID_MAX (1000 to 60000), instead of "above 999". That closes
  nobody (65534) and systemd's DynamicUser accounts (61184 to 65519), which
  were treated as regular users.
- Security (window): the elevated backend retries only a refusal for lack of
  privileges through the helper. Every other refusal from the user backend,
  ArchPM's own process or a process that is gone for instance, is final and
  no longer comes back as a root action.

## 0.2.14 (2026-09-16)

- Security: the widgets no longer run anything that comes out of status.json.
  Before, the file carried a `launch` command line that "Open ArchPM" ran
  through the shell, and the game's pids that "End game" passed to `kill`,
  past every check in signalguard.py. Anything that could write the file as
  you could run a command inside plasmashell. Now "Open ArchPM" uses a command
  fixed when the widget is installed, and "End game" hands the request to the
  window (`archpm --end-game`, or the instance socket when it is open), which
  asks, runs the signal guard and sends, as from its own button. One click in
  the widget; the window's dialog is the confirmation. The `launch` field and
  the game's `pids` are gone from the file.
- Security: the agent no longer falls back to /tmp/archpm when there is no
  $XDG_RUNTIME_DIR; another user could create that directory first and replace
  the file. Without a runtime directory the file goes into ~/.cache/archpm,
  which is the user's own. Every write opens the directory and checks it on
  the descriptor (a real directory, ours, not writable by others) before
  writing through it, so nothing can be swapped in between. When the check
  fails the agent says why and exits with status 3, which the unit no longer
  restarts; the window says why in its status bar and stops publishing.
- An old widget with the new agent shows no "Open ArchPM" and an "End game"
  that does nothing; reinstalling the widgets brings both back. SECURITY.md
  describes the status file and the widgets.

## 0.2.13 (2026-09-15)

- install.sh --uninstall removes everything the script installed: the root
  helper and the polkit policy, the user unit, both widgets, the menu entry
  and the desktop shortcut. Settings and the cache stay. The README says to
  run it before installing the package, because pacman refuses to overwrite
  the policy file it does not own.
- install.sh renders the polkit policy into a mktemp file instead of
  .policy.tmp inside the checkout, and removes it on exit, also when a step
  fails.

## 0.2.12 (2026-09-15)

- Startup: the hint names the autostart folder as ~/.config/autostart
  instead of the full path under your home folder, so a screenshot or a
  pasted line does not carry your username.
- README: full-page screenshots of every page, the Help page included.

## 0.2.11 (2026-09-15)

- The navigation rail slides between its two widths with an eased 160 ms
  animation instead of jumping. The page beneath it is no longer repainted
  while it expands, and the window layout is not run for every frame.

## 0.2.10 (2026-09-15)

- Network: process rows are closed by default and open only by hand. The
  filter opened them along with the programs, and they stayed open after the
  filter was cleared. Programs and hand-opened rows behave as before.

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
