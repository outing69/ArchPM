"""The Network tab: who talks to the internet, what listens, and over which wire."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
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
from .widgets import Card, ElidedLabel, FlowLayout, app_icon, human_bytes, mono

COL_NAME, COL_CONNS, COL_RX, COL_TX, COL_LISTEN, COL_INFO = range(6)
HEADERS = ["Program", "Connections", "Download", "Upload", "Listening", "Details"]
HINT_KEYS = ["net.program", "net.connections", "net.download", "net.upload", "net.listening",
             "net.details"]
RIGHT = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


def _rate(v: float) -> str:
    return f"{human_bytes(v)}/s" if v >= 1024 else ("" if v < 1 else f"{v:.0f} B/s")


# Below this page width the interfaces and the open doors stand one under
# the other instead of side by side.
ONE_COLUMN_BELOW = 640


class NetworkView(QWidget):
    status = Signal(str)
    help_requested = Signal(str)

    def __init__(self, services, parent=None) -> None:
        super().__init__(parent)
        self.service = services              # port -> name
        self._last: NetSnapshot | None = None
        self._expanded: set[str] = set()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(*theme.page_margins())
        outer.setSpacing(theme.CARD_GAP)

        head = FlowLayout(spacing=12)   # wraps when the window is narrow
        title = QLabel("Who is talking to the network")
        title.setFont(theme.font("title", bold=True))
        head.addWidget(title)
        self.lbl_state = QLabel("")
        theme.style(self.lbl_state, "color: {MUTED};")
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
        theme.style(hint, "color: {MUTED};")
        outer.addWidget(hint)

        # Two cards side by side, one under the other when the window is narrow.
        self.top = QGridLayout()
        self.top.setSpacing(theme.CARD_GAP)
        self.card_if = Card("interfaces", color="NET")
        self.grid_if = QGridLayout()
        self.grid_if.setHorizontalSpacing(theme.CARD_GAP)
        self.grid_if.setVerticalSpacing(3)
        self.card_if.body.addLayout(self.grid_if)
        hints.attach(self.card_if, "net.interfaces", self.help_requested.emit)
        self.card_doors = Card("open doors", color="WARN")
        self.lbl_doors = QLabel("")
        self.lbl_doors.setWordWrap(True)
        self.lbl_doors.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_doors.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.card_doors.body.addWidget(self.lbl_doors)
        hints.attach(self.card_doors, "net.doors", self.help_requested.emit)
        self._columns = 0
        self._place_cards(2)
        outer.addLayout(self.top)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(HEADERS)
        theme.style(self.tree, "QTreeWidget {{ border: 1px solid {BORDER};"
                               " border-radius: {RADIUS_CARD}px; }}"
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
        self.tree.itemExpanded.connect(lambda i: self._toggled(i, True))
        self.tree.itemCollapsed.connect(lambda i: self._toggled(i, False))
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

    def _place_cards(self, cols: int) -> None:
        if cols == self._columns:
            return
        while self.top.count():
            self.top.takeAt(0)
        for i, card in enumerate((self.card_if, self.card_doors)):
            self.top.addWidget(card, i // cols, i % cols)
        for c in range(2):
            self.top.setColumnStretch(c, 1 if c < cols else 0)
        self._columns = cols

    def columns(self) -> int:
        return self._columns

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_cards(1 if event.size().width() < ONE_COLUMN_BELOW else 2)

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
            name.setFont(mono("body", bold=True))
            theme.text(name, "NET" if i.up else "FAINT")
            state = QLabel(("up" if i.up else "down") + ("  ·  VPN" if i.vpn else ""))
            theme.text(state, "OK" if i.up else "FAINT")
            # Both can be squeezed: an address or a rate must not hold the
            # window open, and the value changes with the traffic.
            addr = ElidedLabel(i.addr)
            theme.style(addr, "color: {MUTED};")
            addr.setFont(mono("small"))
            rates = ElidedLabel(f"↓ {_rate(i.rx_bps) or '0 B/s'}   ↑ {_rate(i.tx_bps) or '0 B/s'}"
                                if i.up else "")
            rates.setFont(mono("body"))
            for col, w in enumerate((name, state, addr, rates)):
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

        # programs and their connections, grouped by program name; a program
        # whose sockets sit in several processes gets one row per process in
        # between, so Brave shows which of its processes holds what
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
            if q and q not in name.lower() and not any(self._matches(q, p, name) for p in members):
                continue
            rows.append((name, members, conns, rx, tx, estab, listen))
        rows.sort(key=lambda r: (-(r[3] + r[4]), -r[5], r[0].lower()))

        scroll = self.tree.verticalScrollBar().value()
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        for name, members, conns, rx, tx, estab, listen in rows:
            if len(members) == 1:
                info = f"{len(conns)} socket(s), pid {members[0].pid}"
            else:
                info = f"{len(conns)} socket(s) in {len(members)} processes"
            top = self._row(name, estab, rx, tx, listen, info, conns)
            top.setData(COL_NAME, Qt.ItemDataRole.UserRole, name)
            proc = self._procs.get(members[0].pid)
            if proc is not None and proc.icon:
                icon = app_icon(proc.icon)
                if not icon.isNull():
                    top.setIcon(COL_NAME, icon)
            open_mids = []
            if len(members) == 1:
                self._add_sockets(top, members[0], name, q)
            else:
                ordered = sorted(members,
                                 key=lambda p: (-(p.rx_bps + p.tx_bps), -p.established, p.pid))
                for p in ordered:
                    if q and q not in name.lower() and not self._matches(q, p, name):
                        continue
                    key = f"{name}/{p.pid}"
                    opened = key in self._expanded     # only by hand, never by a filter
                    brief = f"pid {p.pid} · {len(p.conns)} socket(s)"
                    ports = self._ports(p)
                    info = brief if opened or not ports else f"{brief} · {ports}"
                    mid = self._row(self._proc_name(p), p.established, p.rx_bps, p.tx_bps,
                                    len(p.listening), info, p.conns)
                    mid.setData(COL_NAME, Qt.ItemDataRole.UserRole, key)
                    mid.setData(COL_INFO, Qt.ItemDataRole.UserRole, (brief, ports))
                    self._add_sockets(mid, p, name, q)
                    top.addChild(mid)
                    if opened:
                        open_mids.append(mid)
            # expand only once in the tree: the signals fire then
            self.tree.addTopLevelItem(top)
            if name in self._expanded or q:     # a filter opens the programs, not their processes
                top.setExpanded(True)
            for mid in open_mids:
                mid.setExpanded(True)
        self.tree.verticalScrollBar().setValue(scroll)
        self.tree.setUpdatesEnabled(True)
        n_procs = len(net.procs)
        note = "" if net.tcp_rates else "  ·  ss not found: no speeds"
        self.lbl_state.setText(f"{n_procs} programs · {net.other_sockets} sockets of other users"
                               f"{note}")

    def _row(self, name: str, estab: int, rx: float, tx: float, listen: int, info: str,
             conns: list[Conn]) -> QTreeWidgetItem:
        """A program or process row: the counts and rates, the details muted,
        the listening count amber when one of the sockets is an open door."""
        item = QTreeWidgetItem([name, str(estab), _rate(rx), _rate(tx),
                                str(listen) if listen else "", info])
        for col in (COL_CONNS, COL_RX, COL_TX, COL_LISTEN):
            item.setTextAlignment(col, RIGHT)
        item.setForeground(COL_INFO, QColor(theme.MUTED))
        if listen:
            open_door = any(c.exposed for c in conns)
            item.setForeground(COL_LISTEN, QColor(theme.WARN if open_door else theme.MUTED))
        return item

    def _add_sockets(self, parent: QTreeWidgetItem, p: ProcNet, name: str, q: str) -> None:
        whole = not q or q in name.lower() or q in self._proc_name(p).lower() or q == str(p.pid)
        for c in sorted(p.conns, key=lambda c: (not c.listening, c.local_only, c.raddr, c.rport)):
            if not whole and q not in self._describe(c).lower():
                continue
            child = QTreeWidgetItem(["", "", "", "", "", self._describe(c)])
            child.setForeground(COL_INFO, QColor(theme.WARN if c.exposed else theme.TEXT))
            child.setFont(COL_INFO, mono("body"))
            parent.addChild(child)

    def _matches(self, q: str, p: ProcNet, name: str) -> bool:
        return (q in name.lower() or q in self._proc_name(p).lower() or q == str(p.pid)
                or any(q in self._describe(c).lower() for c in p.conns))

    def _toggled(self, item: QTreeWidgetItem, expanded: bool) -> None:
        key = item.data(COL_NAME, Qt.ItemDataRole.UserRole)
        if key is None:
            return
        (self._expanded.add if expanded else self._expanded.discard)(key)
        summary = item.data(COL_INFO, Qt.ItemDataRole.UserRole)
        if summary:                       # a process row: the ports only while collapsed
            brief, ports = summary
            item.setText(COL_INFO, brief if expanded or not ports else f"{brief} · {ports}")

    def _ports(self, p: ProcNet) -> str:
        """The ports of one process on one line: what it listens on, then the
        remote ports it talks to."""
        listen = sorted({c.lport for c in p.conns if c.listening})
        remote = sorted({c.rport for c in p.conns if c.raddr and not c.listening})
        parts = []
        if listen:
            parts.append("listening " + self._port_list(listen))
        if remote:
            parts.append("→ " + self._port_list(remote))
        return " · ".join(parts)

    def _port_list(self, ports: list[int], cap: int = 5) -> str:
        text = ", ".join(self._port(port) for port in ports[:cap])
        return text if len(ports) <= cap else f"{text} +{len(ports) - cap} more"

    def _proc_name(self, p: ProcNet) -> str:
        """The process's own name (brave, steamwebhelper), unlike the program's."""
        proc = self._procs.get(p.pid)
        if proc is not None and proc.name:
            return proc.name
        return p.name or f"pid {p.pid}"

    def _port(self, port: int) -> str:
        svc = self.service(port)
        return f"{port} ({svc})" if svc else str(port)

    def _name(self, p: ProcNet) -> str:
        proc: ProcSample | None = self._procs.get(p.pid)
        if proc is not None:
            return proc.display_name
        return p.name or f"pid {p.pid}"
