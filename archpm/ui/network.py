"""The Network tab: who talks to the internet, what listens, and over which wire."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..model import ProcSample, Snapshot
from ..net import Conn, NetSnapshot, ProcNet
from . import hints, theme
from .widgets import Card, app_icon, human_bytes, mono

COL_NAME, COL_CONNS, COL_RX, COL_TX, COL_LISTEN, COL_INFO = range(6)
HEADERS = ["Program", "Connections", "Download", "Upload", "Listening", "Details"]
HINT_KEYS = ["net.program", "net.connections", "net.download", "net.upload", "net.listening",
             "net.details"]
RIGHT = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


def _rate(v: float) -> str:
    return f"{human_bytes(v)}/s" if v >= 1024 else ("" if v < 1 else f"{v:.0f} B/s")


class NetworkView(QWidget):
    status = Signal(str)
    help_requested = Signal(str)

    def __init__(self, services, parent=None) -> None:
        super().__init__(parent)
        self.service = services              # port -> name
        self._last: NetSnapshot | None = None
        self._expanded: set[str] = set()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(12)
        title = QLabel("Who is talking to the network")
        f = title.font()
        f.setPointSize(11)
        f.setBold(True)
        title.setFont(f)
        head.addWidget(title)
        self.lbl_state = QLabel("")
        self.lbl_state.setStyleSheet(f"color: {theme.MUTED};")
        head.addWidget(self.lbl_state)
        head.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by program, address or port…")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(280)
        self.search.textChanged.connect(lambda _: self._rebuild())
        head.addWidget(self.search)
        outer.addLayout(head)

        hint = QLabel(
            "Your programs and their connections, refreshed every five seconds. Download and "
            "upload are per program for TCP (web, downloads, updates); games mostly use UDP, "
            "which has no counters, so a game shows its connections but not a speed. Addresses "
            "are shown as they are; ArchPM never looks them up anywhere."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.MUTED};")
        outer.addWidget(hint)

        top = QHBoxLayout()
        top.setSpacing(10)
        self.card_if = Card("interfaces", color=theme.NET)
        self.grid_if = QGridLayout()
        self.grid_if.setHorizontalSpacing(16)
        self.grid_if.setVerticalSpacing(3)
        self.card_if.body.addLayout(self.grid_if)
        top.addWidget(self.card_if, 1)
        hints.attach(self.card_if, "net.interfaces", self.help_requested.emit)
        self.card_doors = Card("open doors", color=theme.WARN)
        self.lbl_doors = QLabel("")
        self.lbl_doors.setWordWrap(True)
        self.lbl_doors.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_doors.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.card_doors.body.addWidget(self.lbl_doors)
        top.addWidget(self.card_doors, 1)
        hints.attach(self.card_doors, "net.doors", self.help_requested.emit)
        outer.addLayout(top)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(HEADERS)
        self.tree.setStyleSheet(
            f"QTreeWidget {{ border: 1px solid {theme.BORDER}; border-radius: 10px; }}"
        )
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(18)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setSortingEnabled(False)
        header = self.tree.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_INFO, QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(True)
        for col, w in ((COL_NAME, 300), (COL_CONNS, 100), (COL_RX, 100), (COL_TX, 100),
                       (COL_LISTEN, 90)):
            self.tree.setColumnWidth(col, w)
        hints.header_tooltips(self.tree, HINT_KEYS)
        hints.attach_header(header, HINT_KEYS, self.help_requested.emit)
        self.tree.itemExpanded.connect(lambda i: self._expanded.add(i.text(COL_NAME)))
        self.tree.itemCollapsed.connect(lambda i: self._expanded.discard(i.text(COL_NAME)))
        outer.addWidget(self.tree, 1)

    # -- data -----------------------------------------------------------------
    def update_view(self, snap: Snapshot) -> None:
        if snap.net is None or snap.net is self._last:
            return
        self._last = snap.net
        self._procs = {p.pid: p for p in snap.procs}
        if self.isVisible():
            self._rebuild()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._last is not None:
            self._rebuild()

    def _describe(self, c: Conn) -> str:
        svc = self.service(c.rport if c.raddr else c.lport)
        svc = f" ({svc})" if svc else ""
        if c.listening:
            where = "every address" if c.exposed else ("this PC only" if c.local_only else c.laddr)
            return f"Listening on port {c.lport}{svc} · {c.proto} · {where}"
        if c.raddr:
            local = " · this PC" if c.local_only else ""
            return f"→ {c.raddr}:{c.rport}{svc} · {c.proto} · {c.state.lower()}{local}"
        return f"{c.proto} · {c.state.lower()} · port {c.lport}"

    def _rebuild(self) -> None:
        net = self._last
        if net is None:
            return
        q = self.search.text().strip().lower()

        # interfaces
        while self.grid_if.count():
            item = self.grid_if.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for r, i in enumerate(net.interfaces):
            name = QLabel(i.name)
            name.setFont(mono(9, bold=True))
            name.setStyleSheet(f"color: {theme.NET if i.up else theme.FAINT};")
            state = QLabel(("up" if i.up else "down") + ("  ·  VPN" if i.vpn else ""))
            state.setStyleSheet(f"color: {theme.OK if i.up else theme.FAINT};")
            addr = QLabel(i.addr)
            addr.setStyleSheet(f"color: {theme.MUTED};")
            addr.setFont(mono(8.5))
            rx = QLabel(f"↓ {_rate(i.rx_bps) or '0 B/s'}" if i.up else "")
            tx = QLabel(f"↑ {_rate(i.tx_bps) or '0 B/s'}" if i.up else "")
            for lbl in (rx, tx):
                lbl.setFont(mono(9))
            for col, w in enumerate((name, state, addr, rx, tx)):
                self.grid_if.addWidget(w, r, col)
        self.grid_if.setColumnStretch(2, 1)

        # open doors
        doors = []
        for p in net.procs.values():
            exposed = sorted({c.lport for c in p.conns if c.exposed})
            if exposed:
                ports = ", ".join(self._port(port) for port in exposed)
                doors.append(f"<b>{self._name(p)}</b> on {ports}")
        if doors:
            self.lbl_doors.setText(
                "Programs that accept connections from other devices on your network: "
                + "; ".join(doors) + ". Normal for things like KDE Connect and Steam; a "
                "program you do not recognise deserves a look.")
        else:
            self.lbl_doors.setText("No program is accepting connections from the network right "
                                   "now. Everything listening is reachable from this PC only.")

        # programs and their connections, grouped by program name
        groups: dict[str, list[ProcNet]] = {}
        for p in net.procs.values():
            groups.setdefault(self._name(p), []).append(p)
        rows = []
        for name, members in groups.items():
            conns = [c for p in members for c in p.conns]
            rx = sum(p.rx_bps for p in members)
            tx = sum(p.tx_bps for p in members)
            estab = sum(p.established for p in members)
            listen = sum(len(p.listening) for p in members)
            if q and q not in name.lower() and not any(
                    q in self._describe(c).lower() for c in conns):
                continue
            rows.append((name, members, conns, rx, tx, estab, listen))
        rows.sort(key=lambda r: (-(r[3] + r[4]), -r[5], r[0].lower()))

        scroll = self.tree.verticalScrollBar().value()
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        for name, members, conns, rx, tx, estab, listen in rows:
            pids = ", ".join(str(p.pid) for p in members[:4])
            top = QTreeWidgetItem([name, str(estab), _rate(rx), _rate(tx),
                                   str(listen) if listen else "",
                                   f"{len(conns)} socket(s), pid {pids}"])
            proc = self._procs.get(members[0].pid)
            if proc is not None and proc.icon:
                icon = app_icon(proc.icon)
                if not icon.isNull():
                    top.setIcon(COL_NAME, icon)
            for col in (COL_CONNS, COL_RX, COL_TX, COL_LISTEN):
                top.setTextAlignment(col, RIGHT)
            top.setForeground(COL_INFO, QColor(theme.MUTED))
            if listen:
                open_door = any(c.exposed for c in conns)
                top.setForeground(COL_LISTEN, QColor(theme.WARN if open_door else theme.MUTED))
            for c in sorted(conns, key=lambda c: (not c.listening, c.local_only, c.raddr, c.rport)):
                if q and q not in self._describe(c).lower() and q not in name.lower():
                    continue
                child = QTreeWidgetItem(["", "", "", "", "", self._describe(c)])
                child.setForeground(COL_INFO, QColor(theme.WARN if c.exposed else theme.TEXT))
                child.setFont(COL_INFO, mono(9))
                top.addChild(child)
            self.tree.addTopLevelItem(top)
            if name in self._expanded or q:
                top.setExpanded(True)
        self.tree.verticalScrollBar().setValue(scroll)
        self.tree.setUpdatesEnabled(True)
        n_procs = len(net.procs)
        note = "" if net.tcp_rates else "  ·  ss not found: no speeds"
        self.lbl_state.setText(f"{n_procs} programs · {net.other_sockets} sockets of other users"
                               f"{note}")

    def _port(self, port: int) -> str:
        svc = self.service(port)
        return f"{port} ({svc})" if svc else str(port)

    def _name(self, p: ProcNet) -> str:
        proc: ProcSample | None = self._procs.get(p.pid)
        if proc is not None:
            return proc.display_name
        return p.name or f"pid {p.pid}"
