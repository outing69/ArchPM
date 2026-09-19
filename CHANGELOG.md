# Changelog

All notable changes, newest first. Versions are git tags on
[github.com/outing69/ArchPM](https://github.com/outing69/ArchPM).

## 0.2.51 (2026-09-19)

- Changing the sampling interval in the header stopped sampling for the
  rest of the session. The combo handed the change to the worker's
  `set_interval` on the GUI thread, and the QTimer behind it was made on
  the worker thread; Qt refuses to start or stop a timer from another
  thread, drops the call with a warning and leaves the timer stopped, so
  after one change no sample arrived again. The saved setting applied on
  the next launch, which hid it. The change now travels as a queued signal
  and runs on the worker thread; the stop at shutdown had the same shape
  and goes the same way. A test drives the worker from the main thread
  and counts what arrives: a change to 50 ms is followed by samples at
  that rate, a stop by none, and neither prints the warning.
- Closing the window while the Snapshots page read its list, or the
  Network page its firewall, could abort the process: shutdown waited for
  the Cleanup and System threads by name and knew nothing of the other
  two, and a QThread destroyed while running takes the process down. The
  window now joins every thread it finds under itself in the object tree.
  Every page thread is a child of its page, so a page added later is
  covered the moment its thread has a parent, with no list to keep.
- `install.sh --uninstall` removed the package's polkit policy. The AUR
  package installs its policy at the same path as install.sh but its
  helper under /usr/lib, so a package user running the checkout's
  uninstall lost the policy and every root task then failed with "polkit
  policy not installed". `uninstall_root` now has the guard `install_root`
  already had: with the package's helper present the root part is the
  package's and stays, and only a helper left in /usr/local by an earlier
  `install.sh --root` is removed. Both installs are now tested against
  both uninstalls in a bubblewrap sandbox (a throwaway /usr/local, polkit
  directory and /usr/lib overlay, uid 0 in a user namespace, a sudo that
  runs its command); the tests skip where bubblewrap is missing.

## 0.2.50 (2026-09-18)

- The Startup page's description was reported cut on the right once the
  gutter bar appeared (0.2.49's notes). It is not: the pointer of an
  offscreen grab sits at the window's origin, which hovers the rail open
  over the page's first 200 px, and the description's short fourth line
  sat under it. Measured with the pointer away, on every page at 700, 400
  and 287 px: each wrapped label spans exactly its viewport, gutter bar or
  not, and none is squeezed below its text. No page had the fault, so no
  page changed; a test in the chrome suite now walks every page at the
  window's floor and checks both.
- CI had been red on every push since 17 September, and the lint job with
  it, so the checks were not the guard they were taken for. The test jobs
  failed because five test modules imported Qt, or the theme that imports
  Qt, outside the "PySide6 not installed" guard: the theme, boxed list and
  chrome suites failed to import at all, and the Adwaita set and two of
  the words tests errored. They are guarded like the rest; without PySide6
  the suite passes with those skipped, which is CI's shape, and with it
  nothing is skipped that was not before. The lint job failed on eighteen
  findings, all style: fourteen lines over 100 characters (test fixtures,
  a path, a comment in the rail's icon table), three unused imports, two
  unsorted import blocks, one ambiguous name (`l` in the helper's
  Timeshift parser, now `line` with the pattern named), and one pair of
  comparisons to merge. None was a defect. The lint run is clean.

## 0.2.49 (2026-09-18)

- No page clips its content in a short window any more: a page that does
  not fit scrolls, the way the Overview has since 0.2.25, with the bar in
  a gutter beside the content (0.2.29). Measured at the default width with
  the window shrunk in steps: the Network page was the one that clipped,
  from 400 px with two firewall doors (its cards' wrapped sentences were
  squeezed to two thirds of their height, since a wrapped label's minimum
  understates it); the Processes page clipped only with the history panel
  open, as the panel's 190 px and the toolbar then did not fit; Startup,
  System, Cleanup, Snapshots and Help never clipped, since each scrolls
  its body under a head of its own. Processes and Network are scroll
  areas now, like the Overview; the tree keeps the room the window gives
  it and stops shrinking at its own hint when the page starts to scroll.
  The other pages are as they were.
- The window's minimum height was 373 px, set by the Network page's cards
  under the 47 px header bar; it is 287 px, set by the Cleanup page's
  head, its scrolling note and its log box. At that height every page
  shows its head and the start of its content and scrolls for the rest.
- Navigating to a page by its view (the Overview's failed services line,
  a process from a widget, Explain in Help) works for a page that scrolls:
  the shell finds the page a view sits in.
- The Help glossary's "Where" lines and sentences said "Processes tab",
  "Network tab", "Startup tab", "Cleanup tab" and "System tab"; the
  navigation has been a rail of pages since 0.2.5, so they say "page"
  now, and the yellow's explanation names the current page on the rail
  instead of the active tab. A browser's tabs keep their name.

## 0.2.48 (2026-09-18)

- The firewall block's doors are rows, one per door, the way a socket is
  a row under a program in the same tab: the port and protocol, the
  service's name, and the interface or source where there is one, in
  monospace and indented under their count ("53/udp · domain · on virbr0",
  "80/tcp · http · from 192.168.1.0/24", "22/tcp · ssh · rate-limited", a
  profile by its name, a rule for everything as "everything"). Before,
  the doors were one line separated by commas, which ran off past a few,
  and above six the names were dropped for a count. The two summary lines
  above stay as they were.
- More than six doors fold behind their count: the third line is then a
  link, "10 doors open to other machines ▸", closed by default so the
  block stays three lines, and it opens to the full list on a click; a
  Refresh keeps it open. Six or fewer show their rows at once under the
  plain count. A row is never squeezed below its line; a window too short
  for the card clips the wrapped sentences, as it did before.

## 0.2.47 (2026-09-18)

- The firewall block under Open doors, tidied; nothing new in it. The
  Refresh link was a label as wide as the card, and with focus the 2 px
  ring ran around that whole width, so it read as an input field. It is a
  link of its own width now, on the "Firewall" line right after the label,
  the place the failed services block gives its control, and the ring hugs
  the words while the link has focus, nowhere else. The block is set apart
  from the doors' sentence by a hairline in the border colour, the line a
  boxed list draws between its rows, so the two no longer run together as
  one paragraph. The label "Firewall" stands on a line of its own above the
  three lines instead of in front of the first sentence, so the three read
  as one set.

## 0.2.46 (2026-09-18)

- The Network page's Open doors card ends with the firewall's state,
  read-only. The doors say which programs accept connections; whether those
  doors are reachable from outside depends on the firewall, so the two
  answer one question together and the firewall gets no page of its own.
  Three lines at most: whether a firewall runs and which (ufw or
  firewalld); what it does with incoming traffic no rule covers, in plain
  words ("dropped without a reply", "refused, and the sender is told", "let
  in unless a rule blocks it") instead of the tool's deny/reject/allow or a
  zone target; and how many doors it opens to other machines, named while
  there are six or fewer ("2 doors open to other machines: 53/udp (domain)
  on virbr0, 67/udp (bootps) on virbr0"), the IPv6 twins folded into their
  IPv4 lines, a comment dropped, a rate-limited rule marked, a rule bound
  to one interface or one source said so. The tool's own status output is
  what is read (`ufw status verbose`, `firewall-cmd --state`,
  `--get-default-zone`, `--list-all`); the raw nftables ruleset is shown to
  nobody. A machine with only nftables.service or iptables.service gets
  one line: it runs, its rules are not summarised here. A machine with no
  firewall at all gets one line too, without advice: that is a choice, and
  CachyOS ships without one.
- Read when the page opens and on the block's own Refresh, never on the
  sampling cycle (the failed services check's pattern). The plain read is
  detection (the binaries, `systemctl is-active` on five units, ufw's
  world-readable ENABLED flag) plus the tool's status where it answers a
  plain user: firewalld does over D-Bus; ufw refuses outright, so it is
  not even asked. On this machine the plain read costs 8 ms, off the UI
  thread. Where the plain read is refused, the block reads through the
  root helper on request, the Snapshots page's route: "Read the firewall"
  asks for the password once, the next few minutes need none, and Refresh
  then reads the same way. Without the root helper the block says the
  state needs it, the Cleanup root rows' pattern. Each read's cost is in
  the Refresh link's tooltip.
- The helper gains one subcommand, `firewall-status`: fixed argv, nothing
  from the caller, read-only, `ufw status verbose` or firewalld's three
  reads. It never runs `nft` or `iptables`. The polkit message names the
  read. The helper has to be reinstalled (`./install.sh --root`, or the
  package) before the block can read as root; until then the helper
  refuses the unknown subcommand and the block shows that refusal.
- ArchPM changes no firewall rule and switches no firewall on or off. No
  page, no button that changes anything, no switch.

## 0.2.45 (2026-09-18)

- Fixed: the Monitor widget's full view cut at the bottom, a row of the
  top processes list half visible and the footer at or past the edge. The
  height is the user's: the widget declares a minimum of 16 grid units
  (288 px with the default font) and a preferred 20, which the popup from
  a panel takes and a desktop widget starts at, and it can be dragged
  taller without limit. The list has no count of its own; it shows every
  process the agent sends, five. The content is a column: a fixed part
  (header, game, four meters, the core strip, the footer) and the list,
  with a spacer that takes whatever is left when the widget is tall. Made
  shorter, the spacer reaches zero and the column does not shrink further:
  it runs past the bottom, the lower rows and the footer with it. Rendered
  at 288 px: two rows and the footer below the edge, the footer's bottom at
  347 px.
- Now the list gives way. The rows sit in a list that asks the column for
  what its rows need and takes no more, gives way first when the widget is
  short, and shows only the rows that fit whole in the height it gets, in
  order, the rest not at all: never a half row. The footer keeps its
  place. At 288 px one process shows, at the preferred 360 four, from 400
  all five; "TOP PROCESSES" goes with the last row.
- The Network widget had the same shape and the same fault: at its
  minimum height its footer was already past the edge, and with six
  programs and four open doors the doors and the footer were. Its two
  lists, the programs using the network and the open doors, are the same
  kind of list now: at 324 px with that load three programs and two doors
  show, and the footer; taller, more. The interfaces and the sentences stay
  as they are. Neither compact form is touched.

## 0.2.44 (2026-09-18)

- The Monitor widget's panel form is three meters instead of a line of
  text. Before, it drew "CPU 1%", "GPU 0%" and "RAM 43%" in monospace in
  ArchPM's blue, violet and orange (the red of its own palette above 85°),
  the game's name in front by its setting, and a dot when the agent was
  down, at the width of the text: 143 px at those values and 175 px at
  100% everywhere, on a 34 px panel with the default fonts. Now each meter
  is the icon theme's icon for the part, drawn as a mask in the theme's
  text colour, a thin vertical bar of 3 px the height of the text, and the
  number in a cell reserved for its widest form ("100%"; "100°" or
  "100% 100°" by the panel setting), so nothing moves with a value. The
  strip is 186 px at any value; the game's name, when shown, adds its own
  width up to 12 grid units. The icon names are "cpu", "video-display" and
  "memory", each with a fallback from the freedesktop set that Breeze,
  Adwaita and the legacy Adwaita all ship, "computer",
  "preferences-desktop-display" and "media-flash"; when a theme lacks both,
  Kirigami paints its placeholder, so a slot is never blank.
- The bar fills with the theme's highlight colour and turns to the theme's
  negative colour where the application itself calls the part busy or
  full: 85% for the processor, the graphics card and the memory, the
  window's own MACHINE_BUSY, GAME_GPU_FULL and MEM_FULL_PCT; a temperature,
  when the setting shows one, turns negative at the window's HOT_C, 90°,
  where the strip used to say hot at 85°. A test holds the four numbers in
  the QML to the ones in archpm/verdict.py. No data dims the strip.
- In a vertical panel each meter stacks: the icon over the number over a
  thin horizontal bar the width of the column, at 44 px and at 34 px,
  where the number is fitted to the column; nothing is dropped. The
  Network strip is as 0.2.42 left it, 188 px, its arrows being the glyphs;
  its vertical form and its tooltip in words stand. The Monitor's tooltip
  now speaks in words too: "Processor 12% at 45°, graphics card 3% at 54°,
  memory 43% (6.4 GB of 14.7 GB)", and the game's name. Neither full view
  is touched, and no colour of ArchPM's own is in either strip.

## 0.2.43 (2026-09-18)

- Fixed: text cut off at the right edge of the Network widget's full view.
  The widget has no fixed width: on the desktop it is resized by hand down
  to 14 grid units (252 px with the default font) and opens from a panel at
  16; the content is a column that fills that width, and a row's leftovers
  were to elide. But three rows held text that can neither shrink nor wrap,
  the two rates of an interface or a program (monospace, never elided) and
  the port list of an open door, next to text that could: the layout gave
  the shrinkable part nothing, so the address elided to "192.168.17…", and
  when the fixed parts alone were wider than the widget the whole column
  grew past the edge, which is why "Reachable from other devices on your
  network:" no longer wrapped and stood against the edge, cut. Rendered in
  a harness: at 252 px with two open doors the column overflowed by 11 px.
- Now the content follows the width: an interface is a Flow, so its name,
  address and rates go on to the next line when the widget is narrow and
  the address is never cut; a door's port list wraps like a sentence and
  its name elides only when it alone is wider than the widget; a program's
  name elides, with the full name in a tooltip while it is elided; the
  sentences wrap as before. No row is wider than the widget any more, so
  the sentences wrap inside it again.
- The Monitor widget's top processes list does not cut: the name elides and
  the percentage is short. Its game line did, at the widget's minimum width
  ("GPU 97% · 3.2 cores · VRAM 6.6 GB · 12 proc" by 38 px at 13 grid units,
  2 px at the preferred 15); it now wraps, and the game's title and the top
  processes' names carry the tooltip. Neither compact form is touched.

## 0.2.42 (2026-09-18)

- The Network widget's panel form is one line: download and upload, an
  arrow and a rate each, nothing else; a click opens the full view, which is
  unchanged. The widget had a compact form since it was made, but that one
  put "VPN" and the busiest program's name on the line (two settings, now
  gone with their settings page), coloured the rates in ArchPM's own blue
  and teal, and took its width from the text, so the strip grew and shrank
  with every value. Now each rate has the width of the widest form the
  number takes ("↓ 1023.9 MB/s") reserved, in the theme's small monospace
  font and the theme's text colour, and the strip keeps one width while the
  numbers change every two seconds; no data dims the line instead of adding
  a dot. Rendered with the default fonts (Noto Sans Mono, 8 pt, 96 dpi):
  the strip is 188 px wide and its text 15 px high, the same at a 44 px and
  at a 32 px panel, since the font does not follow the panel's height; at
  32 px it keeps 8 px above and below.
- A vertical panel is a column of the panel's thickness, 34 to 48 px, where
  that line cannot fit: there the two rates stack, in a short form without
  spaces or "/s", the next unit from 1000 and a decimal only under 10
  ("↓1.2M" over "↑88K", five characters at most), at a font size fitted
  once to the column for that form's widest case ("↓999M", 33 px at 8 pt),
  so neither the width nor the size moves with the value. At 44 px the
  small font fits as it is; at 34 px it drops to about 6 pt. The tooltip
  says both rates in full, in every panel.
- A widget already on the desktop or in a panel gets the new form after
  the update without being added again: `./install.sh` (or the package)
  replaces the widget's files, and plasmashell reads them at its next start,
  `systemctl --user restart plasma-plasmashell`. The Monitor widget is
  untouched.

## 0.2.41 (2026-09-18)

- Fixed: "Read snapshots" showed nothing. The button and Refresh share one
  read, which went to the root helper only after a list had already been
  read as root; on a machine where Snapper refuses the plain read (its
  config names no one in ALLOW_USERS) the first click repeated that refused
  plain read, so the helper was never called, no error existed to show, and
  the page stayed empty. Reproduced offscreen: the click started the plain
  read thread and made no helper call. The read now goes through the helper
  as soon as the plain read has been refused, the route the reread after
  taking or deleting already took.
- The same silent gap the 0.2.16 audit found in the process list: the
  helper's reply was handled with only the helper's own refusal caught, so
  any other exception between the reply and the list (a reply in a shape
  the parser does not expect, a fault of our own building the rows) left
  the slot to Qt, which drops it on stderr, and the page just stayed empty.
  Now every outcome is shown, the process list's rule: a fault in reading
  goes on the state line as "Not read: ValueError: …" with the list as it
  was, a fault in building the rows as "Not shown: …", a fault after taking
  or deleting to the status bar as "Not done: …", and the plain read thread
  hands a fault to the page as the listing's error instead of dying with it
  and leaving "reading…" on the page. Tests drive the slot with the helper's
  real reply shape, and with the parser and the row builder made to raise.

## 0.2.40 (2026-09-18)

- The Snapshots list is grouped by who took each snapshot, in the process
  list's shape: a header with a count for "Taken by you" (from the page or by
  hand), "Taken by pacman" (snap-pac's pairs, or Timeshift's autosnap) and
  "Taken on a timer" (Snapper's timeline, Timeshift's schedule), newest
  first inside each. Yours sit on top, since those are the ones a user goes
  looking for; a group with nothing in it is left out, so a machine with
  snap-pac alone shows one header.
- A pacman pair is one row: the transaction's time (the before's), what
  pacman did (the before's description, the command; the after's names the
  packages), both numbers, and the size the two hold together where Snapper
  reports one. The row opens on a click to the two snapshots underneath,
  after then before, each with its own number and Delete; the pair row has
  no Delete of its own, so a pair is taken apart one snapshot at a time,
  and a half whose other half is gone stays a plain row. Open pairs stay
  open across a refresh. One line above the list says a transaction is one
  row and that a click opens it.
- On the development machine (snap-pac only, NUMBER_LIMIT 50) the 50
  snapshots become 26 rows: one header and 25 transactions, 76 with every
  pair open.
- A boxed list rounds its corners on the first and last row that are shown,
  so a hidden half at the end of the box does not take the pair row's
  corners. The kind icons gain the chevron of a closed and an open pair
  (Adwaita pan-end and pan-down, Breeze arrow-right and arrow-down), under
  the all-or-nothing rule.

## 0.2.39 (2026-09-18)

- A Snapshots page, for Snapper and Timeshift. Detection is the binary on
  PATH and a config (`/etc/snapper/configs`, `/etc/timeshift/timeshift.json`);
  a machine with neither gets one line naming both, and no advice to install
  anything. A tool that is installed and has no snapshots says that instead.
  The list is newest first: when each snapshot was taken, who took it
  (pacman through snap-pac's before and after pair, Snapper's timeline,
  ArchPM, or a person by hand; Timeshift's autosnap, schedule or by hand),
  its description, its number, and its size where the tool reports one,
  which Snapper does only with btrfs quota on; when it does not, the page
  says so in one line. The Limine boot menu's share of the list is named
  when limine-snapper-sync is installed (its MAX_SNAPSHOT_ENTRIES).
- The list is read when the page opens and on its button, never on the
  sampling cycle, the failed services check's pattern. The plain read comes
  first: Snapper answers a user only when its config names them in
  ALLOW_USERS or ALLOW_GROUPS, and refuses everyone else with "No
  permissions." from snapperd over D-Bus (24 ms on the development
  machine); Timeshift answers root only. When the plain read is refused the
  page says why and offers "Read snapshots", which reads through the root
  helper: the password once, and polkit's keep makes the next few minutes
  silent, so Refresh after that and the reread after taking or deleting ask
  nothing. The page shows the tool's own time and the whole helper call's.
- Taking a snapshot goes through the helper as `snapper create --type single
  --userdata made-by=archpm`, kept until deleted, with the description as the
  only free text the helper ever passes on: letters, digits, space, dot,
  underscore and hyphen, at most 72 (snap-pac's own limit). The dialog's
  validator keeps the input inside that set, the client reduces it once
  more, and the helper refuses anything outside it rather than stripping.
  Chosen over no description at all because a snapshot without one is a
  riddle a week later; chosen this narrow because the text ends up in
  snapper's XML and, through limine-snapper-sync, in a boot menu entry.
- Deleting a snapshot goes through the helper after one confirmation that
  says what is lost (that moment of the system and the way back to it, and
  for half of a pacman pair that its other half stays), whether it is the
  oldest or the newest, and what remains: how many, from when to when. The
  last remaining snapshot is never deleted: its button is disabled and says
  why, and the helper refuses it on its own count. No second dialog.
- No rollback. Restoring changes what the machine boots and stays outside
  ArchPM; the page says so and names the way: with Limine, the snapshot
  under Snapshots in the boot menu and limine-snapper-restore; with Snapper
  alone, snapper rollback; with Timeshift, its window or --restore.
- Without the root helper the page reads what it can and shows no buttons,
  with a line saying that reading (where refused), taking and deleting need
  the helper; the Cleanup page's root rows pattern. The rail has a ninth
  icon, Adwaita's document-open-recent-symbolic or Breeze's view-history,
  under the same all-or-nothing rule; the rows carry an icon for their
  origin (a package, a person, a timer), checked the same way.
- The helper's polkit message and its docstring name the snapshot commands.
  Help has a Snapshots section. The root panel's table in the README lists
  what the helper runs.

## 0.2.38 (2026-09-17)

- The test run is clean: 391 tests, no warnings, nothing on stderr, with
  every Python warning enabled. Two warnings came from the application:
  the two nvidia-smi streams left their pipe to the garbage collector
  (ResourceWarning: unclosed file), which closed it late; the stream now
  closes the pipe itself when the process is stopped or restarted. Nothing
  leaked for the lifetime of the agent: each restart of a stream freed the
  previous pipe at once through reference counting, and one pipe per
  stream stayed open until stop, which is the pipe being read. And the
  process filter called QSortFilterProxyModel.invalidateFilter(), which Qt
  6.10 deprecated together with its rows and columns variants; the filter
  now changes its parameter between beginFilterChange() and
  endFilterChange(Rows), so the proxy runs the row filter once at the end
  and emits inserts and removes for the rows whose acceptance changed,
  instead of resetting the whole model; the view keeps its selection and
  its open branches. On a Qt before 6.10 the old call stays.
- Three more came from the tests and one from the Network page: three
  test classes made a settings folder and never cleaned it, one test let
  the root helper's argparse error reach stderr, and the Network page
  passed an int where Qt wants an alignment flag. All fixed.

## 0.2.37 (2026-09-17)

- README brought back to what the application does after fifteen releases,
  every claim checked against the code and every command run: the verdict
  line and Root tasks at the foot of the Overview, the game card's own
  verdict and colour rule, the Processes page's sections, counts, roles and
  three views, Startup's Enabled and Disabled groups and its confirmation
  that is not a password, the System page's failed services block, the
  confirmation for a single process, the offer to force what stays and the
  sentence that it cannot be undone, the theme, the header bar, and the
  words the application now uses. The agent measured again: 3.6% of one
  core over 3 h 19 min of desktop use, a sample about 75 ms.
- The install section leads with the package, built from a release tag with
  makepkg -si, and says plainly that the package is ready and waiting for
  the AUR to reopen. The checkout route with install.sh comes second.
- A release tag now builds itself. The PKGBUILD's source was the tag's own
  tarball, whose checksum can only be committed after the tag exists, so
  every tag so far carried the PKGBUILD of the release before it. The
  source is now pinned to the commit the release is built from, and the tag
  sits on the commit that carries the matching PKGBUILD.
- Seven new screenshots, one per page, the window as the application
  renders it at 1299 by 982, the rail pinned on the Overview and collapsed
  on the rest. The widget images are unchanged.

## 0.2.36 (2026-09-17)

- Processes: a section header counts what it names. "Apps (55)" counted
  processes and read as fifty-five programs; it now counts the rows under
  it at its top level, so a program with twenty processes is one, and
  reads "Apps (5)". The number of processes is in the header's tooltip:
  "5 rows here, 57 processes in all: a program with several processes is
  one row."
- A closed group row carries its number of processes: "Brave (20)". When
  the group is open the number goes, since the rows are then visible.
  In the flat view with every process shown there are no groups, so the
  header's count is the number of processes, as before.

## 0.2.35 (2026-09-17)

- The words on the five paths a Windows user walks, last of the beginner
  audit. Where a plain word carries the same meaning it replaces the term;
  where the term is the thing itself it stays, with the plain word first.
  Processes: the columns read Threads, Video memory, Priority and Disk
  instead of Thr, VRAM, Nice and Disk I/O; PID stays, since the id is the
  thing itself, and the search field says "Find a program by name, command
  or process id". The context menu reads "Terminate: ask it to quit",
  "Force kill: end it at once", "Pause", "Resume", "… with everything it
  started" and "Cores it may use…"; SIGTERM, SIGKILL, SIGSTOP, SIGCONT and
  "affinity" are gone from it. The toast after an action is a sentence:
  "Asked 1 process to quit", "Force-killed 3 processes", "Priority changed
  for 2 processes"; "process(es)" is gone everywhere. The checkbox "CPU%
  ÷ cores" reads "CPU as % of all cores".
- One scale for one thing on the game card: CPU reads "19%" with "of all
  16 cores" under it, as the tile at the top of the page, instead of "9%"
  beside "1.4 of 16 cores"; video memory reads "of the card's 12 GB"
  instead of the same number again in MB. The captions read "with
  everything it started", "across 3 processes" and "it may use" instead of
  "Whole tree", "In 3 processes" and "Allowed"; the line under the name
  says "Priority raised" instead of "Nice -4" and "process 4562" instead
  of "pid 4562".
- A temperature carries its reference on the tile, not only in a tooltip:
  "normal" under 80°, "warm" to 90°, "hot" above, with the colour by the
  same rule, so 61° under load is green and not amber as the heat scale
  had it. The machine line reads "8 cores, 16 threads" instead of
  "8c/16t"; the memory card reads "On disk (swap)"; the Startup page
  reads "System · your own copy" instead of "User (override)" and
  "Running · process 1323" instead of "pid".
- Kept, and why: PID as a column header and "swap", "threads" and "cores"
  as words, each the thing itself with no plain word that means the same;
  "Force kill" as the button; and the Help glossary's own definitions,
  untouched on purpose.

## 0.2.34 (2026-09-17)

- Overview: a verdict line at the top, above the tiles, in words. "Nothing
  is straining the machine." is the normal state; otherwise the program
  that is: "PyCharm is using 44% of the processor.", "Memory is nearly
  full: Brave holds 8.0 GB.", "The processor is fully busy; the biggest
  user is X (12%)." or "The processor is running hot: 92°." A game at that
  share reads "that is the game" and is not a strain. When a program is
  named the line is a link that opens Processes with that row selected.
  Computed from the sample already taken, in verdict.py: memory above 85%
  of RAM, one program above a quarter of the whole processor, the whole
  processor above 85% with no single culprit, a part above 90°; a strain
  is named only when it holds for three samples in a row, so a page load
  or a compile step does not flash a name. Calm and hot show at once.
- Root tasks is no longer the first button on the page. It sits at the
  foot of the Overview, last, and the machine line under the verdict is
  quiet: the hostname is no longer the yellow headline. The verdict is
  what the eye lands on.
- The game card has its own verdict and its own colour rule, not the heat
  scale: "The graphics card is fully used: the game is the limit, as it
  should be." in green at 85% and above; "The processor is the limit: the
  graphics card is waiting for it." in amber when the card idles while
  the game's tree holds a core; "Neither is busy: a menu, a loading
  screen, a frame cap or waiting for the network." in the quiet colour;
  and "Running hot" in red above 90°. The GPU tile's caption says "fully
  used", "room to spare" or "mostly idle" instead of "GPU busy" at every
  value, and 93% is green, not red. The graphs are untouched.

## 0.2.33 (2026-09-17)

- Processes: a member of a browser is named for what it is, from what its
  own command line says. A Chromium renderer reads "Brave · page", one that
  hosts extensions "Brave · extension", the gpu process "Brave · graphics",
  the utilities "Brave · network", "audio", "storage", "media" or
  "printing", and zygotes, brokers and the like "Brave · helper". Firefox
  says it in the last word after -contentproc, so a tab is a page and
  socket, rdd, gpu and utility are network, media, graphics and helper.
  The same rule covers Chrome, Electron applications, Steam's webhelper and
  Qt WebEngine, since they use Chromium's flags. A process the rules cannot
  place keeps its plain name; nothing is guessed. The name's tooltip says
  what the role means, and the search finds "page".
- The group dialog says what goes, not which ids. Instead of one member's
  full command line and a list of process ids it reads "Brave and
  everything that belongs to it: 19 processes, among them 5 pages, 2
  extension processes, the graphics, 7 helpers. Every open page closes
  with it." The title keeps the count, as before.

## 0.2.32 (2026-09-17)

- Terminate and Force kill ask first for a single process, as they already
  did for a group. An audit of the application sent a real SIGTERM to a live
  browser process because a single process needed no confirmation; it does
  now. Every irreversible action carries the same short sentence, "This
  cannot be undone.", in the same words each time, so the user learns the
  pattern once: Terminate, Force kill, End game on the Overview, and the
  system-logs cleanup, whose dialog already said the logs go for good.
- After a Terminate the process is watched on the next samples. When it is
  still there after five seconds, the toast says "<name> is still running."
  with one button, Force kill, so the user is not sent hunting through a
  context menu; the button opens the same confirmation as any Force kill.
  Nothing is forced by itself, there is one offer per action, a process
  that went or whose pid was reused by another is not offered, and the
  offer comes on whichever page is showing. End game is watched the same
  way, and its dialog says so instead of pointing at the Processes tab.
- The toast can carry one button. A notice with a button stays twelve
  seconds; a plain one four, as before.

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
