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
from ..model import ProcSample, Snapshot
from . import theme
from .history import ProcHistory
from .proc_model import age_text
from .widgets import Card, CoreGrid, Graph, StatTile, app_icon, human_bytes, mono


class GameCard(Card):
    """What is my game doing right now: one process, its tree, its last minutes."""

    terminate_requested = Signal(list, str)   # pids (children first), game name

    def __init__(self, ncpu: int, parent=None) -> None:
        super().__init__("game", parent, color=theme.ACCENT)
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
        self.lbl_name.setFont(mono(12, bold=True))
        self.lbl_name.setTextFormat(Qt.TextFormat.RichText)
        # Expanding: with the tiles hidden nothing else in this column wants
        # width, and the layout would shrink it to the label's minimum.
        self.lbl_name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        name_row.addWidget(self.lbl_name, 1)
        self.btn_kill = QPushButton("End game")
        self.btn_kill.setObjectName("kill")
        self.btn_kill.setToolTip("Ask the game and everything it started to quit (SIGTERM). "
                                 "For a game that does not react, use Force kill in Processes.")
        self.btn_kill.clicked.connect(self._confirm_terminate)
        name_row.addWidget(self.btn_kill)
        left.addLayout(name_row)
        self.lbl_sub = QLabel("A Steam game, or any program doing real GPU work, shows up here "
                              "the moment it starts.")
        self.lbl_sub.setWordWrap(True)
        self.lbl_sub.setStyleSheet(f"color: {theme.MUTED};")
        self.lbl_sub.setFont(mono(8))
        self.lbl_sub.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        left.addWidget(self.lbl_sub)
        self.tiles = QHBoxLayout()
        self.tiles.setSpacing(8)
        self.t_cpu = StatTile("cpu", theme.CPU)
        self.t_gpu = StatTile("gpu", theme.GPU)
        self.t_vram = StatTile("vram", theme.GPU)
        self.t_mem = StatTile("ram", theme.MEM)
        self.t_thr = StatTile("threads", theme.CPU)
        self.t_cores = StatTile("cores", theme.CPU)
        for t in (self.t_cpu, self.t_gpu, self.t_vram, self.t_mem, self.t_thr, self.t_cores):
            self.tiles.addWidget(t, 1)   # equal widths, like the six tiles at the top
        left.addLayout(self.tiles)
        left.addStretch(1)
        row.addLayout(left, 3)

        self.graph = Graph([("cpu", theme.CPU), ("gpu", theme.GPU)], maximum=None, fill=False)
        self.graph.setMinimumHeight(110)
        row.addWidget(self.graph, 2)
        self.body.addLayout(row)
        self._set_tiles_visible(False)

    def _set_tiles_visible(self, on: bool) -> None:
        for t in (self.t_cpu, self.t_gpu, self.t_vram, self.t_mem, self.t_thr, self.t_cores):
            t.setVisible(on)
        self.graph.setVisible(on)
        self.btn_kill.setVisible(on)

    def _confirm_terminate(self) -> None:
        if not self.pid:
            return
        answer = QMessageBox.question(
            self, "End the game?",
            f"Ask <b>{self.name}</b> and the {len(self._tree_pids)} processes that belong to "
            "it to quit?<br><br>Unsaved progress is lost. The game gets the chance to close "
            "cleanly; if it hangs and stays, use Force kill in the Processes tab.",
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

    def update_view(self, procs: list[ProcSample], history: ProcHistory | None) -> None:
        game = pick_game(procs, self.pid)
        if game is None:
            if self.pid:
                self.pid = 0
                self.lbl_name.setText("No game running")
                self.lbl_sub.setText("A Steam game, or any program doing real GPU work, "
                                     "shows up here the moment it starts.")
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
            f"<span style='color:{theme.FAINT}'>&nbsp;&nbsp;·&nbsp;&nbsp;pid {game.pid}"
            f"&nbsp;&nbsp;·&nbsp;&nbsp;{len(tree)} processes</span>"
        )
        self.lbl_name.setToolTip(game.cmdline)
        started = age_text(time.time() - game.create_time) if game.create_time else "?"
        self.lbl_sub.setText(f"running {started}  ·  nice {game.nice}"
                             + (f"  ·  {game.name}" if game.app_name else ""))
        self.t_cpu.set(f"{cpu / self.ncpu:.0f}%", f"{cpu / 100:.1f} of {self.ncpu} cores",
                       theme.heat(cpu / self.ncpu).name())
        self.t_gpu.set(f"{gpu:.0f}%", "of the GPU", theme.heat(gpu).name())
        self.t_vram.set(f"{vram / 1024:.1f} G", f"{vram:.0f} MB")
        self.t_mem.set(human_bytes(rss), "whole tree")
        self.t_thr.set(str(threads), f"in {len(tree)} processes")
        cores = self._cores_allowed(game.pid)
        self.t_cores.set(f"{cores or '?'} of {self.ncpu}", "allowed")
        if history is not None:
            track = history.tree([p.pid for p in tree])
            self.graph.set_history(track.cpu, track.gpu)
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

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.height() / max(self.rows, 1)
        p.setFont(mono(9))
        val_w = 74.0
        for i, (name, _pid, value, icon_key) in enumerate(self.items):
            y = i * h
            frac = min(value / self.scale, 1.0) if self.scale else 0.0
            col = QColor(self.color)
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
                       f"{value:,.0f}{self.unit}".replace(",", " "))
        p.end()


class Dashboard(QWidget):
    root_requested = Signal()

    def __init__(self, ncpu: int, history: ProcHistory | None = None, parent=None) -> None:
        super().__init__(parent)
        self.ncpu = ncpu
        self.history = history
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(10)

        # -- header: what machine is this, and the entry point to root -----
        head = QHBoxLayout()
        head.setSpacing(12)
        self.lbl_machine = QLabel()
        self.lbl_machine.setFont(mono(10.5))
        self.lbl_machine.setTextFormat(Qt.TextFormat.RichText)
        head.addWidget(self.lbl_machine)
        head.addStretch(1)
        self.lbl_root_state = QLabel()
        self.lbl_root_state.setFont(mono(8))
        self.lbl_root_state.setStyleSheet(f"color: {theme.MUTED};")
        head.addWidget(self.lbl_root_state)
        self.btn_root = QPushButton("Root tasks")
        self.btn_root.setToolTip(
            "Actions that require privileges: raising priority, services, memory."
        )
        self.btn_root.clicked.connect(self.root_requested.emit)
        head.addWidget(self.btn_root)
        outer.addLayout(head)

        self._machine = (
            platform.node(),
            platform.release(),
            f"{psutil.cpu_count(logical=False) or ncpu}c/{ncpu}t",
        )
        self._render_machine(0.0)
        self.set_root_state(False)

        # -- tiles ---------------------------------------------------------
        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        self.t_cpu = StatTile("cpu", theme.CPU)
        self.t_cputemp = StatTile("cpu temp", theme.CPU)
        self.t_gpu = StatTile("gpu", theme.GPU)
        self.t_gputemp = StatTile("gpu temp", theme.GPU)
        self.t_mem = StatTile("memory", theme.MEM)
        self.t_vram = StatTile("vram", theme.GPU)
        for t in (self.t_cpu, self.t_cputemp, self.t_gpu, self.t_gputemp, self.t_mem, self.t_vram):
            tiles.addWidget(t)
        outer.addLayout(tiles)

        grid = QGridLayout()
        grid.setSpacing(10)
        outer.addLayout(grid, 1)

        # -- CPU -----------------------------------------------------------
        cpu_card = Card("processor", color=theme.CPU)
        self.g_cpu = Graph([("total", theme.CPU)], maximum=100.0)
        cpu_card.body.addWidget(self.g_cpu, 1)
        self.cores = CoreGrid()
        cpu_card.body.addWidget(self.cores)
        grid.addWidget(cpu_card, 0, 0)

        # -- GPU -----------------------------------------------------------
        gpu_card = Card("graphics card", color=theme.GPU)
        self.g_gpu = Graph([("sm", theme.GPU), ("vram", theme.DISK)], maximum=100.0)
        gpu_card.body.addWidget(self.g_gpu, 1)
        self.gpu_sub = QLabel("--")
        self.gpu_sub.setFont(mono(8))
        self.gpu_sub.setStyleSheet(f"color: {theme.MUTED};")
        gpu_card.body.addWidget(self.gpu_sub)
        grid.addWidget(gpu_card, 0, 1)

        # -- memory --------------------------------------------------------
        mem_card = Card("memory", color=theme.MEM)
        self.g_mem = Graph([("ram", theme.MEM), ("swap", theme.SWAP)], maximum=100.0)
        mem_card.body.addWidget(self.g_mem, 1)
        self.mem_sub = QLabel("--")
        self.mem_sub.setFont(mono(8))
        self.mem_sub.setStyleSheet(f"color: {theme.MUTED};")
        mem_card.body.addWidget(self.mem_sub)
        grid.addWidget(mem_card, 1, 0)

        # -- I/O -----------------------------------------------------------
        io_card = Card("network & disk", color=theme.NET)
        self.g_net = Graph([("net ↓", theme.NET), ("net ↑", theme.CPU)], maximum=None, fill=False)
        self.g_net.set_formatter(lambda v: f"{human_bytes(v)}/s")
        io_card.body.addWidget(self.g_net, 1)
        self.g_disk = Graph([("disk r", theme.DISK), ("disk w", theme.SWAP)],
                            maximum=None, fill=False)
        self.g_disk.set_formatter(lambda v: f"{human_bytes(v)}/s")
        io_card.body.addWidget(self.g_disk, 1)
        grid.addWidget(io_card, 1, 1)

        # -- game ----------------------------------------------------------
        self.game = GameCard(ncpu)
        grid.addWidget(self.game, 2, 0, 1, 2)

        # -- top lists -----------------------------------------------------
        top_card = Card("top processes")
        row = QHBoxLayout()
        row.setSpacing(18)
        cpu_col = QVBoxLayout()
        cpu_col.addWidget(self._sublabel("cpu · of all cores", theme.CPU))
        self.top_cpu = TopProcList(theme.CPU, "%")
        cpu_col.addWidget(self.top_cpu)
        mem_col = QVBoxLayout()
        mem_col.addWidget(self._sublabel("memory", theme.MEM))
        self.top_mem = TopProcList(theme.MEM, " MB")
        mem_col.addWidget(self.top_mem)
        gpu_col = QVBoxLayout()
        gpu_col.addWidget(self._sublabel("vram", theme.GPU))
        self.top_gpu = TopProcList(theme.GPU, " MB")
        gpu_col.addWidget(self.top_gpu)
        for col in (cpu_col, mem_col, gpu_col):
            row.addLayout(col, 1)
        top_card.body.addLayout(row)
        grid.addWidget(top_card, 3, 0, 1, 2)

        grid.setRowStretch(0, 3)
        grid.setRowStretch(1, 3)
        grid.setRowStretch(2, 2)
        grid.setRowStretch(3, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

    def game_name(self) -> str:
        """The running game's name, "" without one; for the tray."""
        return self.game.name if self.game.pid else ""

    def _render_machine(self, uptime_s: float) -> None:
        """Header line in the same role split as the rest: yellow highlights the
        machine itself, the rest recedes in brightness."""
        node, release, cores = self._machine
        sep = f"<span style='color:{theme.FAINT}'>&nbsp;&nbsp;·&nbsp;&nbsp;</span>"
        up = (f"{int(uptime_s // 86400)}d "
              f"{int(uptime_s % 86400 // 3600):02d}:{int(uptime_s % 3600 // 60):02d}")
        self.lbl_machine.setText(
            f"<span style='color:{theme.ACCENT}; font-size:11pt; font-weight:700'>"
            f"{node}</span>{sep}"
            f"<span style='color:{theme.TEXT}'>{release}</span>{sep}"
            f"<span style='color:{theme.MEM}'>{cores}</span>{sep}"
            f"<span style='color:{theme.MUTED}'>up {up}</span>"
        )

    def set_root_state(self, elevated: bool) -> None:
        """Colours the button as soon as root actions are active -- that should be visible."""
        if elevated:
            self.btn_root.setObjectName("accent")
            self.lbl_root_state.setText("root actions active")
            self.lbl_root_state.setStyleSheet(f"color: {theme.ACCENT};")
        else:
            self.btn_root.setObjectName("")
            self.lbl_root_state.setText("")
        self.btn_root.style().unpolish(self.btn_root)
        self.btn_root.style().polish(self.btn_root)

    @staticmethod
    def _sublabel(text: str, color: str = theme.LABEL) -> QLabel:
        lbl = QLabel(text.upper())
        f = lbl.font()
        f.setPointSize(7)
        f.setBold(True)
        lbl.setFont(f)
        lbl.setStyleSheet(f"color: {color};")
        return lbl

    # ------------------------------------------------------------------
    def update_view(self, snap: Snapshot) -> None:
        s = snap.system
        self._render_machine(time.time() - psutil.boot_time())
        self.g_cpu.push(s.cpu_percent)
        self.cores.set_values(s.per_core)
        self.t_cpu.set(f"{s.cpu_percent:.0f}%", f"{s.freq_mhz:.0f} MHz · load {s.load[0]:.2f}",
                       theme.heat(s.cpu_percent).name())
        if s.cpu_temp_c:
            self.t_cputemp.set(f"{s.cpu_temp_c:.0f}°", "Tctl",
                               theme.heat(min(s.cpu_temp_c, 100)).name())

        if s.gpu:
            g = s.gpu
            self.g_gpu.push(g.util, g.mem_pct)
            self.t_gpu.set(f"{g.util:.0f}%", g.name.replace("NVIDIA GeForce ", ""),
                           theme.heat(g.util).name())
            self.t_gputemp.set(f"{g.temp_c:.0f}°", f"{g.fan_pct:.0f}% fan",
                               theme.heat(min(g.temp_c * 1.15, 100)).name())
            self.t_vram.set(f"{g.mem_used_mb / 1024:.1f} G",
                            f"of {g.mem_total_mb / 1024:.0f} G · {g.mem_pct:.0f}%")
            self.gpu_sub.setText(
                f"{g.power_w:.0f} W  ·  {g.clock_mhz:.0f} MHz  ·  "
                f"{g.mem_used_mb:.0f}/{g.mem_total_mb:.0f} MB"
            )
        else:
            self.gpu_sub.setText("no GPU telemetry available")

        swap_pct = 100.0 * s.swap_used / s.swap_total if s.swap_total else 0.0
        self.g_mem.push(s.mem_pct, swap_pct)
        self.t_mem.set(f"{s.mem_used / 2**30:.1f} G",
                       f"of {s.mem_total / 2**30:.0f} G · {s.mem_pct:.0f}%",
                       theme.heat(s.mem_pct).name())
        self.mem_sub.setText(
            f"free {s.mem_available / 2**30:.1f} G  ·  swap "
            f"{s.swap_used / 2**30:.1f}/{s.swap_total / 2**30:.0f} G  ·  "
            f"{s.proc_count} processes, {s.thread_count} threads"
        )

        self.g_net.push(s.net_rx_bps, s.net_tx_bps)
        self.g_disk.push(s.disk_r_bps, s.disk_w_bps)

        procs = snap.procs
        self.game.update_view(procs, self.history)
        # Shown as a share of the whole machine, like the CPU tile above it;
        # "135%" (top's one-core notation) reads as an error to most people.
        self.top_cpu.set_items(
            [(p.display_name, p.pid, p.cpu_percent / self.ncpu, p.icon)
             for p in sorted(procs, key=lambda x: x.cpu_percent, reverse=True)[:5]],
            scale=100.0,
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
