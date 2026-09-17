"""The process list with every action you can take without root."""
from __future__ import annotations

import signal
import time

import psutil
from PySide6.QtCore import (
    QItemSelectionModel,
    QModelIndex,
    QSettings,
    QSize,
    Qt,
    QTimer,
    Signal,
)
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

from .. import signalguard
from ..actions import ActionError, UserBackend
from ..appinfo import CATEGORIES
from ..model import ProcSample
from ..sections import KEY_OF_PID, SECTION_PID, is_section
from . import hints, theme
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
    HEADERS,
    HINT_KEYS,
    PID_ROLE,
    ProcFilter,
    ProcModel,
    age_text,
)
from .widgets import FlowLayout, Graph, app_icon, human_bytes, mono

WATCH_S = 5.0     # after a Terminate: this long before the toast offers to force it
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
        self.setWindowTitle(f"CPU affinity: {proc.display_name} ({proc.pid})")
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
        self.lbl.setFont(mono("body", bold=True))
        self.lbl.setTextFormat(Qt.TextFormat.RichText)
        head.addWidget(self.lbl, 1)
        lay.addLayout(head)
        graphs = QHBoxLayout()
        graphs.setSpacing(theme.CARD_GAP)
        self.g_cpu = Graph([("CPU", "CPU"), ("GPU", "GPU")], maximum=None, fill=False)
        self.g_mem = Graph([("Memory", "MEM")], maximum=None, fill=True)
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
    help_requested = Signal(str)
    # a message with one button: (text, button label, what the button does)
    offer = Signal(str, str, object)

    def __init__(self, ncpu: int, backend: UserBackend, history: ProcHistory | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.ncpu = ncpu
        self.backend = backend
        self._watches: list[dict] = []     # see watch()
        self.history = history
        # The process whose history is shown, kept when its row disappears:
        # after a kill you want to see what it was doing, not whatever row Qt
        # happens to make current next.
        self._pinned: tuple[ProcSample, list[int]] | None = None
        self._pending = None          # newest snapshot received while hidden
        self._frozen = False
        self.settings = QSettings("archpm", "ArchPM")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(*theme.page_margins())
        outer.setSpacing(theme.CARD_GAP)

        # -- toolbar: one row when it fits, wrapped when the window is narrow
        bar = FlowLayout(spacing=10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by name, command or PID…   (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(240)
        bar.addWidget(self.search)

        self.combo_category = QComboBox()
        self.combo_category.addItem("All categories", "")
        for c in CATEGORIES:
            self.combo_category.addItem(c, c)
        self.combo_category.setToolTip("Only programs of one kind, from their menu entry; "
                                       "Steam games are Game.")
        bar.addWidget(self.combo_category)

        self.combo_mode = QComboBox()
        for label, mode in (("Grouped", "grouped"), ("Tree", "tree"), ("Flat", "flat")):
            self.combo_mode.addItem(label, mode)
        self.combo_mode.setToolTip(
            "Grouped: one row per application, open it for its processes.\n"
            "Tree: every process under its parent (Steam → reaper → game).\n"
            "Flat: one row per process."
        )
        saved = self.settings.value("view_mode", "grouped", type=str)
        self.combo_mode.setCurrentIndex(max(self.combo_mode.findData(saved), 0))
        self.cb_all = QCheckBox("Show all processes")
        self.cb_all.setChecked(self.settings.value("show_all", False, type=bool))
        self.cb_all.setToolTip(
            "Off: your programs (anything with a name and icon) plus whatever is busy.\n"
            "On: every process, including other users' and kernel threads, in three "
            "sections: Apps, Background processes, System processes (Grouped and Flat)."
        )
        self.cb_gpu = QCheckBox("GPU only")
        self.cb_norm = QCheckBox("CPU% ÷ cores")
        self.cb_norm.setToolTip(
            "Off: 100% = one core fully used (like top).\nOn: 100% = all cores fully used."
        )
        self.cb_freeze = QCheckBox("Pause list")
        self.cb_freeze.setToolTip("Freezes the list so rows stop jumping around.")
        bar.addWidget(self.combo_mode)
        for cb in (self.cb_all, self.cb_gpu, self.cb_norm, self.cb_freeze):
            bar.addWidget(cb)
        bar.addStretch(1)

        self.btn_kill = QPushButton("Terminate")
        self.btn_kill.setObjectName("danger")
        self.btn_kill.clicked.connect(lambda: self._signal_selected(signal.SIGTERM))
        bar.addWidget(self.btn_kill)
        outer.addLayout(bar)

        # -- tree ----------------------------------------------------------
        self.model = ProcModel(ncpu, self)
        self.model.mode = self.combo_mode.currentData()
        self.model.sections = self.cb_all.isChecked()
        remembered = self.settings.value("collapsed_sections", "", type=str)
        self._collapsed_sections = {k for k in remembered.split(",") if k in SECTION_PID}
        # Connected before the proxy sees the model: Qt calls slots in
        # connection order, and the proxy would otherwise move the view's
        # current row (and re-pin the history) before we notice the removal.
        self.model.rowsAboutToBeRemoved.connect(self._rows_going)
        self.proxy = ProcFilter(self)
        self.proxy.show_all = self.cb_all.isChecked()
        self.proxy.setSourceModel(self.model)
        self.table = QTreeView()
        # Breeze paints its own frame over the app-wide rule; state the border here.
        theme.style(self.table, "QTreeView {{ border: 1px solid {BORDER};"
                                " border-radius: {RADIUS_CARD}px; }}"
        )
        self.table.setModel(self.proxy)
        self.table.setRootIsDecorated(self.model.hierarchical or self.model.sectioned)
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
        # Right-click on a header: explain the column in Help, or tick columns
        # on and off. Nice, User and Status are off by default: they answer
        # questions a beginner does not ask yet.
        hints.attach_header(
            header, HINT_KEYS, self.help_requested.emit, names=HEADERS,
            hideable=(COL_PID, COL_GPU, COL_VRAM, COL_THREADS, COL_NICE, COL_IO, COL_USER,
                      COL_STATUS, COL_STARTED, COL_CATEGORY, COL_CMD),
            settings=self.settings, default_hidden=(COL_NICE, COL_USER, COL_STATUS),
        )
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
        # The programs sit at the root (the model hoists them out from under
        # pid 1 and your systemd --user), so there is nothing to open on
        # startup. The one exception is Steam when a new game appears under it.
        self._games_seen: set[int] = set()   # game roots already used to open Steam
        self._expanded_before_search: set[int] | None = None
        self.proxy.modelReset.connect(self._games_seen.clear)

        # -- behaviour -----------------------------------------------------
        header.sortIndicatorChanged.connect(self._remember_sort)
        self.search.textChanged.connect(self._search_changed)
        self.combo_mode.currentIndexChanged.connect(self._set_mode)
        self.cb_all.toggled.connect(self._set_show_all)
        self.combo_category.currentIndexChanged.connect(
            lambda i: self.proxy.set_flag("category", self.combo_category.itemData(i))
        )
        self.cb_gpu.toggled.connect(lambda v: self.proxy.set_flag("only_gpu", v))
        # A collapsed program row shows the totals of its tree; the model needs
        # to know which rows are open to decide that.
        self.table.expanded.connect(lambda i: self._folded(i.data(PID_ROLE), True))
        self.table.collapsed.connect(lambda i: self._folded(i.data(PID_ROLE), False))
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
        if self.isHidden():
            self._check_watches(snap)
            # Another page is on screen. Updating the model and re-sorting the
            # proxy costs 8 ms per tick in the default view and 28 ms with
            # every process shown (measured), for rows nobody sees. Keep the
            # sample and apply it the moment the page comes back.
            self._pending = snap
            self.model.remember(snap.procs)
            return
        self._check_watches(snap)
        self._pending = None
        self.model.update(snap.procs)
        self._expand_sections()
        if self.model.hierarchical and not self.model.frozen:
            if self.model.tree:
                self._auto_expand()
            if self.proxy.text:
                self._expand_matches()
        if self.panel.isVisible():
            self._show_history()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._pending is not None:
            self.update_view(self._pending)

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
        # A collapsed program row stands for its tree, a group row for its
        # members; so does their history.
        pids = [p.pid]
        if p.members or (self.model.tree and self.model.has_children(p.pid)
                         and not self.model.is_expanded(p.pid)):
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
        self.model.set_sections(on)
        self._expand_sections()

    # -- sections -----------------------------------------------------------
    def _folded(self, pid: int, expanded: bool) -> None:
        """The view opened or closed a row; a section's state is remembered."""
        self.model.set_expanded(pid, expanded)
        if not is_section(pid):
            return
        key = KEY_OF_PID[pid]
        before = set(self._collapsed_sections)
        (self._collapsed_sections.discard if expanded else self._collapsed_sections.add)(key)
        if self._collapsed_sections != before:
            self.settings.setValue("collapsed_sections", ",".join(sorted(self._collapsed_sections)))

    def _expand_sections(self) -> None:
        """Sections open by default; one closed by hand stays closed, also next time."""
        if not self.model.sectioned:
            return
        for key, pid in SECTION_PID.items():
            if key in self._collapsed_sections:
                continue
            index = self.proxy.mapFromSource(self.model.index_for_pid(pid))
            if index.isValid() and not self.table.isExpanded(index):
                self.table.expand(index)

    def _remember_sort(self, column: int, order: Qt.SortOrder) -> None:
        self.settings.setValue("sort_column", column)
        self.settings.setValue("sort_order", order.value)

    def set_mode(self, mode: str) -> None:
        self.combo_mode.setCurrentIndex(self.combo_mode.findData(mode))

    def _set_mode(self, index: int) -> None:
        mode = self.combo_mode.itemData(index)
        self.settings.setValue("view_mode", mode)
        self.model.set_mode(mode)
        self.table.setRootIsDecorated(mode != "flat" or self.model.sectioned)
        self._expand_sections()
        if self.model.hierarchical and self.proxy.text:
            self._expand_matches()

    # -- search -----------------------------------------------------------
    def _search_changed(self, text: str) -> None:
        """In Tree mode a match deep in a collapsed branch would stay out of
        sight. While a search is active every branch on the way to a match is
        open; clearing the box puts the tree back the way it was."""
        had_text = bool(self.proxy.text)
        self.proxy.set_text(text)
        if not self.model.hierarchical:
            return
        if self.proxy.text:
            if not had_text:
                self._expanded_before_search = self.model.expanded_pids()
            self._expand_matches()
        elif had_text:
            self._restore_expansion()

    def _expand_matches(self) -> None:
        """The proxy filters recursively, so with a search active every visible
        row is a match or an ancestor of one; opening every visible branch is
        exactly "show the way to each match"."""
        pending = [QModelIndex()]
        while pending:
            parent = pending.pop()
            for row in range(self.proxy.rowCount(parent)):
                index = self.proxy.index(row, 0, parent)
                if self.proxy.rowCount(index):
                    self.table.expand(index)
                    pending.append(index)

    def _restore_expansion(self) -> None:
        before, self._expanded_before_search = self._expanded_before_search, None
        if before is None:
            return
        # collapseAll() emits no collapsed() signals, so tell the model ourselves.
        self.table.collapseAll()
        for pid in self.model.expanded_pids():
            self.model.set_expanded(pid, False)
        for pid in before:
            index = self.proxy.mapFromSource(self.model.index_for_pid(pid))
            if index.isValid():
                self.table.expand(index)

    def _auto_expand(self) -> None:
        """Steam opens when a new game shows up under it, so the game is one row
        below Steam without digging. Nothing else opens by itself."""
        steam = self.model.steam_pid
        if not steam:
            return
        new_games = set(self.model.game_children(steam)) - self._games_seen
        if not new_games:
            return
        self._games_seen |= new_games
        index = self.proxy.mapFromSource(self.model.index_for_pid(steam))
        while index.isValid():
            self.table.expand(index)
            index = index.parent()

    # -- selection --------------------------------------------------------
    def _selected(self) -> list[ProcSample]:
        out = []
        for idx in self.table.selectionModel().selectedRows():
            p = self.model.proc_at(self.proxy.mapToSource(idx))
            if p is not None:
                out.append(p)
        return out

    def _selected_real(self) -> list[ProcSample]:
        """Selected processes, with a group row standing for its members. A
        group row has a negative pid that no kernel call can take; acting on
        it means acting on every process shown under it."""
        seen: set[int] = set()
        out: list[ProcSample] = []
        for p in self._selected():
            for q in ([p] if p.pid > 0 else self.model.procs_under(p.pid)):
                if q.pid not in seen:
                    seen.add(q.pid)
                    out.append(q)
        return out

    def _selected_trees(self) -> list[ProcSample]:
        """Selected processes plus every descendant (or group member), children
        first, no duplicates, real processes only."""
        seen: set[int] = set()
        out: list[ProcSample] = []
        for p in self._selected():
            for q in self.model.procs_under(p.pid):
                if q.pid not in seen:
                    seen.add(q.pid)
                    out.append(q)
        return out

    # -- context menu -----------------------------------------------------
    def _menu(self, pos) -> None:
        procs = self._selected()
        if not procs:
            return
        one = procs[0] if len(procs) == 1 else None
        title = one.display_name if one else f"{len(procs)} processes"
        menu = QMenu(self)
        detail = "" if one is None else (f"  ·  {one.members} processes" if one.members
                                         else f"  ·  pid {one.pid}")
        header = menu.addAction(f"{title}{detail}")
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

    def show_pid(self, pid: int) -> bool:
        """Select this process's row and bring it into view: the search is
        cleared and its parents opened. False when the list does not have it."""
        if self.search.text():
            self.search.setText("")
        src = self.model.index_for_pid(pid)
        if not src.isValid():
            return False
        idx = self.proxy.mapFromSource(src)
        if not idx.isValid():
            return False
        parent = idx.parent()
        while parent.isValid():
            self.table.expand(parent)
            parent = parent.parent()
        flag = QItemSelectionModel.SelectionFlag
        self.table.selectionModel().select(idx, flag.ClearAndSelect | flag.Rows)
        self.table.setCurrentIndex(idx)
        self.table.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)
        return True

    # -- actions ----------------------------------------------------------
    def _run(self, fn, procs: list[ProcSample], verb: str) -> None:
        """Every outcome is shown: a count for what was done, a box for what
        was not. An action that silently does nothing is worse than an error,
        so even a fault in our own code lands in the box instead of in a
        traceback on stderr that nobody sees."""
        done, errors = 0, []
        for p in procs:
            try:
                fn(p)
                done += 1
            except ActionError as exc:
                errors.append(f"{p.display_name} ({p.pid}): {exc}")
            except Exception as exc:  # noqa: BLE001 - reported, never swallowed
                errors.append(f"{p.display_name} ({p.pid}): {type(exc).__name__}: {exc}")
        if done:
            self.status.emit(f"{verb}: {done} process(es)")
        elif not procs:
            self.status.emit(f"{verb}: nothing selected")
        if errors:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Failed")
            box.setText(f"{len(errors)} of {len(procs)} not carried out.")
            box.setDetailedText("\n".join(errors))
            box.exec()

    def _signal_selected(self, sig: signal.Signals, confirm: bool = False,
                         tree: bool = False) -> None:
        """There is no undo for a signal, so the guard sits here, before it is sent."""
        procs = self._selected_trees() if tree else self._selected()
        if not procs:
            return
        if any(p.members for p in procs):
            # A group row stands for all its processes: signal every one of
            # them, and always ask first, naming each.
            procs = self._selected_trees()
            kw = {"tree": True, "always_ask": True, "list_all": True}
        else:
            kw = {"tree": tree, "always_ask": confirm}
        verdict = signalguard.check(procs, sig.name, **kw)
        if verdict.refused:
            self._notice("Not done", verdict.refused)
            return
        # Only now, with a dialog about to open: does a service start the
        # process again? One systemctl call per service unit, about 4 ms each.
        note = signalguard.restart_note(procs, sig.name)
        if note:
            if not verdict.confirm:
                # ending it would change nothing for long: that is worth asking
                verdict = signalguard.check(procs, sig.name, **{**kw, "always_ask": True})
            verdict.text = f"{verdict.text}\n\n{note}".strip()
        if verdict.confirm and not self._confirm(verdict):
            return
        self._run(lambda p: self.backend.send_signal(p.pid, sig), procs, sig.name)
        if sig == signal.SIGTERM:
            self.watch(procs)

    # -- after a Terminate: is it gone? ------------------------------------
    # A program may ignore the request. Nothing is forced by itself: the pid
    # is watched on the next samples, and when it is still there after
    # WATCH_S the toast says so and offers one button, so the user is not
    # sent hunting through a context menu for Force kill.
    def watch(self, procs: list[ProcSample], name: str = "") -> None:
        """Watch these processes, asked to quit just now, for WATCH_S."""
        procs = [p for p in procs if p.pid > 0]
        if not procs:
            return
        lead = next((p for p in procs if p.app_name), procs[0])
        self._watches.append({"pids": {p.pid: p.create_time for p in procs},
                              "name": name or lead.display_name, "sent": time.time()})

    def _check_watches(self, snap) -> None:
        if not self._watches:
            return
        alive = {p.pid: p for p in snap.procs}
        now = time.time()
        for watch in list(self._watches):
            # the same pid with another start time is another process
            left = [alive[pid] for pid, born in watch["pids"].items()
                    if pid in alive and alive[pid].create_time == born]
            if not left:
                self._watches.remove(watch)
                continue
            if now - watch["sent"] < WATCH_S:
                continue
            self._watches.remove(watch)
            name = watch["name"]
            text = (f"{name} is still running." if len(left) == 1
                    else f"{name}: {len(left)} processes are still running.")
            self.offer.emit(text, "Force kill", lambda procs=left: self._force(procs))

    def _force(self, procs: list[ProcSample]) -> None:
        """SIGKILL to what stayed, after the same confirmation as any Force kill."""
        many = len(procs) > 1
        verdict = signalguard.check(procs, "KILL", tree=many, always_ask=True, list_all=many)
        if verdict.refused:
            self._notice("Not done", verdict.refused)
            return
        if verdict.confirm and not self._confirm(verdict):
            return
        self._run(lambda p: self.backend.send_signal(p.pid, signal.SIGKILL), procs, "SIGKILL")

    def _confirm(self, verdict: signalguard.Verdict) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.NoIcon)
        box.setWindowTitle(verdict.title)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(verdict.title)
        box.setInformativeText(verdict.text)
        go = box.addButton(verdict.button, QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        return box.clickedButton() is go

    def _notice(self, title: str, text: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.NoIcon)
        box.setWindowTitle(title)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(text)
        box.exec()

    def _set_nice(self, value: int) -> None:
        self._run(lambda p: self.backend.set_nice(p.pid, value),
                  self._selected_real(), f"nice {value}")

    def _set_ionice(self, klass, value: int = 4) -> None:
        self._run(lambda p: self.backend.set_ionice(p.pid, klass, value),
                  self._selected_real(), "disk priority")

    def _affinity(self, proc: ProcSample) -> None:
        """For a group row the dialog starts from the first member's mask and
        the choice goes to every member."""
        targets = [proc] if proc.pid > 0 else self.model.procs_under(proc.pid)
        if not targets:
            self.status.emit("affinity: nothing selected")
            return
        current = self.backend.get_affinity(targets[0].pid) or list(range(self.ncpu))
        dlg = AffinityDialog(proc, current, self.ncpu, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._run(lambda p: self.backend.set_affinity(p.pid, dlg.selection()),
                  targets, "affinity")

    @staticmethod
    def _copy(text: str) -> None:
        QGuiApplication.clipboard().setText(text)
