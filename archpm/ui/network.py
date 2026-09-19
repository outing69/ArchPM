"""The Network page: who talks to the internet, what listens, and over which wire.

The open doors card ends with the firewall's state, read-only: whether one
runs and which, what it does with incoming traffic no rule covers, and
which ports it opens to other machines. The doors say which programs
accept connections; the firewall says whether those doors are reachable
from outside, so the two answer one question together. Read when the page
opens and on the block's own Refresh, never on the sampling cycle (the
failed services check's pattern). ufw refuses a plain user, so on this
route the block reads through the root helper on request, the way the
Snapshots page does; without the helper it says the state needs it, the
way the Cleanup root rows do. ArchPM changes no rule and switches no
firewall on or off.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QProcess, Qt, QThread, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import firewall
from ..actions import ActionError, Cancelled
from ..helptext import plural
from ..model import ProcSample, Snapshot
from ..net import Conn, NetSnapshot, ProcNet
from ..root.client import HELPER, RootClient, check
from . import hints, theme
from .widgets import Card, ElidedLabel, FlowLayout, TextLink, app_icon, human_bytes, mono

COL_NAME, COL_CONNS, COL_RX, COL_TX, COL_LISTEN, COL_INFO = range(6)
HEADERS = ["Program", "Connections", "Download", "Upload", "Listening", "Details"]
HINT_KEYS = ["net.program", "net.connections", "net.download", "net.upload", "net.listening",
             "net.details"]
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def _rate(v: float) -> str:
    return f"{human_bytes(v)}/s" if v >= 1024 else ("" if v < 1 else f"{v:.0f} B/s")


# Below this page width the interfaces and the open doors stand one under
# the other instead of side by side.
ONE_COLUMN_BELOW = 640


class _ReadFirewall(QThread):
    """Detection and the plain read, off the UI thread: a handful of short
    commands and one file. A fault in either is handed to the page as the
    state's error, since an exception in a thread's run() goes nowhere."""
    done = Signal(object, object)

    def run(self) -> None:
        setup = firewall.Setup()
        try:
            setup = firewall.detect()
            state = firewall.read_as_user(setup)
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            state = firewall.State(tool=setup.tool, taken_at=time.time(),
                                   error=f"{type(exc).__name__}: {exc}")
        self.done.emit(setup, state)


class NetworkView(QWidget):
    status = Signal(str)
    help_requested = Signal(str)

    def __init__(self, services, client: RootClient | None = None, parent=None) -> None:
        super().__init__(parent)
        self.service = services              # port -> name
        self.client = client                 # None: the firewall block never reads
        self._last: NetSnapshot | None = None
        self._expanded: set[str] = set()
        self.fw_setup: firewall.Setup | None = None
        self.fw_state: firewall.State | None = None
        self._fw_thread: _ReadFirewall | None = None
        self._fw_proc: QProcess | None = None
        self._fw_t0 = 0.0

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
        # The firewall, set apart from the doors' sentence the way rows of a
        # boxed list are set apart: a hairline, then a head line with the
        # label and the one control right after it (the failed services
        # block's shape), then the three lines at most.
        self.sep_fw = QFrame()
        self.sep_fw.setFixedHeight(1)
        theme.style(self.sep_fw, "background: {BORDER};")
        self.sep_fw.hide()
        self.card_doors.body.addWidget(self.sep_fw)
        self.head_fw = QWidget()
        head_fw = QHBoxLayout(self.head_fw)
        head_fw.setContentsMargins(0, 0, 0, 0)
        head_fw.setSpacing(12)
        self.lbl_fw_title = QLabel("Firewall")
        theme.style(self.lbl_fw_title, "font-weight: 700;")
        head_fw.addWidget(self.lbl_fw_title)
        self.link_fw = TextLink()
        # its own width: a link, not a field, and the focus ring hugs the words
        self.link_fw.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.link_fw.activated.connect(self._fw_link)
        head_fw.addWidget(self.link_fw, 0, Qt.AlignmentFlag.AlignVCenter)
        head_fw.addStretch(1)
        self.head_fw.hide()
        self.card_doors.body.addWidget(self.head_fw)
        self.lbl_fw = QLabel("")
        self.lbl_fw.setWordWrap(True)
        self.lbl_fw.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_fw.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_fw.hide()
        self.card_doors.body.addWidget(self.lbl_fw)
        # The doors: their count on a line, one row per door under it, the
        # way a socket is a row under a program in the tree below. Past
        # FOLD_ABOVE the rows wait behind the count, which is then a link.
        self.lbl_fw_doors = TextLink()
        self.lbl_fw_doors.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.lbl_fw_doors.activated.connect(self._toggle_doors)
        self.lbl_fw_doors.hide()
        self.card_doors.body.addWidget(self.lbl_fw_doors, 0, Qt.AlignmentFlag.AlignLeft)
        self.rows_fw = QWidget()
        rows_fw = QVBoxLayout(self.rows_fw)
        rows_fw.setContentsMargins(self.tree_indent(), 0, 0, 0)
        rows_fw.setSpacing(2)
        self.rows_fw.hide()
        self.card_doors.body.addWidget(self.rows_fw)
        self._fw_open = False
        self._fw_block: firewall.Block | None = None
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
        if self.client is not None and self.fw_state is None and self._fw_thread is None:
            self.read_firewall()

    # -- the firewall ------------------------------------------------------------
    def read_firewall(self) -> None:
        """The plain read: detection, and the tool's own status where it
        answers a plain user. Never the helper by itself: that can ask for
        a password, and a page that opens must not."""
        if self._fw_thread is not None or self._fw_proc is not None:
            return
        self._fw_thread = _ReadFirewall(self)
        self._fw_thread.done.connect(self._fw_plain_done)
        self._fw_thread.finished.connect(self._fw_thread_done)
        self._fw_thread.start()

    @Slot()
    def _fw_thread_done(self) -> None:
        if self._fw_thread is not None:
            self._fw_thread.deleteLater()
            self._fw_thread = None

    @Slot(object, object)
    def _fw_plain_done(self, setup, state) -> None:
        self.set_firewall(setup, state)

    def read_firewall_root(self) -> None:
        """Through the helper: pkexec asks for the password the first time,
        and polkit keeps it for a few minutes, so a Refresh soon after is
        silent."""
        if self.client is None or self._fw_proc is not None or not check().ready:
            return
        self._fw_t0 = time.perf_counter()
        self.link_fw.set_plain("reading as root…", "MUTED")
        self._fw_proc = QProcess(self)
        self._fw_proc.finished.connect(self._fw_helper_done)
        self._fw_proc.errorOccurred.connect(self._fw_helper_failed)
        argv = self.client.argv("firewall-status")
        self._fw_proc.start(argv[0], argv[1:])

    def _fw_helper_failed(self, error) -> None:
        """pkexec could not be started at all: finished never comes, so the
        block would stay on "reading as root…" for good."""
        if error != QProcess.ProcessError.FailedToStart or self._fw_proc is None:
            return
        proc, self._fw_proc = self._fw_proc, None
        state = self.fw_state or firewall.State(tool=self.fw_setup.tool if self.fw_setup else "")
        state.error = f"the root helper could not be started ({proc.errorString()})"
        self.set_firewall(self.fw_setup or firewall.Setup(), state)

    def _fw_helper_done(self, code: int, *_) -> None:
        proc, self._fw_proc = self._fw_proc, None
        if proc is None or self.client is None:
            return
        out = bytes(proc.readAllStandardOutput()).decode(errors="replace")
        err = bytes(proc.readAllStandardError()).decode(errors="replace")
        elapsed = (time.perf_counter() - self._fw_t0) * 1000
        try:
            state = firewall.from_helper(self.client.parse(code, out, err, "firewall-status"))
            state.call_ms = elapsed
        except Cancelled:
            state = self.fw_state or firewall.State(tool=self.fw_setup.tool if self.fw_setup
                                                    else "")
            state.error = "cancelled, the firewall was not read"
        except ActionError as exc:
            state = self.fw_state or firewall.State(tool=self.fw_setup.tool if self.fw_setup
                                                    else "")
            state.error = str(exc)
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            state = self.fw_state or firewall.State()
            state.error = f"{type(exc).__name__}: {exc}"
        self.set_firewall(self.fw_setup or firewall.Setup(), state)

    def _fw_link(self) -> None:
        """Read the firewall when it needs root, Refresh by the route that
        worked otherwise."""
        st = self.fw_state
        if st is not None and (st.as_root or st.needs_root) and check().ready:
            self.read_firewall_root()
        else:
            self.read_firewall()

    def set_firewall(self, setup: firewall.Setup, state: firewall.State) -> None:
        """The block's text and link from a setup and a state; the tests
        hand these in directly."""
        self.fw_setup, self.fw_state = setup, state
        ready = check().ready and self.client is not None
        b = firewall.block(setup, state, self.service, helper_ready=ready,
                           helper_path=str(HELPER))
        self._fw_block = b
        # the summary lines, the error under them; the doors' count and rows
        # are widgets of their own so the rows can fold
        self.lbl_fw.setText("<br>".join(b.lines + ([b.error] if b.error else [])))
        for w in (self.sep_fw, self.head_fw, self.lbl_fw, self.link_fw):
            w.show()
        self._fill_doors(b)
        if state.needs_root and not state.as_root:
            if ready:
                self.link_fw.set_link("Read the firewall", "ACCENT")
                self.link_fw.setToolTip("Reads the firewall's state through the root helper. "
                                        "Nothing is changed. This and Refresh are the only "
                                        "times it is read; it is not on a timer.")
            else:
                self.link_fw.hide()
            return
        self.link_fw.set_link("Refresh", "ACCENT")
        when = time.strftime("%H:%M:%S", time.localtime(state.taken_at)) if state.taken_at \
            else ""
        cost = f"read at {when} in {state.took_ms:.0f} ms" if when else "not read yet"
        if state.as_root:
            cost += f" as root (the whole helper call {state.call_ms:.0f} ms)"
        self.link_fw.setToolTip(f"Reads the firewall's state again ({cost}). This and opening "
                                "the page are the only times it is read; it is not on a timer.")

    def _fill_doors(self, b: firewall.Block) -> None:
        lay = self.rows_fw.layout()
        while lay.count():
            item = lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not b.doors:
            self.lbl_fw_doors.hide()
            self.rows_fw.hide()
            return
        for text in b.rows:
            row = QLabel(text)
            row.setFont(mono("body"))
            row.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            # never squeezed below its line: a short window clips the card's
            # wrapped sentences, not the rows into one another
            row.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            lay.addWidget(row)
        self.lbl_fw_doors.show()
        self._show_doors()

    def _show_doors(self) -> None:
        """The count line: plain text over the rows when they are few, a
        link that opens and closes them when they are many."""
        b = self._fw_block
        if b is None or not b.doors:
            return
        if not b.folded:
            self.lbl_fw_doors.set_plain(b.doors, "TEXT")
            self.lbl_fw_doors.setToolTip("")
            self.rows_fw.show()
            return
        opened = self._fw_open
        self.lbl_fw_doors.set_link(f"{b.doors} {'▾' if opened else '▸'}", "ACCENT")
        self.lbl_fw_doors.setToolTip(f"{'Hides' if opened else 'Shows'} the {len(b.rows)} rows, "
                                     "one per door.")
        self.lbl_fw_doors.setAccessibleName(f"{b.doors}, {'open' if opened else 'closed'}")
        self.rows_fw.setVisible(opened)

    def _toggle_doors(self) -> None:
        self._fw_open = not self._fw_open
        self._show_doors()

    @staticmethod
    def tree_indent() -> int:
        return 18

    def firewall_text(self) -> str:
        """The block's lines as plain text, the doors' count line included
        when there is one, for the tests."""
        text = self.lbl_fw.text().replace("<br>", "\n")
        if self._fw_block is not None and self._fw_block.doors:
            text += "\n" + self._fw_block.doors
        return text

    def firewall_rows(self) -> list[str]:
        """The door rows as shown, for the tests; empty while folded."""
        lay = self.rows_fw.layout()
        if not self.rows_fw.isVisibleTo(self):
            return []
        return [lay.itemAt(i).widget().text() for i in range(lay.count())
                if lay.itemAt(i).widget() is not None]

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
                info = f"{plural(len(conns), 'socket')}, pid {members[0].pid}"
            else:
                info = f"{plural(len(conns), 'socket')} in {plural(len(members), 'process')}"
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
                    brief = f"pid {p.pid} · {plural(len(p.conns), 'socket')}"
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
        the listening count orange when one of the sockets is an open door."""
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
