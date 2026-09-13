"""Table model for the process list.

Rows are not rebuilt every tick but updated in place: otherwise you lose your
selection and the table flickers on every sample.
"""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor

from ..model import ProcSample
from . import theme
from .widgets import human_bytes

SORT_ROLE = Qt.ItemDataRole.UserRole + 1
PID_ROLE = Qt.ItemDataRole.UserRole + 2

COL_PID, COL_NAME, COL_CPU, COL_MEM, COL_GPU, COL_VRAM, COL_THREADS, \
    COL_NICE, COL_IO, COL_USER, COL_STATUS, COL_CMD = range(12)

HEADERS = [
    "PID", "Name", "CPU %", "Memory", "GPU %", "VRAM", "Thr",
    "Nice", "Disk I/O", "User", "Status", "Command",
]

_RIGHT = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
_CENTER = int(Qt.AlignmentFlag.AlignCenter)
_LEFT = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

ALIGN = {
    COL_PID: _RIGHT, COL_CPU: _RIGHT, COL_MEM: _RIGHT, COL_GPU: _RIGHT,
    COL_VRAM: _RIGHT, COL_THREADS: _RIGHT, COL_NICE: _CENTER, COL_IO: _RIGHT,
    COL_STATUS: _CENTER,
}


class ProcModel(QAbstractTableModel):
    def __init__(self, ncpu: int, parent=None) -> None:
        super().__init__(parent)
        self.ncpu = ncpu
        self.normalize_cpu = False   # True = CPU% divided by number of cores
        self._rows: list[ProcSample] = []
        self._pids: dict[int, int] = {}
        self.frozen = False

    # -- Qt ---------------------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if section == COL_CPU and self.normalize_cpu:
                return "CPU % (norm)"
            return HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        p = self._rows[index.row()]
        col = index.column()

        if role == PID_ROLE:
            return p.pid
        if role == SORT_ROLE:
            return self._sort_value(p, col)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return ALIGN.get(col, _LEFT)
        if role == Qt.ItemDataRole.ForegroundRole:
            return self._color(p, col)
        if role == Qt.ItemDataRole.ToolTipRole:
            return p.cmdline or p.name
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return self._text(p, col)

    # -- content ----------------------------------------------------------
    def _cpu(self, p: ProcSample) -> float:
        return p.cpu_percent / self.ncpu if self.normalize_cpu else p.cpu_percent

    def _text(self, p: ProcSample, col: int):
        if col == COL_PID:
            return str(p.pid)
        if col == COL_NAME:
            return p.name
        if col == COL_CPU:
            v = self._cpu(p)
            return f"{v:.1f}" if v >= 0.05 else "·"
        if col == COL_MEM:
            return human_bytes(p.mem_rss)
        if col == COL_GPU:
            return f"{p.gpu_sm:.0f}" if p.gpu_sm else ("·" if p.gpu_mem_mb else "")
        if col == COL_VRAM:
            return f"{p.gpu_mem_mb:.0f} MB" if p.gpu_mem_mb else ""
        if col == COL_THREADS:
            return str(p.num_threads)
        if col == COL_NICE:
            return str(p.nice)
        if col == COL_IO:
            total = p.io_read_bps + p.io_write_bps
            return f"{human_bytes(total)}/s" if total > 1024 else ""
        if col == COL_USER:
            return p.username
        if col == COL_STATUS:
            return p.status
        if col == COL_CMD:
            return p.cmdline
        return None

    def _sort_value(self, p: ProcSample, col: int):
        return {
            COL_PID: p.pid, COL_NAME: p.name.lower(), COL_CPU: p.cpu_percent,
            COL_MEM: p.mem_rss, COL_GPU: p.gpu_sm, COL_VRAM: p.gpu_mem_mb,
            COL_THREADS: p.num_threads, COL_NICE: p.nice,
            COL_IO: p.io_read_bps + p.io_write_bps, COL_USER: p.username,
            COL_STATUS: p.status, COL_CMD: p.cmdline.lower(),
        }.get(col, "")

    def _color(self, p: ProcSample, col: int):
        if p.status == "stopped":
            return QColor(theme.WARN)
        if col == COL_CPU:
            v = self._cpu(p)
            if v >= 50:
                return QColor(theme.CRIT if v >= 85 else theme.WARN)
            if v < 0.05:
                return QColor(theme.MUTED)
        elif col == COL_GPU and p.gpu_sm >= 20:
            return QColor(theme.GPU)
        elif col in (COL_VRAM, COL_CMD, COL_USER, COL_STATUS):
            return QColor(theme.MUTED)
        elif col == COL_NICE and p.nice != 0:
            # yellow = stands out (higher priority), green = neatly tucked away
            return QColor(theme.OK if p.nice > 0 else theme.ACCENT)
        return None

    # -- updates ----------------------------------------------------------
    def update(self, procs: list[ProcSample]) -> None:
        if self.frozen:
            return
        incoming = {p.pid: p for p in procs}
        gone = [pid for pid in self._pids if pid not in incoming]
        if gone:
            for pid in sorted(gone, key=lambda x: self._pids[x], reverse=True):
                row = self._pids[pid]
                self.beginRemoveRows(QModelIndex(), row, row)
                del self._rows[row]
                self.endRemoveRows()
            self._reindex()

        for pid, row in self._pids.items():
            self._rows[row] = incoming[pid]
        if self._rows:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._rows) - 1, len(HEADERS) - 1),
                [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ForegroundRole, SORT_ROLE],
            )

        added = [p for pid, p in incoming.items() if pid not in self._pids]
        if added:
            start = len(self._rows)
            self.beginInsertRows(QModelIndex(), start, start + len(added) - 1)
            self._rows.extend(added)
            self.endInsertRows()
            self._reindex()

    def _reindex(self) -> None:
        self._pids = {p.pid: i for i, p in enumerate(self._rows)}

    def proc_at(self, row: int) -> ProcSample | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def set_normalize(self, on: bool) -> None:
        self.normalize_cpu = on
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, COL_CPU, COL_CPU)
        if self._rows:
            self.dataChanged.emit(self.index(0, COL_CPU),
                                  self.index(len(self._rows) - 1, COL_CPU))


class ProcFilter(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSortRole(SORT_ROLE)
        self.setDynamicSortFilter(True)
        self.text = ""
        self.only_mine = True
        self.hide_kernel = True
        self.only_gpu = False
        self.min_cpu = 0.0

    def set_text(self, text: str) -> None:
        self.text = text.strip().lower()
        self.invalidateFilter()

    def set_flag(self, name: str, value) -> None:
        setattr(self, name, value)
        self.invalidateFilter()

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:
        model: ProcModel = self.sourceModel()
        p = model.proc_at(row)
        if p is None:
            return False
        if self.only_mine and not p.owned:
            return False
        if self.hide_kernel and not p.cmdline:
            return False
        if self.only_gpu and not (p.gpu_sm or p.gpu_mem_mb):
            return False
        if self.min_cpu and p.cpu_percent < self.min_cpu:
            return False
        if self.text:
            t = self.text
            if t not in p.name.lower() and t not in p.cmdline.lower() and t != str(p.pid):
                return False
        return True
