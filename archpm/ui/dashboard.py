"""The overview: what is this PC doing right now, at a glance."""
from __future__ import annotations

import platform
import time

import psutil
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..game import game_tree, pick_game
from ..helptext import CANNOT_UNDO, duration, plural
from ..model import ProcSample, Snapshot, SystemSample
from ..sysinfo import cpu_model, short_cpu_name
from ..verdict import (
    GAME_GPU_FULL,
    StrainWatch,
    Verdict,
    game_verdict,
    gpu_caption,
    temp_level,
)
from . import hints, theme
from .history import ProcHistory
from .proc_model import age_text
from .widgets import (
    Card,
    CoreGrid,
    FlowLayout,
    Graph,
    StatTile,
    TextLink,
    TileRow,
    app_icon,
    human_bytes,
    mono,
)

# Below this page width the four cards stand in one column instead of two,
# so a graph keeps a readable width; the page scrolls, so height is free.
ONE_COLUMN_BELOW = 720


class GameCard(Card):
    help_requested = Signal(str)

    """What is my game doing right now: one process, its tree, its last minutes."""

    terminate_requested = Signal(list, str)   # pids (children first), game name

    def __init__(self, ncpu: int, parent=None) -> None:
        super().__init__("game", parent, color="ACCENT")
        self.ncpu = ncpu
        self.pid = 0
        self.name = ""
        self._tree_pids: list[int] = []
        self._affinity: tuple[int, int, int] = (0, 0, 0)  # pid, cores, tick
        self._tick = 0
        row = QHBoxLayout()
        row.setSpacing(18)

        left = QVBoxLayout()
        left.setSpacing(4)
        name_row = QHBoxLayout()
        name_row.setSpacing(12)
        self.lbl_name = QLabel("No game running")
        self.lbl_name.setFont(mono("title", bold=True))
        self.lbl_name.setTextFormat(Qt.TextFormat.RichText)
        # Expanding: with the tiles hidden nothing else in this column wants
        # width, and the layout would shrink it to the label's minimum.
        self.lbl_name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        name_row.addWidget(self.lbl_name, 1)
        self.btn_kill = QPushButton("End game…")
        self.btn_kill.setObjectName("kill")
        self.btn_kill.setToolTip("Ask the game and everything it started to quit. If it stays, "
                                 "ArchPM says so after a few seconds and offers to force it.")
        self.btn_kill.clicked.connect(self._confirm_terminate)
        name_row.addWidget(self.btn_kill)
        left.addLayout(name_row)
        self.lbl_verdict = QLabel()
        self.lbl_verdict.setFont(theme.font("body", bold=True))
        self.lbl_verdict.setWordWrap(True)
        self.lbl_verdict.hide()
        left.addWidget(self.lbl_verdict)
        self.lbl_sub = QLabel("A Steam game, or any program doing real GPU work, shows up here "
                              "the moment it starts.")
        self.lbl_sub.setWordWrap(True)
        theme.style(self.lbl_sub, "color: {MUTED};")
        self.lbl_sub.setFont(mono("small"))
        self.lbl_sub.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        left.addWidget(self.lbl_sub)
        self.t_cpu = StatTile("cpu", "CPU")
        self.t_gpu = StatTile("gpu", "GPU")
        self.t_vram = StatTile("video memory", "GPU")
        self.t_mem = StatTile("ram", "MEM")
        self.t_thr = StatTile("threads", "CPU")
        self.t_cores = StatTile("cores", "CPU")
        for t, key in ((self.t_cpu, "game.cpu"), (self.t_gpu, "game.gpu"),
                       (self.t_vram, "game.vram"), (self.t_mem, "game.ram"),
                       (self.t_thr, "game.threads"), (self.t_cores, "game.cores")):
            hints.attach(t, key, self.help_requested.emit)
        # equal widths, like the six tiles at the top; two rows of three when narrow
        self.tiles = TileRow([self.t_cpu, self.t_gpu, self.t_vram, self.t_mem,
                              self.t_thr, self.t_cores], theme.CARD_GAP)
        left.addWidget(self.tiles)
        left.addStretch(1)
        row.addLayout(left, 3)

        self.graph = Graph([("CPU", "CPU"), ("GPU", "GPU")], maximum=None, fill=False)
        self.graph.setMinimumHeight(110)
        hints.attach(self.graph, "game.graph", self.help_requested.emit)
        row.addWidget(self.graph, 2)
        self.body.addLayout(row)
        self._set_tiles_visible(False)

    def _set_tiles_visible(self, on: bool) -> None:
        self.tiles.setVisible(on)
        self.graph.setVisible(on)
        self.btn_kill.setVisible(on)

    def _confirm_terminate(self) -> None:
        if not self.pid:
            return
        answer = QMessageBox.question(
            self, "End the game?",
            f"Ask <b>{self.name}</b> and the {len(self._tree_pids)} processes that belong to "
            "it to quit?<br><br>Unsaved progress is lost. The game gets the chance to close "
            "cleanly; if it hangs and stays, ArchPM says so after a few seconds and offers "
            f"to force it.<br><br>{CANNOT_UNDO}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.terminate_requested.emit(list(self._tree_pids), self.name)

    def _cores_allowed(self, pid: int) -> int:
        """One syscall, for one process, every fifth tick: cheap enough."""
        self._tick += 1
        cached_pid, cores, tick = self._affinity
        if cached_pid == pid and self._tick - tick < 5:
            return cores
        try:
            cores = len(psutil.Process(pid).cpu_affinity())
        except psutil.Error:
            cores = 0
        self._affinity = (pid, cores, self._tick)
        return cores

    def update_view(self, procs: list[ProcSample], history: ProcHistory | None,
                    system: SystemSample | None = None) -> None:
        game = pick_game(procs, self.pid)
        if game is None:
            if self.pid:
                self.pid = 0
                self.lbl_name.setText("No game running")
                self.lbl_sub.setText("A Steam game, or any program doing real GPU work, "
                                     "shows up here the moment it starts.")
                self.lbl_verdict.hide()
                self._set_tiles_visible(False)
            return
        if not self.pid:
            self._set_tiles_visible(True)
        self.pid = game.pid
        self.name = game.display_name
        tree = game_tree(game, procs)
        # children first, so nothing is orphaned and re-spawned while we work
        self._tree_pids = [p.pid for p in tree if p.pid != game.pid] + [game.pid]
        cpu = sum(p.cpu_percent for p in tree)
        rss = sum(p.mem_rss for p in tree)
        gpu = max(p.gpu_sm for p in tree)
        vram = sum(p.gpu_mem_mb for p in tree)
        threads = sum(p.num_threads for p in tree)
        icon = app_icon(game.icon)
        self.lbl_name.setText(
            f"<span style='color:{theme.ACCENT}'>{game.display_name}</span>"
            f"<span style='color:{theme.FAINT}'>&nbsp;&nbsp;·&nbsp;&nbsp;process {game.pid}"
            f"&nbsp;&nbsp;·&nbsp;&nbsp;{plural(len(tree), 'process')}</span>"
        )
        self.lbl_name.setToolTip(game.cmdline)
        started = age_text(time.time() - game.create_time) if game.create_time else "?"
        priority = ("raised" if game.nice < 0 else "lowered" if game.nice > 0 else "normal")
        self.lbl_sub.setText(f"Running {started}  ·  Priority {priority}"
                             + (f"  ·  {game.name}" if game.app_name else ""))
        # The card's own rule, not the heat scale: for a game the card fully
        # used is the good outcome, so it is green and never red.
        cpu_t = system.cpu_temp_c if system else 0.0
        gpu_t = system.gpu.temp_c if system and system.gpu else 0.0
        text, token = game_verdict(cpu, gpu, cpu_t, gpu_t)
        self.lbl_verdict.setText(text)
        theme.text(self.lbl_verdict, token)
        self.lbl_verdict.show()
        # one scale for one thing: the share of the whole processor, as the
        # tile at the top of the page; not "9%" beside "1.4 of 16 cores"
        self.t_cpu.set(f"{cpu / self.ncpu:.0f}%", f"of all {self.ncpu} cores",
                       "WARN" if token == "WARN" else "TEXT")
        self.t_gpu.set(f"{gpu:.0f}%", gpu_caption(gpu),
                       "OK" if gpu >= GAME_GPU_FULL else "TEXT")
        total = system.gpu.mem_total_mb if system and system.gpu else 0.0
        self.t_vram.set(f"{vram / 1024:.1f} GB", f"of the card's {total / 1024:.0f} GB"
                        if total else "")
        self.t_mem.set(human_bytes(rss), "with everything it started")
        self.t_thr.set(str(threads), f"across {plural(len(tree), 'process')}")
        cores = self._cores_allowed(game.pid)
        self.t_cores.set(f"{cores or '?'} of {self.ncpu}", "it may use")
        if history is not None:
            track = history.tree([p.pid for p in tree])
            # same notation as the tile next to it: share of the whole machine
            self.graph.set_history([c / self.ncpu for c in track.cpu], track.gpu)
        del icon  # the name label is text; the icon lives in the process list


class TopProcList(QWidget):
    """Top-N processes as named bars -- quicker to read than a table."""

    def __init__(self, color: str, unit: str = "%", rows: int = 5, parent=None) -> None:
        super().__init__(parent)
        self.color = color
        self.unit = unit
        self.rows = rows
        self.items: list[tuple[str, int, float, str]] = []  # name, pid, value, icon
        self.scale = 100.0
        self.setMinimumHeight(rows * 22)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_items(self, items: list[tuple[str, int, float, str]],
                  scale: float | None = None) -> None:
        self.items = items[: self.rows]
        self.scale = scale or max([v for _, _, v, _ in self.items] + [1.0])
        self.update()

    def _fmt(self, value: float) -> str:
        # Shares of the whole machine are small at idle (kwin at 3% of one
        # core is 0.2% of sixteen); a bare "0%" reads as a broken list.
        if self.unit == "%" and value < 10:
            return f"{value:.1f}%"
        return f"{value:,.0f}{self.unit}".replace(",", " ")

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.height() / max(self.rows, 1)
        p.setFont(mono("body"))
        val_w = 74.0
        for i, (name, _pid, value, icon_key) in enumerate(self.items):
            y = i * h
            frac = min(value / self.scale, 1.0) if self.scale else 0.0
            col = theme.color(self.color)
            col.setAlpha(46)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(0, y + 1, self.width() * frac, h - 3), 4, 4)
            text_x = 6.0
            icon = app_icon(icon_key)
            if not icon.isNull():
                size = int(min(h - 6, 16))
                icon.paint(p, int(text_x), int(y + (h - size) / 2), size, size)
                text_x += size + 6
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(text_x, y, self.width() - val_w - text_x, h - 2),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       f"{name}")
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(self.width() - val_w - 6, y, val_w, h - 2),
                       int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                       self._fmt(value))
        p.end()


class Dashboard(QWidget):
    root_requested = Signal()
    process_requested = Signal(int)   # the verdict was clicked: show this pid in Processes
    failed_clicked = Signal()     # "N services failed" was clicked: show the System page
    help_requested = Signal(str)

    def __init__(self, ncpu: int, history: ProcHistory | None = None, parent=None) -> None:
        super().__init__(parent)
        self.ncpu = ncpu
        self.history = history
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*theme.page_margins())
        outer.setSpacing(theme.CARD_GAP)

        # -- header: the verdict first, in words; the machine line under it --
        # The one line a beginner needs: is anything straining the machine,
        # and which program. A link to that program's row when there is one.
        head = FlowLayout(spacing=12)   # the controls drop to a second row when narrow
        self.lbl_verdict = TextLink()
        self.lbl_verdict.set_css("font-size: {FONT_TITLE}pt; font-weight: 700;")
        self.lbl_verdict.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.lbl_verdict.setAccessibleName("Verdict")
        self.lbl_verdict.activated.connect(self._verdict_clicked)
        hints.attach(self.lbl_verdict, "tile.verdict", self.help_requested.emit)
        head.addWidget(self.lbl_verdict)
        head.addStretch(1)
        # Failed services: a snapshot taken at start (and on Refresh on the
        # System page). Plain muted text when there are none, a link when
        # there are; never a button, never on the sampling cycle.
        self.lbl_failed = TextLink()
        self.lbl_failed.activated.connect(self.failed_clicked.emit)
        head.addWidget(self.lbl_failed)
        outer.addLayout(head)
        sub = FlowLayout(spacing=12)
        self.lbl_machine = QLabel()
        self.lbl_machine.setFont(mono("small"))
        self.lbl_machine.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_machine.setWordWrap(True)      # two lines in a narrow window
        self.lbl_machine.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        sub.addWidget(self.lbl_machine)
        sub.addStretch(1)
        self.lbl_root_state = QLabel()
        self.lbl_root_state.setFont(mono("small"))
        theme.style(self.lbl_root_state, "color: {MUTED};")
        sub.addWidget(self.lbl_root_state)
        outer.addLayout(sub)
        self.strain = StrainWatch()
        self._verdict = Verdict()
        self._show_verdict(self._verdict)

        self._cpu_name = short_cpu_name(cpu_model())
        self._machine = (
            platform.node(),
            platform.release(),
            f"{psutil.cpu_count(logical=False) or ncpu} cores, {ncpu} threads",
        )
        self._render_machine(0.0)
        # Root tasks: made here, placed at the foot of the page below
        self.btn_root = QPushButton("Root tasks…")
        self.btn_root.setToolTip(
            "Root actions (raising priority, memory) and your own session's services."
        )
        self.btn_root.clicked.connect(self.root_requested.emit)
        self.set_root_state(False)

        # -- tiles: six across, or two rows of three when the window is narrow
        self.t_cpu = StatTile("cpu", "CPU")
        self.t_cputemp = StatTile("cpu temp", "CPU")
        self.t_gpu = StatTile("gpu", "GPU")
        self.t_gputemp = StatTile("gpu temp", "GPU")
        self.t_mem = StatTile("memory", "MEM")
        self.t_vram = StatTile("video memory", "GPU")
        for t, key in ((self.t_cpu, "tile.cpu"), (self.t_cputemp, "tile.cpu temp"),
                       (self.t_gpu, "tile.gpu"), (self.t_gputemp, "tile.gpu temp"),
                       (self.t_mem, "tile.memory"), (self.t_vram, "tile.vram")):
            hints.attach(t, key, self.help_requested.emit)
        self.tiles = TileRow([self.t_cpu, self.t_cputemp, self.t_gpu, self.t_gputemp,
                              self.t_mem, self.t_vram], theme.CARD_GAP)
        outer.addWidget(self.tiles)

        grid = QGridLayout()
        grid.setSpacing(theme.CARD_GAP)
        outer.addLayout(grid, 1)
        self.grid = grid

        # -- CPU -----------------------------------------------------------
        cpu_card = Card("processor", color="CPU")
        self.g_cpu = Graph([("Total", "CPU")], maximum=100.0)
        cpu_card.body.addWidget(self.g_cpu, 1)
        self.cores = CoreGrid()
        cpu_card.body.addWidget(self.cores)
        hints.attach(self.g_cpu, "graph.cpu", self.help_requested.emit)
        hints.attach(self.cores, "graph.cpu", self.help_requested.emit)
        grid.addWidget(cpu_card, 0, 0)

        # -- GPU -----------------------------------------------------------
        gpu_card = Card("graphics card", color="GPU")
        self.g_gpu = Graph([("GPU load", "GPU"), ("Video memory", "DISK")], maximum=100.0)
        gpu_card.body.addWidget(self.g_gpu, 1)
        hints.attach(self.g_gpu, "graph.gpu", self.help_requested.emit)
        self.gpu_sub = QLabel("--")
        self.gpu_sub.setWordWrap(True)
        self.gpu_sub.setFont(mono("small"))
        theme.style(self.gpu_sub, "color: {MUTED};")
        gpu_card.body.addWidget(self.gpu_sub)
        grid.addWidget(gpu_card, 0, 1)

        # -- memory --------------------------------------------------------
        mem_card = Card("memory", color="MEM")
        self.g_mem = Graph([("RAM", "MEM"), ("On disk (swap)", "SWAP")], maximum=100.0)
        mem_card.body.addWidget(self.g_mem, 1)
        hints.attach(self.g_mem, "graph.mem", self.help_requested.emit)
        self.mem_sub = QLabel("--")
        self.mem_sub.setWordWrap(True)
        self.mem_sub.setFont(mono("small"))
        theme.style(self.mem_sub, "color: {MUTED};")
        mem_card.body.addWidget(self.mem_sub)
        grid.addWidget(mem_card, 1, 0)

        # -- I/O -----------------------------------------------------------
        io_card = Card("network & disk", color="NET")
        self.g_net = Graph([("Download", "NET"), ("Upload", "CPU")],
                           maximum=None, fill=False)
        self.g_net.set_formatter(lambda v: f"{human_bytes(v)}/s")
        io_card.body.addWidget(self.g_net, 1)
        hints.attach(self.g_net, "graph.net", self.help_requested.emit)
        self.g_disk = Graph([("Disk read", "DISK"), ("Disk write", "SWAP")],
                            maximum=None, fill=False)
        self.g_disk.set_formatter(lambda v: f"{human_bytes(v)}/s")
        io_card.body.addWidget(self.g_disk, 1)
        hints.attach(self.g_disk, "graph.disk", self.help_requested.emit)
        grid.addWidget(io_card, 1, 1)

        # -- game ----------------------------------------------------------
        self.game = GameCard(ncpu)
        self.game.help_requested.connect(self.help_requested.emit)

        # -- top lists -----------------------------------------------------
        top_card = Card("top processes")
        row = QHBoxLayout()
        row.setSpacing(18)
        cpu_col = QVBoxLayout()
        cpu_col.addWidget(self._sublabel("cpu · of all cores", "CPU"))
        self.top_cpu = TopProcList("CPU", "%")
        cpu_col.addWidget(self.top_cpu)
        mem_col = QVBoxLayout()
        mem_col.addWidget(self._sublabel("memory", "MEM"))
        self.top_mem = TopProcList("MEM", " MB")
        mem_col.addWidget(self.top_mem)
        gpu_col = QVBoxLayout()
        gpu_col.addWidget(self._sublabel("video memory", "GPU"))
        self.top_gpu = TopProcList("GPU", " MB")
        gpu_col.addWidget(self.top_gpu)
        for col in (cpu_col, mem_col, gpu_col):
            row.addLayout(col, 1)
        for lst, key in ((self.top_cpu, "top.cpu"), (self.top_mem, "top.mem"),
                         (self.top_gpu, "top.vram")):
            hints.attach(lst, key, self.help_requested.emit)
        top_card.body.addLayout(row)

        # Two columns of cards, one column when the window is narrow; the
        # game and the top lists always span the width.
        self.cards = [cpu_card, gpu_card, mem_card, io_card]
        self.wide_cards = [self.game, top_card]
        self._columns = 0
        self._place_cards(2)

        # -- foot: the entry point to root, last on the page on purpose ------
        # It was the first button, always there, one click from Drop caches:
        # where a Windows user goes to free memory and should not.
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(self.btn_root)
        outer.addLayout(foot)

    def _place_cards(self, cols: int) -> None:
        if cols == self._columns:
            return
        grid = self.grid
        while grid.count():
            grid.takeAt(0)
        for i, card in enumerate(self.cards):
            grid.addWidget(card, i // cols, i % cols)
        rows = -(-len(self.cards) // cols)
        for i, card in enumerate(self.wide_cards):
            grid.addWidget(card, rows + i, 0, 1, cols)
        for r in range(rows + len(self.wide_cards) + 2):
            grid.setRowStretch(r, 3 if r < rows else (2 if r < rows + len(self.wide_cards) else 0))
        for c in range(2):
            grid.setColumnStretch(c, 1 if c < cols else 0)
        self._columns = cols

    def columns(self) -> int:
        return self._columns

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_cards(1 if event.size().width() < ONE_COLUMN_BELOW else 2)

    def set_failed(self, count: int) -> None:
        if count == 0:
            self.lbl_failed.set_plain("No failed services", "MUTED")
            self.lbl_failed.setToolTip(
                "systemctl --failed and systemctl --user --failed listed nothing when the "
                "window started. \"Refresh failed services\" on the System page looks again.")
            return
        noun = "service" if count == 1 else "services"
        self.lbl_failed.set_link(f"{count} {noun} failed", "WARN")
        self.lbl_failed.setToolTip("Opens the System page: the list, and the last log lines "
                                   "of each. Enter works too.")

    def game_name(self) -> str:
        """The running game's name, "" without one; for the tray."""
        return self.game.name if self.game.pid else ""

    def _render_machine(self, uptime_s: float) -> None:
        """The machine line, quiet: the verdict above it is what the eye
        should land on, so the hostname is no longer the yellow headline."""
        node, release, cores = self._machine
        sep = f"<span style='color:{theme.FAINT}'>&nbsp;&nbsp;·&nbsp;&nbsp;</span>"
        up = duration(uptime_s)
        self.lbl_machine.setText(
            f"<span style='color:{theme.LABEL}'>{node}</span>{sep}"
            f"<span style='color:{theme.MUTED}'>{release}</span>{sep}"
            f"<span style='color:{theme.MUTED}'>{cores}</span>{sep}"
            f"<span style='color:{theme.MUTED}'>Up {up}</span>"
        )

    # -- the verdict ----------------------------------------------------------
    VERDICT_COLOUR = {"calm": "TEXT", "game": "TEXT", "strain": "ACCENT", "hot": "CRIT"}

    def _show_verdict(self, v: Verdict) -> None:
        self._verdict = v
        colour = self.VERDICT_COLOUR[v.level]
        if v.pid:
            self.lbl_verdict.set_link(v.text, colour)
            self.lbl_verdict.setToolTip(f"Open Processes with {v.program} selected.")
        else:
            self.lbl_verdict.set_plain(v.text, colour)
            self.lbl_verdict.setToolTip("")

    def _verdict_clicked(self) -> None:
        if self._verdict.pid:
            self.process_requested.emit(self._verdict.pid)

    def verdict(self) -> Verdict:
        return self._verdict

    def set_root_state(self, elevated: bool) -> None:
        """Colours the button as soon as root actions are active -- that should be visible."""
        if elevated:
            self.btn_root.setObjectName("accent")
            self.lbl_root_state.setText("root actions active")
            theme.style(self.lbl_root_state, "color: {ACCENT};")
        else:
            self.btn_root.setObjectName("")
            self.lbl_root_state.setText("")
        self.btn_root.style().unpolish(self.btn_root)
        self.btn_root.style().polish(self.btn_root)

    @staticmethod
    def _sublabel(text: str, color: str = "LABEL") -> QLabel:
        lbl = QLabel(text.upper())
        lbl.setFont(theme.font("small", bold=True))
        theme.text(lbl, color)
        return lbl

    # ------------------------------------------------------------------
    def update_view(self, snap: Snapshot) -> None:
        s = snap.system
        self._render_machine(time.time() - psutil.boot_time())
        self.g_cpu.push(s.cpu_percent)
        self.cores.set_values(s.per_core)
        self.t_cpu.set(f"{s.cpu_percent:.0f}%", self._cpu_name, theme.heat(s.cpu_percent).name())
        if s.cpu_temp_c:
            # the reference on the tile, not only in the tooltip: normal,
            # warm or hot, and the colour by the same rule, not the heat scale
            word, token = temp_level(s.cpu_temp_c)
            self.t_cputemp.set(f"{s.cpu_temp_c:.0f}°", word, token)

        if s.gpu:
            g = s.gpu
            self.g_gpu.push(g.util, g.mem_pct)
            self.t_gpu.set(f"{g.util:.0f}%", g.name.replace("NVIDIA GeForce ", ""),
                           theme.heat(g.util).name())
            word, token = temp_level(g.temp_c)
            self.t_gputemp.set(f"{g.temp_c:.0f}°", f"{word}  ·  fan {g.fan_pct:.0f}%", token)
            self.t_vram.set(f"{g.mem_used_mb / 1024:.1f} GB",
                            f"{g.mem_pct:.0f}% of {g.mem_total_mb / 1024:.0f} GB")
            self.gpu_sub.setText(
                f"{g.power_w:.0f} W  ·  {g.clock_mhz:.0f} MHz  ·  "
                f"{g.mem_used_mb:.0f}/{g.mem_total_mb:.0f} MB"
            )
        else:
            self.gpu_sub.setText("No GPU telemetry available")

        swap_pct = 100.0 * s.swap_used / s.swap_total if s.swap_total else 0.0
        self.g_mem.push(s.mem_pct, swap_pct)
        self.t_mem.set(f"{s.mem_used / 2**30:.1f} GB",
                       f"{s.mem_pct:.0f}% of {s.mem_total / 2**30:.0f} GB",
                       theme.heat(s.mem_pct).name())
        self.mem_sub.setText(
            f"Free {s.mem_available / 2**30:.1f} GB  ·  On disk (swap) "
            f"{s.swap_used / 2**30:.1f}/{s.swap_total / 2**30:.0f} GB  ·  "
            f"{s.proc_count} processes, {s.thread_count} threads"
        )

        self.g_net.push(s.net_rx_bps, s.net_tx_bps)
        self.g_disk.push(s.disk_r_bps, s.disk_w_bps)

        procs = snap.procs
        self._show_verdict(self.strain.update(s, procs, self.ncpu))
        self.game.update_view(procs, self.history, s)
        # Shown as a share of the whole machine, like the CPU tile above it;
        # "135%" (top's one-core notation) reads as an error to most people.
        # Bars are relative to the busiest entry, like the two lists next to
        # it: against a fixed 100% nothing is visible on an idle desktop.
        self.top_cpu.set_items(
            [(p.display_name, p.pid, p.cpu_percent / self.ncpu, p.icon)
             for p in sorted(procs, key=lambda x: x.cpu_percent, reverse=True)[:5]]
        )
        self.top_mem.set_items(
            [(p.display_name, p.pid, p.mem_mb, p.icon)
             for p in sorted(procs, key=lambda x: x.mem_rss, reverse=True)[:5]]
        )
        gpu_procs = [p for p in procs if p.gpu_mem_mb]
        self.top_gpu.set_items(
            [(p.display_name, p.pid, p.gpu_mem_mb, p.icon)
             for p in sorted(gpu_procs, key=lambda x: x.gpu_mem_mb, reverse=True)[:5]]
        )
