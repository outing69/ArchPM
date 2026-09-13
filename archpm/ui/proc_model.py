"""Item model for the process list: a tree by parent pid, or flat.

Rows are updated in place every tick instead of rebuilt: a rebuild would drop
the selection and the expanded/collapsed state and make the view flicker.
Processes that appear are inserted under their parent (or at the top level
when the parent is not in the snapshot), processes that vanish are removed
with their subtree, and a process whose parent changed (the parent died and
init or a subreaper adopted it) is removed and re-inserted under the new one.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor

from ..appinfo import describe
from ..model import ProcSample
from . import theme
from .widgets import app_icon, human_bytes

SORT_ROLE = Qt.ItemDataRole.UserRole + 1
PID_ROLE = Qt.ItemDataRole.UserRole + 2

COL_PID, COL_NAME, COL_CPU, COL_MEM, COL_GPU, COL_VRAM, COL_THREADS, \
    COL_NICE, COL_IO, COL_USER, COL_STATUS, COL_STARTED, COL_CATEGORY, COL_CMD = range(14)

HEADERS = [
    "PID", "Name", "CPU %", "Memory", "GPU %", "VRAM", "Thr",
    "Nice", "Disk I/O", "User", "Status", "Started", "Category", "Command",
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
        self.tree = True
        self._root = Node(None, None)
        self._nodes: dict[int, Node] = {}
        self._last: list[ProcSample] = []
        self.busy_until: dict[int, float] = {}   # pid -> monotonic deadline
        self._expanded: set[int] = set()         # pids whose row the view shows expanded

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
        if role == Qt.ItemDataRole.DecorationRole:
            if col == COL_NAME and p.icon:
                icon = app_icon(p.icon)
                return None if icon.isNull() else icon
            return None
        if role == Qt.ItemDataRole.ToolTipRole:
            if totals and col in _SUMMED:
                return f"Total of {totals.count} processes in this tree"
            if col == COL_NAME:
                exe = p.cmdline.split(" ", 1)[0] if p.cmdline else p.name
                about = describe(exe) or describe(p.name)
                lines = [about] if about else []
                if p.app_name:
                    lines.append(p.name)
                if p.cmdline:
                    lines.append(p.cmdline)
                return "\n".join(lines) or p.name
            return p.cmdline or p.name
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return self._text(p, col, totals)

    # -- content ------------------------------------------------------------
    def _cpu(self, p: ProcSample) -> float:
        return p.cpu_percent / self.ncpu if self.normalize_cpu else p.cpu_percent

    def _text(self, p: ProcSample, col: int, t: Totals | None = None):
        cpu = t.cpu if t else p.cpu_percent
        rss = t.rss if t else p.mem_rss
        gpu_sm = t.gpu_sm if t else p.gpu_sm
        gpu_mem = t.gpu_mem if t else p.gpu_mem_mb
        threads = t.threads if t else p.num_threads
        io = t.io if t else p.io_read_bps + p.io_write_bps
        if col == COL_PID:
            return str(p.pid)
        if col == COL_NAME:
            return p.display_name
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
        """The process and all its descendants, deepest first (children before parents)."""
        node = self._nodes.get(pid)
        if node is None:
            return [pid]
        out = [d.proc.pid for d in node.descendants()]
        out.reverse()
        out.append(pid)
        return out

    def pids(self):
        return self._nodes.keys()

    def has_children(self, pid: int) -> bool:
        node = self._nodes.get(pid)
        return bool(node and node.children)

    # -- updates --------------------------------------------------------------
    def _parent_for(self, p: ProcSample, incoming: dict[int, ProcSample]) -> Node:
        if self.tree and p.ppid in incoming and p.ppid != p.pid:
            node = self._nodes.get(p.ppid)
            if node is not None:
                return node
        return self._root

    def _desired_parent_pid(self, p: ProcSample, incoming: dict[int, ProcSample]) -> int:
        if self.tree and p.ppid in incoming and p.ppid != p.pid:
            return p.ppid
        return 0

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

    def update(self, procs: list[ProcSample]) -> None:
        self._last = procs
        if self.frozen:
            return
        incoming = {p.pid: p for p in procs}

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
        for p in procs:
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

    def set_tree(self, on: bool) -> None:
        """Flat <-> tree is a structural change, so rebuild; selection is lost once."""
        if on == self.tree:
            return
        self.beginResetModel()
        self.tree = on
        self._root = Node(None, None)
        self._nodes = {}
        self._expanded = set()
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

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:
        model: ProcModel = self.sourceModel()
        p = model.proc_at(model.index(row, 0, parent))
        if p is None:
            return False
        if not self.show_all:
            if not p.owned or not p.cmdline:
                return False
            if not p.program and model.busy_until.get(p.pid, 0.0) < time.monotonic():
                return False
        if self.only_gpu and not (p.gpu_sm or p.gpu_mem_mb):
            return False
        if self.category and p.category != self.category:
            return False
        if self.text:
            t = self.text
            if (t not in p.name.lower() and t not in p.app_name.lower()
                    and t not in p.cmdline.lower() and t != str(p.pid)):
                return False
        return True
