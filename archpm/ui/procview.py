"""The process list with every action you can take without root."""
from __future__ import annotations

import signal
import time

import psutil
from PySide6.QtCore import QModelIndex, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ..actions import ActionError, UserBackend
from ..appinfo import CATEGORIES
from ..model import ProcSample
from . import theme
from .history import ProcHistory
from .proc_model import (
    COL_CATEGORY,
    COL_CMD,
    COL_CPU,
    COL_GPU,
    COL_IO,
    COL_MEM,
    COL_NAME,
    COL_NICE,
    COL_PID,
    COL_STARTED,
    COL_STATUS,
    COL_THREADS,
    COL_USER,
    COL_VRAM,
    PID_ROLE,
    ProcFilter,
    ProcModel,
    age_text,
)
from .widgets import Graph, app_icon, human_bytes, mono

NICE_PRESETS = [
    ("Game priority (nice -10)", -10),
    ("High (nice -5)", -5),
    ("Normal (nice 0)", 0),
    ("Low (nice 10)", 10),
    ("Background (nice 19)", 19),
]


class AffinityDialog(QDialog):
    """Pin a process to cores. Handy to keep a game away from core 0."""

    def __init__(self, proc: ProcSample, current: list[int], ncpu: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"CPU affinity — {proc.display_name} ({proc.pid})")
        self.ncpu = ncpu
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(QLabel(
            f"Which logical cores may <b>{proc.display_name}</b> run on?<br>"
            f"<span style='color:{theme.MUTED}'>Even numbers are usually physical "
            f"cores, odd ones the SMT siblings.</span>"
        ))

        grid = QGridLayout()
        grid.setSpacing(6)
        self.boxes: list[QCheckBox] = []
        for i in range(ncpu):
            cb = QCheckBox(str(i))
            cb.setChecked(i in current)
            self.boxes.append(cb)
            grid.addWidget(cb, i // 8, i % 8)
        lay.addLayout(grid)

        presets = QHBoxLayout()
        for label, fn in (
            ("All", lambda: list(range(ncpu))),
            ("Physical only", lambda: list(range(0, ncpu, 2))),
            ("First half", lambda: list(range(ncpu // 2))),
            ("Second half", lambda: list(range(ncpu // 2, ncpu))),
        ):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _=False, f=fn: self._apply_preset(f()))
            presets.addWidget(btn)
        presets.addStretch(1)
        lay.addLayout(presets)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _apply_preset(self, cores: list[int]) -> None:
        for i, cb in enumerate(self.boxes):
            cb.setChecked(i in cores)

    def selection(self) -> list[int]:
        return [i for i, cb in enumerate(self.boxes) if cb.isChecked()]


class HistoryPanel(QWidget):
    """The last minutes of one process (or a collapsed program's whole tree)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(6)
        head = QHBoxLayout()
        self.lbl_icon = QLabel()
        self.lbl_icon.setFixedSize(18, 18)
        head.addWidget(self.lbl_icon)
        self.lbl = QLabel("Select a process to see its last minutes")
        self.lbl.setFont(mono(9, bold=True))
        self.lbl.setTextFormat(Qt.TextFormat.RichText)
        head.addWidget(self.lbl, 1)
        lay.addLayout(head)
        graphs = QHBoxLayout()
        graphs.setSpacing(10)
        self.g_cpu = Graph([("CPU", theme.CPU), ("GPU", theme.GPU)], maximum=None, fill=False)
        self.g_mem = Graph([("Memory", theme.MEM)], maximum=None, fill=True)
        self.g_mem.set_formatter(human_bytes)
        for g in (self.g_cpu, self.g_mem):
            g.setMinimumHeight(140)
            graphs.addWidget(g, 1)
        lay.addLayout(graphs)

    def show_track(self, p: ProcSample, track, tree_size: int,
                   ended_ago: float | None = None) -> None:
        scope = f"Whole tree, {tree_size} processes" if tree_size > 1 else f"PID {p.pid}"
        if ended_ago is not None:
            when = "just now" if ended_ago < 10 else f"{age_text(ended_ago)} ago"
            scope += (f"&nbsp;&nbsp;·&nbsp;&nbsp;"
                      f"<span style='color:{theme.WARN}'>Ended {when}</span>")
        sep = "&nbsp;&nbsp;·&nbsp;&nbsp;"
        self.lbl.setText(f"<span style='color:{theme.ACCENT}'>{p.display_name}</span>"
                         f"<span style='color:{theme.FAINT}'>{sep}{scope}</span>")
        icon = app_icon(p.icon)
        self.lbl_icon.setPixmap(icon.pixmap(16, 16) if not icon.isNull() else QPixmap())
        self.g_cpu.set_history(track.cpu, track.gpu)
        self.g_mem.set_history(track.rss)


class ProcessView(QWidget):
    status = Signal(str)

    def __init__(self, ncpu: int, backend: UserBackend, history: ProcHistory | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.ncpu = ncpu
        self.backend = backend
        self.history = history
        # The process whose history is shown, kept when its row disappears:
        # after a kill you want to see what it was doing, not whatever row Qt
        # happens to make current next.
        self._pinned: tuple[ProcSample, list[int]] | None = None
        self._frozen = False
        self.settings = QSettings("archpm", "ArchPM")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(8)

        # -- toolbar -------------------------------------------------------
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by name, command or PID…   (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(240)
        bar.addWidget(self.search, 2)

        self.combo_category = QComboBox()
        self.combo_category.addItem("All categories", "")
        for c in CATEGORIES:
            self.combo_category.addItem(c, c)
        self.combo_category.setToolTip("Only programs of one kind, from their menu entry; "
                                       "Steam games are Game.")
        bar.addWidget(self.combo_category)

        self.cb_tree = QCheckBox("Tree")
        self.cb_tree.setChecked(self.settings.value("tree", True, type=bool))
        self.cb_tree.setToolTip("Nest processes under their parent (Steam → reaper → game).")
        self.cb_all = QCheckBox("Show all processes")
        self.cb_all.setChecked(self.settings.value("show_all", False, type=bool))
        self.cb_all.setToolTip(
            "Off: your programs (anything with a name and icon) plus whatever is busy.\n"
            "On: every process, including other users' and kernel threads."
        )
        self.cb_gpu = QCheckBox("GPU only")
        self.cb_norm = QCheckBox("CPU% ÷ cores")
        self.cb_norm.setToolTip(
            "Off: 100% = one core fully used (like top).\nOn: 100% = all cores fully used."
        )
        self.cb_freeze = QCheckBox("Pause list")
        self.cb_freeze.setToolTip("Freezes the list so rows stop jumping around.")
        for cb in (self.cb_tree, self.cb_all, self.cb_gpu, self.cb_norm, self.cb_freeze):
            bar.addWidget(cb)
        bar.addStretch(1)

        self.btn_kill = QPushButton("Terminate")
        self.btn_kill.setObjectName("danger")
        self.btn_kill.clicked.connect(lambda: self._signal_selected(signal.SIGTERM))
        bar.addWidget(self.btn_kill)
        outer.addLayout(bar)

        # -- tree ----------------------------------------------------------
        self.model = ProcModel(ncpu, self)
        self.model.tree = self.cb_tree.isChecked()
        # Connected before the proxy sees the model: Qt calls slots in
        # connection order, and the proxy would otherwise move the view's
        # current row (and re-pin the history) before we notice the removal.
        self.model.rowsAboutToBeRemoved.connect(self._rows_going)
        self.proxy = ProcFilter(self)
        self.proxy.show_all = self.cb_all.isChecked()
        self.proxy.setSourceModel(self.model)
        self.table = QTreeView()
        # Breeze paints its own frame over the app-wide rule; state the border here.
        self.table.setStyleSheet(
            f"QTreeView {{ border: 1px solid {theme.BORDER}; border-radius: 10px; }}"
        )
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        # Sorted by name by default: sorting on a live value (CPU%) makes rows
        # trade places every tick, which is unbearable in a tree. The last
        # chosen sort is remembered.
        col = self.settings.value("sort_column", COL_NAME, type=int)
        order = self.settings.value("sort_order", Qt.SortOrder.AscendingOrder.value, type=int)
        self.table.sortByColumn(col, Qt.SortOrder(order))
        self.table.setAlternatingRowColors(True)
        self.table.setUniformRowHeights(True)   # required for fast layout of ~500 rows
        self.table.setIndentation(16)
        self.table.setIconSize(QSize(16, 16))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        header = self.table.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_CMD, QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(True)
        header.setHighlightSections(False)
        # Draw the tree (arrows, indentation) in the Name column and show that
        # column first; PID stays a plain narrow column.
        self.table.setTreePosition(COL_NAME)
        header.moveSection(COL_NAME, 0)
        # Without explicit widths the middle columns swallow everything and
        # nothing is left for the command.
        for col, w in (
            (COL_PID, 64), (COL_NAME, 280), (COL_CPU, 74), (COL_MEM, 86),
            (COL_GPU, 58), (COL_VRAM, 74), (COL_THREADS, 46), (COL_NICE, 48),
            (COL_IO, 84), (COL_USER, 78), (COL_STATUS, 74), (COL_STARTED, 76),
            (COL_CATEGORY, 104),
        ):
            self.table.setColumnWidth(col, w)
        # History under the tree: shows once something is selected; the
        # splitter lets the user give it more or less room.
        self.split = QSplitter(Qt.Orientation.Vertical)
        self.split.setChildrenCollapsible(False)
        self.split.addWidget(self.table)
        self.panel = HistoryPanel()
        self.panel.setVisible(False)
        self.split.addWidget(self.panel)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 1)
        self.panel.setMinimumHeight(190)
        outer.addWidget(self.split, 1)
        self.table.selectionModel().currentRowChanged.connect(self._current_changed)
        self.table.pressed.connect(lambda _: self._unfreeze())

        # Collapsed by default, or a browser's twenty renderers bury everything.
        # The one exception, applied once per process the first time it is
        # seen (so what you collapse stays collapsed): the top two levels, init
        # and your session, which is where your programs live. Done after each
        # update rather than on rowsInserted: the proxy maps deeper rows lazily
        # and emits nothing for them until the view looks.
        self._auto_done: set[int] = set()
        self._games_seen: set[int] = set()   # game roots already used to open Steam
        self.proxy.modelReset.connect(self._auto_done.clear)
        self.proxy.modelReset.connect(self._games_seen.clear)

        # -- behaviour -----------------------------------------------------
        header.sortIndicatorChanged.connect(self._remember_sort)
        self.search.textChanged.connect(self.proxy.set_text)
        self.cb_tree.toggled.connect(self._set_tree)
        self.cb_all.toggled.connect(self._set_show_all)
        self.combo_category.currentIndexChanged.connect(
            lambda i: self.proxy.set_flag("category", self.combo_category.itemData(i))
        )
        self.cb_gpu.toggled.connect(lambda v: self.proxy.set_flag("only_gpu", v))
        # A collapsed program row shows the totals of its tree; the model needs
        # to know which rows are open to decide that.
        self.table.expanded.connect(lambda i: self.model.set_expanded(i.data(PID_ROLE), True))
        self.table.collapsed.connect(lambda i: self.model.set_expanded(i.data(PID_ROLE), False))
        self.cb_norm.toggled.connect(self.model.set_normalize)
        self.cb_freeze.toggled.connect(self._set_frozen)

        act_find = QAction(self)
        act_find.setShortcut(QKeySequence.StandardKey.Find)
        act_find.triggered.connect(self.search.setFocus)
        self.addAction(act_find)
        act_term = QAction(self)
        act_term.setShortcut(QKeySequence(Qt.Key.Key_Delete))
        act_term.triggered.connect(lambda: self._signal_selected(signal.SIGTERM))
        self.table.addAction(act_term)
        act_kill = QAction(self)
        act_kill.setShortcut(QKeySequence("Shift+Del"))
        act_kill.triggered.connect(lambda: self._signal_selected(signal.SIGKILL))
        self.table.addAction(act_kill)

    # -- data -------------------------------------------------------------
    def set_backend(self, backend) -> None:
        """Switches between the regular and the root backend without rebuilding the UI."""
        self.backend = backend

    def update_view(self, snap) -> None:
        self.model.update(snap.procs)
        if self.model.tree and not self.model.frozen:
            self._auto_expand()
        if self.panel.isVisible():
            self._show_history()

    def _current_changed(self, *_) -> None:
        if self._frozen:
            # Qt moved "current" because the pinned row vanished; keep the panel
            # on the killed process and leave nothing looking selected.
            QTimer.singleShot(0, self.table.clearSelection)
            return
        self._show_history()

    def _unfreeze(self) -> None:
        self._frozen = False

    def _rows_going(self, parent: QModelIndex, first: int, last: int) -> None:
        if self._pinned is None or self._frozen:
            return
        pinned_pid = self._pinned[0].pid
        for row in range(first, last + 1):
            idx = self.model.index(row, 0, parent)
            if pinned_pid in self.model.subtree_pids(idx.data(PID_ROLE)):
                self._frozen = True
                return

    def _show_history(self) -> None:
        if self.history is None:
            return
        if self._frozen and self._pinned is not None:
            p, pids = self._pinned
            ended = self.history.ended_at(p.pid)
            ago = (time.monotonic() - ended) if ended is not None else None
            self.panel.show_track(p, self.history.tree(pids), len(pids), ago)
            return
        idx = self.table.selectionModel().currentIndex()
        p = self.model.proc_at(self.proxy.mapToSource(idx)) if idx.isValid() else None
        if p is None:
            self._pinned = None
            self.panel.setVisible(False)
            return
        # A collapsed program row stands for its tree; so does its history.
        pids = [p.pid]
        if self.model.tree and self.model.has_children(p.pid) and not self.model.is_expanded(p.pid):
            pids = self.model.subtree_pids(p.pid)
        self._pinned = (p, pids)
        self.panel.show_track(p, self.history.tree(pids), len(pids))
        if not self.panel.isVisible():
            self.panel.setVisible(True)

    def _set_frozen(self, frozen: bool) -> None:
        self.model.frozen = frozen
        self.proxy.setDynamicSortFilter(not frozen)

    def _set_show_all(self, on: bool) -> None:
        self.settings.setValue("show_all", on)
        self.proxy.set_flag("show_all", on)

    def _remember_sort(self, column: int, order: Qt.SortOrder) -> None:
        self.settings.setValue("sort_column", column)
        self.settings.setValue("sort_order", order.value)

    def _set_tree(self, on: bool) -> None:
        self.settings.setValue("tree", on)
        self.model.set_tree(on)
        self.table.setRootIsDecorated(on)

    def _auto_expand(self) -> None:
        """Apply the default-expansion rule to rows not seen before (see __init__)."""
        alive = set(self.model.pids())
        self._auto_done &= alive
        pending = [(QModelIndex(), 0)]
        while pending:
            parent, depth = pending.pop()
            for row in range(self.proxy.rowCount(parent)):
                index = self.proxy.index(row, 0, parent)
                children = self.proxy.rowCount(index)
                if children:
                    pending.append((index, depth + 1))
                    pid = index.data(PID_ROLE)
                    if pid not in self._auto_done:
                        if depth <= 1:
                            self.table.expand(index)
                        self._auto_done.add(pid)
                    # Steam opens when a new game shows up under it, so the
                    # game is one row below Steam without digging.
                    if pid == self.model.steam_pid:
                        new_games = set(self.model.game_children(pid)) - self._games_seen
                        if new_games:
                            self._games_seen |= new_games
                            self.table.expand(index)
                            for ancestor in (index.parent(), index.parent().parent()):
                                if ancestor.isValid():
                                    self.table.expand(ancestor)

    # -- selection --------------------------------------------------------
    def _selected(self) -> list[ProcSample]:
        out = []
        for idx in self.table.selectionModel().selectedRows():
            p = self.model.proc_at(self.proxy.mapToSource(idx))
            if p is not None:
                out.append(p)
        return out

    def _selected_trees(self) -> list[ProcSample]:
        """Selected processes plus every descendant, children first, no duplicates."""
        by_pid = {p.pid: p for p in self.model._last}
        seen: set[int] = set()
        out: list[ProcSample] = []
        for p in self._selected():
            for pid in self.model.subtree_pids(p.pid):
                if pid not in seen and pid in by_pid:
                    seen.add(pid)
                    out.append(by_pid[pid])
        return out

    # -- context menu -----------------------------------------------------
    def _menu(self, pos) -> None:
        procs = self._selected()
        if not procs:
            return
        one = procs[0] if len(procs) == 1 else None
        title = one.display_name if one else f"{len(procs)} processes"
        menu = QMenu(self)
        header = menu.addAction(f"{title}" + (f"  ·  pid {one.pid}" if one else ""))
        header.setEnabled(False)
        menu.addSeparator()

        menu.addAction("Terminate  (SIGTERM)",
                       lambda: self._signal_selected(signal.SIGTERM))
        menu.addAction("Force kill  (SIGKILL)",
                       lambda: self._signal_selected(signal.SIGKILL, confirm=True))
        if self.model.tree and any(self.model.has_children(p.pid) for p in procs):
            n = len(self._selected_trees())
            menu.addAction(f"Terminate with children  ({n} processes)",
                           lambda: self._signal_selected(signal.SIGTERM, tree=True))
            menu.addAction(f"Force kill with children  ({n} processes)",
                           lambda: self._signal_selected(signal.SIGKILL, confirm=True, tree=True))
        if one and one.status == "stopped":
            menu.addAction("Resume  (SIGCONT)",
                           lambda: self._signal_selected(signal.SIGCONT))
        else:
            menu.addAction("Suspend  (SIGSTOP)",
                           lambda: self._signal_selected(signal.SIGSTOP))
        menu.addSeparator()

        prio = menu.addMenu("Priority")
        for label, value in NICE_PRESETS:
            act = prio.addAction(label, lambda _=False, v=value: self._set_nice(v))
            if one and one.nice == value:
                act.setCheckable(True)
                act.setChecked(True)
        io = menu.addMenu("Disk priority")
        io.addAction("Normal", lambda: self._set_ionice(psutil.IOPRIO_CLASS_BE, 4))
        io.addAction("Low", lambda: self._set_ionice(psutil.IOPRIO_CLASS_BE, 7))
        io.addAction("Idle only", lambda: self._set_ionice(psutil.IOPRIO_CLASS_IDLE))

        if one:
            menu.addAction("CPU affinity…", lambda: self._affinity(one))
        menu.addSeparator()
        copy = menu.addMenu("Copy")
        copy.addAction("PID", lambda: self._copy(" ".join(str(p.pid) for p in procs)))
        copy.addAction("Name", lambda: self._copy(" ".join(p.name for p in procs)))
        if one:
            copy.addAction("Command line", lambda: self._copy(one.cmdline))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # -- actions ----------------------------------------------------------
    def _run(self, fn, procs: list[ProcSample], verb: str) -> None:
        done, errors = 0, []
        for p in procs:
            try:
                fn(p)
                done += 1
            except ActionError as exc:
                errors.append(f"{p.display_name} ({p.pid}): {exc}")
        if done:
            self.status.emit(f"{verb}: {done} process(es)")
        if errors:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Failed")
            box.setText(f"{len(errors)} of {len(procs)} not carried out.")
            box.setDetailedText("\n".join(errors))
            box.exec()

    def _signal_selected(self, sig: signal.Signals, confirm: bool = False,
                         tree: bool = False) -> None:
        procs = self._selected_trees() if tree else self._selected()
        if not procs:
            return
        if confirm:
            names = ", ".join(f"{p.display_name} ({p.pid})" for p in procs[:6])
            extra = "" if len(procs) <= 6 else f" and {len(procs) - 6} more"
            answer = QMessageBox.question(
                self, "Force kill",
                f"Send SIGKILL to {names}{extra}?\n\n"
                "The process gets no chance to clean up — unsaved work is lost.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._run(lambda p: self.backend.send_signal(p.pid, sig), procs, sig.name)

    def _set_nice(self, value: int) -> None:
        self._run(lambda p: self.backend.set_nice(p.pid, value),
                  self._selected(), f"nice {value}")

    def _set_ionice(self, klass, value: int = 4) -> None:
        self._run(lambda p: self.backend.set_ionice(p.pid, klass, value),
                  self._selected(), "disk priority")

    def _affinity(self, proc: ProcSample) -> None:
        current = self.backend.get_affinity(proc.pid) or list(range(self.ncpu))
        dlg = AffinityDialog(proc, current, self.ncpu, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._run(lambda p: self.backend.set_affinity(p.pid, dlg.selection()),
                  [proc], "affinity")

    @staticmethod
    def _copy(text: str) -> None:
        QGuiApplication.clipboard().setText(text)
