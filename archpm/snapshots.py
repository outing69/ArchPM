"""Filesystem snapshots, read-only on this side: what Snapper or Timeshift
has, taken once when the page opens and again on its Refresh button, never
on the sampling cycle, never on a timer. Making and deleting go through the
root helper (archpm/root/helper.py); this file only detects the tool, tries
the plain-user listing and parses what either side returns.

Snapper answers a plain user only when the config's ALLOW_USERS or
ALLOW_GROUPS names them (snapperd checks that over D-Bus and says "No
permissions." otherwise); Timeshift always wants root. When the plain read
is refused, the page reads through the helper on request.

The rows are the snapshots folded (a pacman pair is one row, its two halves
under it) and grouped by who took them (yours, pacman's, a timer's).

No Qt in this file.
"""
from __future__ import annotations

import calendar
import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field

SNAPPER, TIMESHIFT = "snapper", "timeshift"
TIMEOUT = 20
# What a description may hold on its way to the helper: letters, digits,
# space, dot, underscore, hyphen, at most 72 characters (snap-pac's own
# limit). Enough for "before nvidia 580" or "clean install"; nothing that
# needs quoting in a shell, an XML file (snapper's info.xml) or a boot menu
# entry (limine-snapper-sync copies the description into limine.conf).
DESCRIPTION_CHARS = "A-Za-z0-9 ._-"
DESCRIPTION_MAX = 72
DESCRIPTION_RE = re.compile(rf"[{DESCRIPTION_CHARS}]{{0,{DESCRIPTION_MAX}}}")
SNAPPER_CONFIG_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")
TIMESHIFT_NAME_RE = re.compile(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}")
TIMESHIFT_TAGS = set("OBHDWM")
MADE_BY = "made-by=archpm"       # snapper userdata on a snapshot this page took
LIMINE_CONF = "/etc/limine-snapper-sync.conf"

# origins, as the page names them
PACMAN, TIMELINE, ARCHPM, BY_HAND, SCHEDULED = ("pacman", "timeline", "ArchPM",
                                                "by hand", "scheduled")
# the groups of the list, in the order shown: yours on top, since those are
# the ones a user goes looking for
YOURS, PACMANS, TIMED = "Taken by you", "Taken by pacman", "Taken on a timer"
GROUPS = (YOURS, PACMANS, TIMED)
GROUP_OF = {ARCHPM: YOURS, BY_HAND: YOURS, PACMAN: PACMANS, TIMELINE: TIMED, SCHEDULED: TIMED}


@dataclass
class Snapshot:
    tool: str
    config: str                  # snapper config name, or "timeshift"
    id: str                      # snapper number as text, or timeshift's name
    taken_at: float = 0.0        # epoch seconds
    kind: str = "single"         # snapper: single, pre, post
    origin: str = BY_HAND        # PACMAN, TIMELINE, ARCHPM, BY_HAND, SCHEDULED
    description: str = ""
    size: int | None = None      # bytes, when the tool reports it
    pair: str = ""               # the other half of a pre/post pair, when known
    cleanup: str = ""

    @property
    def label(self) -> str:
        """"#265" for snapper, the name for timeshift."""
        return f"#{self.id}" if self.tool == SNAPPER else self.id

    @property
    def when(self) -> str:
        return time.strftime("%d %b %Y %H:%M", time.localtime(self.taken_at))

    @property
    def why(self) -> str:
        """Who made it and, for a pacman pair, which half."""
        if self.origin == PACMAN and self.kind in ("pre", "post"):
            return f"pacman, {'before' if self.kind == 'pre' else 'after'}"
        return self.origin


@dataclass
class Pair:
    """One pacman transaction: snap-pac's before and after as one row of the
    list. The time is the before's, the description the command it ran (the
    after's names the packages), the label both numbers, the size what the
    two hold together. Its halves are the two snapshots, newest first."""
    pre: Snapshot
    post: Snapshot

    @property
    def tool(self) -> str:
        return self.pre.tool

    @property
    def config(self) -> str:
        return self.pre.config

    @property
    def origin(self) -> str:
        return PACMAN

    @property
    def taken_at(self) -> float:
        return self.pre.taken_at

    @property
    def when(self) -> str:
        return self.pre.when

    @property
    def why(self) -> str:
        return PACMAN

    @property
    def label(self) -> str:
        return f"{self.pre.label} · {self.post.label}"

    @property
    def description(self) -> str:
        return self.pre.description or self.post.description

    @property
    def size(self) -> int | None:
        sizes = [s.size for s in (self.pre, self.post) if s.size is not None]
        return sum(sizes) if sizes else None

    @property
    def halves(self) -> list[Snapshot]:
        return [self.post, self.pre]


Entry = Snapshot | Pair      # one row of the list


@dataclass
class Setup:
    snapper: bool = False
    timeshift: bool = False
    configs: list[str] = field(default_factory=list)   # snapper's
    limine_entries: int = 0      # boot entries limine-snapper-sync keeps, 0 = not installed

    @property
    def tool(self) -> str:
        if self.snapper:
            return SNAPPER
        return TIMESHIFT if self.timeshift else ""


@dataclass
class Listing:
    tool: str = ""
    snapshots: list[Snapshot] = field(default_factory=list)   # newest first
    needs_root: bool = False     # the plain read was refused
    as_root: bool = False        # read through the helper
    took_ms: float = 0.0         # the tool's own time
    call_ms: float = 0.0         # the whole helper call, pkexec included (as_root only)
    taken_at: float = 0.0
    error: str = ""

    @property
    def sized(self) -> bool:
        return any(s.size is not None for s in self.snapshots)


# -- detection -----------------------------------------------------------------
def limine_entries(path: str = LIMINE_CONF, which=shutil.which) -> int:
    """How many snapshots limine-snapper-sync puts in the boot menu; 0 when
    it is not installed. The file is world-readable; the default is 5."""
    if which("limine-snapper-sync") is None:
        return 0
    try:
        with open(path) as fh:
            for line in fh:
                key, _, value = line.partition("=")
                if key.strip() == "MAX_SNAPSHOT_ENTRIES" and value.strip().isdigit():
                    return int(value.strip())
    except OSError:
        pass
    return 5


def snapper_configs(run=subprocess.run) -> list[str]:
    """`snapper --jsonout list-configs` works without root."""
    try:
        proc = run(["snapper", "--jsonout", "list-configs"], capture_output=True,
                   text=True, timeout=TIMEOUT, check=False)
        data = json.loads(proc.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []
    return [c.get("config", "") for c in data.get("configs", []) if c.get("config")]


def detect(which=shutil.which, run=subprocess.run) -> Setup:
    setup = Setup(snapper=which("snapper") is not None,
                  timeshift=which("timeshift") is not None,
                  limine_entries=limine_entries(which=which))
    if setup.snapper:
        setup.configs = snapper_configs(run)
    return setup


# -- parsing ---------------------------------------------------------------------
def _utc(text: str) -> float:
    """"2026-09-17 19:02:09" as snapper prints it with --utc --iso."""
    try:
        return calendar.timegm(time.strptime(text.strip(), "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return 0.0


def _local_name(name: str) -> float:
    """Timeshift names its snapshots by local time: 2026-09-17_21-00-18."""
    try:
        return time.mktime(time.strptime(name, "%Y-%m-%d_%H-%M-%S"))
    except (ValueError, OverflowError):
        return 0.0


def snapper_origin(kind: str, description: str, cleanup: str, userdata: dict) -> str:
    if userdata.get("made-by") == "archpm":
        return ARCHPM
    if kind in ("pre", "post"):
        return PACMAN
    if cleanup == "timeline" or description == "timeline":
        return TIMELINE
    return BY_HAND


def parse_snapper(config: str, text: str) -> list[Snapshot]:
    """`snapper --jsonout --utc --iso -c CONFIG list`: {"CONFIG": [rows]}.
    Row 0 is the live filesystem, not a snapshot. A post carries its pre's
    number; the pre gets its post's from the pass over the list."""
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return []
    rows = data.get(config) if isinstance(data, dict) else None
    if not isinstance(rows, list):
        rows = next((v for v in data.values() if isinstance(v, list)), []) \
            if isinstance(data, dict) else []
    out: list[Snapshot] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        number = row.get("number")
        if not isinstance(number, int) or number <= 0:
            continue
        userdata = row.get("userdata") or {}
        if not isinstance(userdata, dict):
            userdata = {}
        kind = str(row.get("type") or "single")
        desc = str(row.get("description") or "")
        cleanup = str(row.get("cleanup") or "")
        size = row.get("used-space")
        pre = row.get("pre-number")
        out.append(Snapshot(
            tool=SNAPPER, config=config, id=str(number), taken_at=_utc(str(row.get("date") or "")),
            kind=kind, origin=snapper_origin(kind, desc, cleanup, userdata),
            description=desc, size=int(size) if isinstance(size, int) else None,
            pair=str(pre) if isinstance(pre, int) and pre > 0 else "", cleanup=cleanup,
        ))
    posts = {s.pair: s.id for s in out if s.kind == "post" and s.pair}
    for s in out:
        if s.kind == "pre" and not s.pair:
            s.pair = posts.get(s.id, "")
    return out


def parse_timeshift(text: str) -> list[Snapshot]:
    """`timeshift --list`: a header, then one line per snapshot:
    "Num  >  2026-09-17_21-00-18  O B  {timeshift-autosnap} {created before upgrade}".
    The tags are O (on demand), B (boot), H, D, W, M (the schedule)."""
    out: list[Snapshot] = []
    for line in (text or "").splitlines():
        m = re.match(r"\s*\d+\s+>?\s*(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\s*(.*)$", line)
        if not m:
            continue
        name, rest = m.group(1), m.group(2).strip()
        tags = set()
        words = rest.split()
        while words and words[0] in TIMESHIFT_TAGS:
            tags.add(words.pop(0))
        desc = " ".join(words)
        if "timeshift-autosnap" in desc:
            origin = PACMAN
        elif tags & set("BHDWM"):
            origin = SCHEDULED
        else:
            origin = BY_HAND
        out.append(Snapshot(tool=TIMESHIFT, config=TIMESHIFT, id=name, taken_at=_local_name(name),
                            origin=origin, description=desc))
    return out


def parse(tool: str, outputs: list) -> list[Snapshot]:
    """(config, text) pairs, from the plain read or from the helper's reply,
    to one list, newest first."""
    found: list[Snapshot] = []
    for config, text in outputs:
        found.extend(parse_snapper(config, text) if tool == SNAPPER else parse_timeshift(text))
    found.sort(key=lambda s: (s.taken_at, _sort_id(s)), reverse=True)
    return found


def _sort_id(s: Snapshot):
    return int(s.id) if s.id.isdigit() else 0


# -- rows ------------------------------------------------------------------------
def fold(snapshots: list[Snapshot]) -> list[Entry]:
    """The rows of the list, newest first: a pacman pair whose two halves
    are both in the list becomes one entry, at its before's time; a half
    without its other half, and every other snapshot, stays a row of its
    own."""
    by_key = {(s.config, s.id): s for s in snapshots}
    out: list[Entry] = []
    seen: set[tuple[str, str]] = set()
    for s in snapshots:
        key = (s.config, s.id)
        if key in seen:
            continue
        seen.add(key)
        other = by_key.get((s.config, s.pair)) if s.pair else None
        if (other is not None and (other.config, other.id) not in seen
                and {s.kind, other.kind} == {"pre", "post"}):
            seen.add((other.config, other.id))
            out.append(Pair(s, other) if s.kind == "pre" else Pair(other, s))
        else:
            out.append(s)
    out.sort(key=lambda e: (e.taken_at, _sort_id(e.pre if isinstance(e, Pair) else e)),
             reverse=True)
    return out


def grouped(entries: list[Entry]) -> list[tuple[str, list[Entry]]]:
    """The rows by who took them, in GROUPS order; a group with nothing in
    it is left out."""
    buckets: dict[str, list[Entry]] = {g: [] for g in GROUPS}
    for e in entries:
        buckets[GROUP_OF.get(e.origin, YOURS)].append(e)
    return [(g, buckets[g]) for g in GROUPS if buckets[g]]


def count_rows(snapshots: list[Snapshot]) -> tuple[int, int]:
    """(rows the list shows folded, rows with every pair open), headers
    included: what the page does to a listing."""
    groups = grouped(fold(snapshots))
    folded = sum(1 + len(members) for _g, members in groups)
    pairs = sum(1 for _g, members in groups for e in members if isinstance(e, Pair))
    return folded, folded + 2 * pairs


# -- the plain read ----------------------------------------------------------------
def read_as_user(setup: Setup | None = None, run=subprocess.run) -> Listing:
    """Try without root. Snapper says "No permissions." unless ALLOW_USERS or
    ALLOW_GROUPS names this user; Timeshift refuses every plain user."""
    setup = detect(run=run) if setup is None else setup
    listing = Listing(tool=setup.tool, taken_at=time.time())
    if not setup.tool:
        return listing
    if setup.tool == TIMESHIFT:
        listing.needs_root = True
        return listing
    start = time.perf_counter()
    outputs = []
    for config in setup.configs or ["root"]:
        try:
            proc = run(["snapper", "--jsonout", "--utc", "--iso", "-c", config, "list"],
                       capture_output=True, text=True, timeout=TIMEOUT, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            listing.error = f"snapper could not be asked: {exc}"
            return listing
        if proc.returncode != 0:
            err = ((proc.stderr or "") + (proc.stdout or "")).strip()
            if "No permissions" in err:
                listing.needs_root = True
            else:
                lines = err.splitlines()
                listing.error = lines[-1] if lines else f"snapper returned code {proc.returncode}"
            return listing
        outputs.append((config, proc.stdout))
    listing.snapshots = parse(SNAPPER, outputs)
    listing.took_ms = (time.perf_counter() - start) * 1000
    return listing


def from_helper(result: dict) -> Listing:
    """The helper's `snapshots-list` reply: {"tool", "outputs": [[config, text]], "took_ms"}."""
    tool = str(result.get("tool") or "")
    listing = Listing(tool=tool, as_root=True, taken_at=time.time(),
                      took_ms=float(result.get("took_ms") or 0.0))
    listing.snapshots = parse(tool, [tuple(o) for o in result.get("outputs") or [] if len(o) == 2])
    return listing


# -- text --------------------------------------------------------------------------
def sanitise(text: str) -> str:
    """A description reduced to DESCRIPTION_CHARS, one space between words,
    at most DESCRIPTION_MAX characters. The helper checks the same rule and
    refuses instead of stripping; this side makes sure it never has to."""
    kept = re.sub(rf"[^{DESCRIPTION_CHARS}]", " ", text or "")
    return " ".join(kept.split())[:DESCRIPTION_MAX].strip()


def position(snap: Snapshot, snapshots: list[Snapshot]) -> str:
    """"the oldest", "the newest", "" : where it stands, newest first."""
    if len(snapshots) < 2:
        return ""
    if snapshots[0] is snap or snapshots[0].id == snap.id:
        return "the newest"
    if snapshots[-1] is snap or snapshots[-1].id == snap.id:
        return "the oldest"
    return ""


def remaining(snap: Snapshot, snapshots: list[Snapshot]) -> list[Snapshot]:
    return [s for s in snapshots if not (s.config == snap.config and s.id == snap.id)]


def restore_advice(setup: Setup, which=shutil.which) -> str:
    """How a snapshot is restored, since not here."""
    if setup.tool == SNAPPER and which("limine-snapper-restore") is not None:
        return ("On this machine: pick it under Snapshots in the Limine boot menu, boot it, "
                "and run limine-snapper-restore.")
    if setup.tool == SNAPPER:
        return ("With Snapper: snapper rollback followed by the number, then reboot; or "
                "Btrfs Assistant.")
    if setup.tool == TIMESHIFT:
        return "With Timeshift: its window, or timeshift --restore."
    return ""

