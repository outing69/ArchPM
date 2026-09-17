"""Item model for the process list: grouped by application, a tree by parent
pid, or flat.

Grouped: a row per application that owns two or more processes (see
grouping.py), expandable to the processes. The group row is a synthetic
ProcSample with a negative pid whose numbers are the sums; an application
with a single process sits at the root as itself.

Rows are updated in place every tick instead of rebuilt: a rebuild would drop
the selection and the expanded/collapsed state and make the view flicker.
Processes that appear are inserted under their parent (or at the top level
when the parent is not in the snapshot), processes that vanish are removed
with their subtree, and a process whose parent changed (the parent died and
init or a subreaper adopted it) is removed and re-inserted under the new one.
"""
from __future__ import annotations

import textwrap
import time
from dataclasses import dataclass

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QFont

from ..appinfo import ROLE_ABOUT, describe
from ..grouping import build_groups, summarize
from ..model import ProcSample
from ..sections import ABOUT, KEY_OF_PID, LABEL, RANK, SECTION_PID, is_section, section_of, uid_min
from . import theme
from .hints import tooltip_html
from .navrail import kind_icon
from .widgets import app_icon, human_bytes

SORT_ROLE = Qt.ItemDataRole.UserRole + 1
PID_ROLE = Qt.ItemDataRole.UserRole + 2

COL_PID, COL_NAME, COL_CPU, COL_MEM, COL_GPU, COL_VRAM, COL_THREADS, \
    COL_NICE, COL_IO, COL_USER, COL_STATUS, COL_STARTED, COL_CATEGORY, COL_CMD = range(14)

HEADERS = [
    "PID", "Name", "CPU %", "Memory", "GPU %", "Video memory", "Threads",
    "Priority", "Disk", "User", "Status", "Started", "Category", "Command",
]
HINT_KEYS = [
    "col.pid", "col.name", "col.cpu", "col.mem", "col.gpu", "col.vram", "col.threads",
    "col.nice", "col.io", "col.user", "col.status", "col.started", "col.category", "col.cmd",
]


def age_text(seconds: float) -> str:
    """How long ago something started: "just now", "45 s", "12 min", "3 h 05", "2 d 14 h"."""
    if seconds < 10:
        return "just now"
    if seconds < 60:
        return f"{seconds:.0f} s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.0f} min"
    hours = minutes / 60
    if hours < 24:
        return f"{int(hours)} h {int(minutes % 60):02d}"
    return f"{int(hours // 24)} d {int(hours % 24)} h"

_RIGHT = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
_CENTER = int(Qt.AlignmentFlag.AlignCenter)
_LEFT = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

ALIGN = {
    COL_PID: _RIGHT, COL_CPU: _RIGHT, COL_MEM: _RIGHT, COL_GPU: _RIGHT,
    COL_VRAM: _RIGHT, COL_THREADS: _RIGHT, COL_NICE: _CENTER, COL_IO: _RIGHT,
    COL_STATUS: _CENTER, COL_STARTED: _RIGHT,
}
_SUMMED = {COL_CPU, COL_MEM, COL_GPU, COL_VRAM, COL_THREADS, COL_IO}
MODES = ("grouped", "tree", "flat")

# Tooltips: about 600 px of the tooltip font per line, and a command line
# cut short; the Command column still has the whole thing.
TIP_WIDTH = 90
TIP_CMD_MAX = 240


def short_cmd(cmd: str) -> str:
    return cmd if len(cmd) <= TIP_CMD_MAX else cmd[:TIP_CMD_MAX - 1] + "…"


def wrap_tip(lines: list[str]) -> str:
    out: list[str] = []
    for line in lines:
        out.extend(textwrap.wrap(line, TIP_WIDTH, break_long_words=True,
                                 break_on_hyphens=False) or [""])
    return "\n".join(out)


def group_source(key: str) -> str:
    """"cgroup:app-steam@1.service" -> "the cgroup app-steam@1.service"."""
    kind, _, value = key.partition(":")
    return {"cgroup": f"the cgroup {value}", "exe": f"the program file {value}",
            "name": f"the process name {value}", "steam": f"Steam app {value}"}.get(kind, key)


@dataclass(slots=True)
class Totals:
    """Sums over a process and its whole subtree; shown on a collapsed row."""
    count: int = 0
    cpu: float = 0.0
    rss: int = 0
    gpu_sm: float = 0.0
    gpu_mem: float = 0.0
    threads: int = 0
    io: float = 0.0


# "Busy" means worth showing even without a name and icon: really working the
# CPU or GPU, really moving data, or really large. Merely holding some VRAM
# (every compositor does) or idling at 3% does not count. A process stays
# visible this long after it was last busy, so a value hovering around the
# threshold does not make the row blink in and out.
BUSY_CPU = 5.0          # % of one core
BUSY_IO = 1024 * 1024   # B/s
BUSY_RSS = 1 << 30      # bytes
BUSY_HOLD_S = 15.0


def is_busy(p: ProcSample) -> bool:
    return (p.cpu_percent >= BUSY_CPU or p.gpu_sm > 0
            or p.io_read_bps + p.io_write_bps >= BUSY_IO or p.mem_rss >= BUSY_RSS)


class Node:
    __slots__ = ("proc", "parent", "children", "row", "totals")

    def __init__(self, proc: ProcSample | None, parent: Node | None) -> None:
        self.proc = proc
        self.parent = parent
        self.children: list[Node] = []
        self.row = 0
        self.totals = Totals()

    def reindex(self) -> None:
        for i, c in enumerate(self.children):
            c.row = i

    def descendants(self):
        for c in self.children:
            yield c
            yield from c.descendants()


class ProcModel(QAbstractItemModel):
    def __init__(self, ncpu: int, parent=None) -> None:
        super().__init__(parent)
        self.ncpu = ncpu
        self.normalize_cpu = False   # True = CPU% divided by number of cores
        self.frozen = False
        self.mode = "tree"
        self._group_ids: dict[str, int] = {}     # group key -> stable negative pid
        self._group_of: dict[int, int] = {}      # pid -> group pid, this tick
        self._root = Node(None, None)
        self._nodes: dict[int, Node] = {}
        self._last: list[ProcSample] = []
        self.busy_until: dict[int, float] = {}   # pid -> monotonic deadline
        self._expanded: set[int] = set()         # pids whose row the view shows expanded
        self.steam_pid = 0                       # the Steam client, if it runs
        self.hoisted: set[int] = set()           # pid 1 and the systemd user managers
        # Three sections (Apps, Background, System) as root rows, in Grouped
        # and Flat with every process shown; see sections.py. Tree keeps its
        # parent hierarchy, which is its whole point.
        self.sections = False
        self._section_of: dict[int, int] = {}    # pid or group pid -> section pid, this tick
        self._uid_min = uid_min()
        self.fallbacks = 0                       # processes placed by owner, not by cgroup

    @property
    def tree(self) -> bool:
        return self.mode == "tree"

    @property
    def sectioned(self) -> bool:
        return self.sections and self.mode != "tree"

    def flags(self, index: QModelIndex):
        # A section header cannot be selected, so no action can ever reach
        # everything under it by accident; it opens and closes, nothing else.
        p = self.proc_at(index)
        if p is not None and is_section(p.pid):
            return Qt.ItemFlag.ItemIsEnabled
        return super().flags(index)

    @property
    def hierarchical(self) -> bool:
        return self.mode != "flat"

    # -- Qt structure -------------------------------------------------------
    def _node(self, index: QModelIndex) -> Node:
        return index.internalPointer() if index.isValid() else self._root

    def index(self, row: int, column: int, parent=QModelIndex()) -> QModelIndex:
        node = self._node(parent)
        if 0 <= row < len(node.children) and 0 <= column < len(HEADERS):
            return self.createIndex(row, column, node.children[row])
        return QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:  # type: ignore[override]
        if not index.isValid():
            return QModelIndex()
        p = index.internalPointer().parent
        if p is None or p is self._root:
            return QModelIndex()
        return self.createIndex(p.row, 0, p)

    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid() and parent.column() > 0:
            return 0
        return len(self._node(parent).children)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(HEADERS)

    def hasChildren(self, parent=QModelIndex()) -> bool:
        if parent.isValid() and parent.column() > 0:
            return False
        return bool(self._node(parent).children)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if section == COL_CPU and self.normalize_cpu:
                return "CPU % (norm)"
            return HEADERS[section]
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.ToolTipRole:
            return tooltip_html(HINT_KEYS[section])
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node: Node = index.internalPointer()
        p: ProcSample = node.proc
        col = index.column()
        # A collapsed program stands for its whole subtree: show the sums.
        totals = node.totals if (self.tree and node.children
                                 and p.pid not in self._expanded) else None

        if role == PID_ROLE:
            return p.pid
        if role == SORT_ROLE:
            return self._sort_value(p, col, totals)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return ALIGN.get(col, _LEFT)
        if role == Qt.ItemDataRole.ForegroundRole:
            return self._color(p, col, totals)
        if role == Qt.ItemDataRole.FontRole:
            if is_section(p.pid):
                font = QFont()
                font.setBold(True)
                return font
            return None
        if role == Qt.ItemDataRole.DecorationRole:
            if col != COL_NAME or is_section(p.pid):
                return None
            if p.icon:
                icon = app_icon(p.icon)
                if not icon.isNull():
                    return icon
            # no icon of its own: the icon of the section it sits in
            icon = kind_icon(self._section_key(p))
            return None if icon.isNull() else icon
        if role == Qt.ItemDataRole.ToolTipRole:
            if is_section(p.pid):
                return wrap_tip([ABOUT[KEY_OF_PID[p.pid]]])
            if totals and col in _SUMMED:
                return f"Total of {totals.count} processes in this tree"
            if p.members and col == COL_MEM:
                lines = [f"Memory of {p.members} processes, with pages they share counted "
                         "once (PSS). Measured every ten seconds, so up to ten seconds old."]
                if p.mem_approx:
                    lines.append("One or more of them could not be measured yet and count "
                                 "their RSS instead, which overstates a little.")
                return wrap_tip(lines)
            if p.members and col in _SUMMED:
                return f"Total of {p.members} processes in this group"
            if col == COL_NAME:
                # Says what each line is: a beginner reading "python3" under
                # "ArchPM" should see that one is the program, the other the process.
                exe = p.argv[0] if p.argv else p.name
                about = describe(exe, p.app_name) or describe(p.name)
                lines = [about] if about else []
                if p.role:
                    lines.append(ROLE_ABOUT.get(p.role, ""))
                if p.members:
                    lines.append(f"{p.members} processes of one application, grouped by "
                                 f"{group_source(p.cgroup)}.")
                if p.app_name:
                    lines.append(f"Program: {p.app_name}")
                lines.append(f"Process name: {p.name}")
                if p.cmdline:
                    lines.append(f"Command: {short_cmd(p.cmdline)}")
                return wrap_tip(lines)
            return wrap_tip([short_cmd(p.cmdline) or p.name])
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return self._text(p, col, totals)

    # -- content ------------------------------------------------------------
    def _cpu(self, p: ProcSample) -> float:
        return p.cpu_percent / self.ncpu if self.normalize_cpu else p.cpu_percent

    def _text(self, p: ProcSample, col: int, t: Totals | None = None):
        if is_section(p.pid):
            return f"{p.name} ({p.members})" if col == COL_NAME else ""
        cpu = t.cpu if t else p.cpu_percent
        rss = t.rss if t else p.mem_rss
        gpu_sm = t.gpu_sm if t else p.gpu_sm
        gpu_mem = t.gpu_mem if t else p.gpu_mem_mb
        threads = t.threads if t else p.num_threads
        io = t.io if t else p.io_read_bps + p.io_write_bps
        if col == COL_PID:
            return "" if p.members else str(p.pid)
        if col == COL_NAME:
            # a member of a browser says what it is: "Brave · page"
            return f"{p.display_name} · {p.role}" if p.role else p.display_name
        if col == COL_CPU:
            v = cpu / self.ncpu if self.normalize_cpu else cpu
            return f"{v:.1f}" if v >= 0.05 else "·"
        if col == COL_MEM:
            return human_bytes(rss)
        if col == COL_GPU:
            return f"{gpu_sm:.0f}" if gpu_sm else ("·" if gpu_mem else "")
        if col == COL_VRAM:
            return f"{gpu_mem:.0f} MB" if gpu_mem else ""
        if col == COL_THREADS:
            return str(threads)
        if col == COL_NICE:
            return str(p.nice)
        if col == COL_IO:
            return f"{human_bytes(io)}/s" if io > 1024 else ""
        if col == COL_USER:
            return p.username
        if col == COL_STATUS:
            return p.status
        if col == COL_STARTED:
            return age_text(time.time() - p.create_time) if p.create_time else ""
        if col == COL_CATEGORY:
            return p.category
        if col == COL_CMD:
            return p.cmdline
        return None

    def _sort_value(self, p: ProcSample, col: int, t: Totals | None = None):
        if is_section(p.pid):
            return RANK[KEY_OF_PID[p.pid]]   # the proxy keeps this order under any sort
        return {
            COL_PID: p.pid, COL_NAME: p.display_name.lower(),
            COL_CPU: t.cpu if t else p.cpu_percent,
            COL_MEM: t.rss if t else p.mem_rss,
            COL_GPU: t.gpu_sm if t else p.gpu_sm,
            COL_VRAM: t.gpu_mem if t else p.gpu_mem_mb,
            COL_THREADS: t.threads if t else p.num_threads, COL_NICE: p.nice,
            COL_IO: t.io if t else p.io_read_bps + p.io_write_bps, COL_USER: p.username,
            COL_STATUS: p.status, COL_STARTED: -p.create_time, COL_CATEGORY: p.category,
            COL_CMD: p.cmdline.lower(),
        }.get(col, "")

    def _color(self, p: ProcSample, col: int, t: Totals | None = None):
        if is_section(p.pid):
            return None
        if p.status == "stopped":
            return QColor(theme.WARN)
        if col == COL_CPU:
            v = (t.cpu if t else p.cpu_percent) / (self.ncpu if self.normalize_cpu else 1)
            if v >= 50:
                return QColor(theme.CRIT if v >= 85 else theme.WARN)
            if v < 0.05:
                return QColor(theme.MUTED)
        elif col == COL_GPU and (t.gpu_sm if t else p.gpu_sm) >= 20:
            return QColor(theme.GPU)
        elif col in (COL_VRAM, COL_CMD, COL_USER, COL_STATUS, COL_CATEGORY):
            return QColor(theme.MUTED)
        elif col == COL_STARTED:
            # something that started in the last minute stands out: that is
            # usually what you opened the list for
            recent = p.create_time and time.time() - p.create_time < 60
            return QColor(theme.ACCENT if recent else theme.MUTED)
        elif col == COL_NICE and p.nice != 0:
            # yellow = stands out (higher priority), green = neatly tucked away
            return QColor(theme.OK if p.nice > 0 else theme.ACCENT)
        return None

    # -- expansion state (fed by the view) --------------------------------------
    def set_expanded(self, pid: int, expanded: bool) -> None:
        if expanded:
            self._expanded.add(pid)
        else:
            self._expanded.discard(pid)
        node = self._nodes.get(pid)
        if node is not None and node.children:
            self.dataChanged.emit(self.createIndex(node.row, 0, node),
                                  self.createIndex(node.row, len(HEADERS) - 1, node),
                                  [Qt.ItemDataRole.DisplayRole, SORT_ROLE])

    def _sum_totals(self, node: Node) -> Totals:
        t = Totals()
        if node.proc is not None:
            p = node.proc
            t.count, t.cpu, t.rss = 1, p.cpu_percent, p.mem_rss
            t.gpu_sm, t.gpu_mem, t.threads = p.gpu_sm, p.gpu_mem_mb, p.num_threads
            t.io = p.io_read_bps + p.io_write_bps
        for c in node.children:
            ct = self._sum_totals(c)
            t.count += ct.count
            t.cpu += ct.cpu
            t.rss += ct.rss
            t.gpu_sm += ct.gpu_sm
            t.gpu_mem += ct.gpu_mem
            t.threads += ct.threads
            t.io += ct.io
        node.totals = t
        return t

    # -- lookups used by the view --------------------------------------------
    def proc_at(self, index: QModelIndex) -> ProcSample | None:
        return index.internalPointer().proc if index.isValid() else None

    def index_for_pid(self, pid: int) -> QModelIndex:
        node = self._nodes.get(pid)
        return self.createIndex(node.row, 0, node) if node else QModelIndex()

    def subtree_pids(self, pid: int) -> list[int]:
        """The process and all its descendants, deepest first (children before
        parents). Real pids only: a group row stands for its members."""
        node = self._nodes.get(pid)
        if node is None:
            return [pid] if pid > 0 else []
        out = [d.proc.pid for d in node.descendants() if d.proc.pid > 0]
        out.reverse()
        if pid > 0:
            out.append(pid)
        return out

    def procs_under(self, pid: int) -> list[ProcSample]:
        """The samples behind subtree_pids(pid), in the same order."""
        return [self._nodes[q].proc for q in self.subtree_pids(pid) if q in self._nodes]

    def pids(self):
        return self._nodes.keys()

    def is_expanded(self, pid: int) -> bool:
        return pid in self._expanded

    def expanded_pids(self) -> set[int]:
        return set(self._expanded)

    def has_children(self, pid: int) -> bool:
        node = self._nodes.get(pid)
        return bool(node and node.children)

    # -- updates --------------------------------------------------------------
    def _section_key(self, p: ProcSample) -> str:
        """The section a row sits in, whether or not the sections are shown."""
        spid = self._section_of.get(p.pid) if self.sectioned else None
        if spid is not None:
            return KEY_OF_PID[spid]
        return section_of(p.cgroup, p.uid, self._uid_min)[0]

    def _desired_parent_pid(self, p: ProcSample, incoming: dict[int, ProcSample]) -> int:
        if self.sectioned:
            if is_section(p.pid):
                return 0
            if self.mode == "grouped" and self._group_of.get(p.pid, 0):
                return self._group_of[p.pid]
            return self._section_of.get(p.pid, SECTION_PID["background"])
        if self.mode == "flat":
            return 0
        if self.mode == "grouped":
            return self._group_of.get(p.pid, 0)
        # A Steam game's tree hangs directly under the Steam client, whatever
        # its real parent: Steam nests games under reaper and the runtime, and
        # once reaper is gone the tree even ends up beside Steam.
        if (p.steam_appid and self.steam_pid and p.pid != self.steam_pid
                and incoming.get(p.ppid) is not None
                and incoming[p.ppid].steam_appid != p.steam_appid):
            return self.steam_pid
        if p.steam_appid and self.steam_pid and p.pid != self.steam_pid and p.ppid not in incoming:
            return self.steam_pid
        # pid 1 and "systemd --user" carry no information of their own and
        # would bury every program two levels deep: their children sit at the root.
        if p.ppid in self.hoisted:
            return 0
        if p.ppid in incoming and p.ppid != p.pid:
            return p.ppid
        return 0

    @staticmethod
    def find_managers(incoming: dict[int, ProcSample]) -> set[int]:
        """pid 1 plus every systemd user manager (a "systemd" directly under pid 1)."""
        return {1} | {p.pid for p in incoming.values()
                      if p.name == "systemd" and p.ppid in (0, 1) and p.pid != 1}

    @staticmethod
    def find_steam(incoming: dict[int, ProcSample]) -> int:
        for p in incoming.values():
            if p.name == "steam" and not p.steam_appid and p.owned:
                return p.pid
        return 0

    def game_children(self, pid: int) -> list[int]:
        node = self._nodes.get(pid)
        if node is None:
            return []
        return [c.proc.pid for c in node.children if c.proc.steam_appid]

    def _with_groups(self, incoming: dict[int, ProcSample]) -> dict[int, ProcSample]:
        """Add a synthetic sample per application with two or more processes
        and remember which group each process belongs to this tick. Group
        pids are negative and stay the same for the same key."""
        self._group_of = {}
        out = dict(incoming)
        for key, members in build_groups(list(incoming.values())).items():
            if len(members) < 2:
                continue
            gid = self._group_ids.get(key)
            if gid is None:
                gid = -(len(self._group_ids) + 1)
                self._group_ids[key] = gid
            out[gid] = summarize(gid, key, members)
            for m in members:
                self._group_of[m.pid] = gid
        return out

    def _with_sections(self, incoming: dict[int, ProcSample]) -> dict[int, ProcSample]:
        """Place every process (by cgroup, or by owner when the cgroup could not
        be read) and every group row (where most of its members are), and add
        the three section rows, each carrying its count of processes."""
        self._section_of = {}
        counts = dict.fromkeys(SECTION_PID, 0)
        self.fallbacks = 0
        members_of: dict[int, list[int]] = {}
        for pid, p in incoming.items():
            if pid <= 0:
                continue
            key, fell_back = section_of(p.cgroup, p.uid, self._uid_min)
            self._section_of[pid] = SECTION_PID[key]
            counts[key] += 1
            self.fallbacks += fell_back
            gid = self._group_of.get(pid, 0)
            if gid:
                members_of.setdefault(gid, []).append(SECTION_PID[key])
        for gid, homes in members_of.items():
            self._section_of[gid] = max(set(homes), key=homes.count)
        out = dict(incoming)
        for key, spid in SECTION_PID.items():
            out[spid] = ProcSample(pid=spid, name=LABEL[key], members=counts[key], cgroup=key)
        return out

    def section_counts(self) -> dict[str, int]:
        return {key: self._nodes[spid].proc.members for key, spid in SECTION_PID.items()
                if spid in self._nodes}

    def _index_of(self, node: Node) -> QModelIndex:
        return QModelIndex() if node is self._root else self.createIndex(node.row, 0, node)

    def _remove(self, node: Node) -> None:
        """Remove a node with its whole subtree from the structure and the view."""
        parent = node.parent
        self.beginRemoveRows(self._index_of(parent), node.row, node.row)
        del parent.children[node.row]
        parent.reindex()
        self._nodes.pop(node.proc.pid, None)
        for d in node.descendants():
            self._nodes.pop(d.proc.pid, None)
        self.endRemoveRows()

    def _insert(self, parent: Node, procs: list[ProcSample]) -> None:
        start = len(parent.children)
        self.beginInsertRows(self._index_of(parent), start, start + len(procs) - 1)
        for p in procs:
            node = Node(p, parent)
            node.row = len(parent.children)
            parent.children.append(node)
            self._nodes[p.pid] = node
        self.endInsertRows()

    def remember(self, procs: list[ProcSample]) -> None:
        """Keep the latest sample without touching the rows: the game-end
        path reads it while the list itself is not on screen."""
        self._last = procs

    def update(self, procs: list[ProcSample]) -> None:
        self._last = procs
        if self.frozen:
            return
        incoming = {p.pid: p for p in procs}
        self.steam_pid = self.find_steam(incoming)
        self.hoisted = self.find_managers(incoming)
        if self.mode == "grouped":
            incoming = self._with_groups(incoming)
        if self.sectioned:
            incoming = self._with_sections(incoming)

        # 1. Remove what is gone, and what must move (its parent changed). A
        #    removed subtree may contain processes that still exist: they are
        #    re-inserted below, under their current parent.
        doomed = []
        for pid, node in self._nodes.items():
            p = incoming.get(pid)
            if p is None:
                doomed.append(node)
                continue
            cur_parent_pid = node.parent.proc.pid if node.parent is not self._root else 0
            if cur_parent_pid != self._desired_parent_pid(p, incoming):
                doomed.append(node)
        # Deepest first so a child is never removed after its parent already went.
        depth = {}
        for node in doomed:
            d, n = 0, node
            while n.parent is not None:
                d, n = d + 1, n.parent
            depth[id(node)] = d
        for node in sorted(doomed, key=lambda n: -depth[id(n)]):
            if node.proc.pid in self._nodes:  # not already gone with an ancestor
                self._remove(node)

        # 2. Refresh the survivors' data.
        for pid, node in self._nodes.items():
            node.proc = incoming[pid]

        # 3. Insert new (and re-homed) processes, parents before children.
        pending = [p for pid, p in incoming.items() if pid not in self._nodes]
        while pending:
            by_parent: dict[int, list[ProcSample]] = {}
            later = []
            for p in pending:
                want = self._desired_parent_pid(p, incoming)
                if want == 0 or want in self._nodes:
                    by_parent.setdefault(want, []).append(p)
                else:
                    later.append(p)
            if not by_parent:  # only cycles left, which /proc cannot produce; be safe
                by_parent[0] = later
                later = []
            for parent_pid, group in by_parent.items():
                parent = self._root if parent_pid == 0 else self._nodes[parent_pid]
                self._insert(parent, group)
            pending = later

        # 4. Busy deadlines (for the programs-only filter) and subtree totals,
        #    then tell the views. Totals must exist before dataChanged fires.
        now = time.monotonic()
        for p in incoming.values():
            if is_busy(p):
                self.busy_until[p.pid] = now + BUSY_HOLD_S
        for pid in [pid for pid in self.busy_until if pid not in incoming]:
            del self.busy_until[pid]
        self._expanded &= incoming.keys()
        if self.tree:
            self._sum_totals(self._root)
        self._emit_changed(self._root)

    def _emit_changed(self, node: Node) -> None:
        if node.children:
            self.dataChanged.emit(
                self.createIndex(0, 0, node.children[0]),
                self.createIndex(len(node.children) - 1, len(HEADERS) - 1, node.children[-1]),
                [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ForegroundRole, SORT_ROLE],
            )
            for c in node.children:
                self._emit_changed(c)

    def set_mode(self, mode: str) -> None:
        """Grouped, tree or flat: a structural change, so rebuild; selection is lost once."""
        if mode not in MODES:
            raise ValueError(mode)
        if mode == self.mode:
            return
        self.mode = mode
        self._rebuild()

    def set_sections(self, on: bool) -> None:
        """Sections on or off: the root rows change, so rebuild like a mode change."""
        if on == self.sections:
            return
        self.sections = on
        self._rebuild()

    def _rebuild(self) -> None:
        self.beginResetModel()
        self._root = Node(None, None)
        self._nodes = {}
        self._expanded = set()
        self._section_of = {}
        self.endResetModel()
        if self._last:
            self.update(self._last)

    def set_normalize(self, on: bool) -> None:
        self.normalize_cpu = on
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, COL_CPU, COL_CPU)
        self._emit_changed(self._root)


class ProcFilter(QSortFilterProxyModel):
    """Filters on the process itself; in tree mode a parent stays visible when
    any descendant passes, so a game's ancestry (systemd, steam, reaper)
    remains as context.

    Default view ("programs"): your own processes that are user-facing programs
    (a visible menu entry or a Steam game) plus anything that is busy right
    now, icon or not. `show_all` lifts every one of those restrictions,
    including other users' processes and kernel threads."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSortRole(SORT_ROLE)
        self.setDynamicSortFilter(True)
        self.setRecursiveFilteringEnabled(True)
        self.text = ""
        self.show_all = False
        self.only_gpu = False
        self.category = ""   # "" = all; otherwise one of appinfo.CATEGORIES

    def set_text(self, text: str) -> None:
        self.text = text.strip().lower()
        self.invalidateFilter()

    def set_flag(self, name: str, value) -> None:
        setattr(self, name, value)
        self.invalidateFilter()

    def matches_text(self, p: ProcSample) -> bool:
        t = self.text
        return (not t or t in p.name.lower() or t in p.app_name.lower()
                or t in p.role or t in p.cmdline.lower() or t == str(p.pid))

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        # During a search a visible row is a match or an ancestor of one; the
        # ancestors are only context and step back so the matches stand out.
        if role == Qt.ItemDataRole.ForegroundRole and self.text:
            p = self.sourceModel().proc_at(self.mapToSource(index))
            if p is not None and not self.matches_text(p):
                return QColor(theme.FAINT)
        return super().data(index, role)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        # Section headers keep their order (Apps, Background, System) whatever
        # column is sorted and in whichever direction.
        model: ProcModel = self.sourceModel()
        a, b = model.proc_at(left), model.proc_at(right)
        if a is not None and b is not None and is_section(a.pid) and is_section(b.pid):
            first = RANK[KEY_OF_PID[a.pid]] < RANK[KEY_OF_PID[b.pid]]
            return first if self.sortOrder() == Qt.SortOrder.AscendingOrder else not first
        return super().lessThan(left, right)

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:
        model: ProcModel = self.sourceModel()
        p = model.proc_at(model.index(row, 0, parent))
        if p is None:
            return False
        if is_section(p.pid):
            return False   # shown through its rows (recursive filter); empty, it is hidden
        if not self.show_all:
            # A member of a group inherits the group row's verdict: opening
            # "Brave" must show all of Brave, helpers included, while a group
            # that is not yours stays hidden with all its members.
            subject = p
            if parent.isValid() and model.proc_at(parent).members:
                subject = model.proc_at(parent)
            if not subject.owned or not subject.cmdline:
                return False
            if not subject.program and model.busy_until.get(subject.pid, 0.0) < time.monotonic():
                return False
        if self.only_gpu and not (p.gpu_sm or p.gpu_mem_mb):
            return False
        if self.category and p.category != self.category:
            return False
        return self.matches_text(p)
