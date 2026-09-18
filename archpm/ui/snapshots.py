"""The Snapshots page: what Snapper or Timeshift keeps, grouped by who took
it (yours on top, then pacman's, then a timer's) with a count on each
header, newest first inside a group; a pacman transaction is one row that
opens to its before and after. A button to take one and one per snapshot
to delete.

The list is read when the page opens and on its button, never on the
sampling cycle (the failed services check's pattern). The plain read comes
first; when the tool refuses a plain user, which Snapper does unless its
config names them and Timeshift always does, the button reads through the
root helper. Taking and deleting go through the helper every time. No
rollback: restoring changes what the machine boots and stays with the tool.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QProcess, QRegularExpression, Qt, QThread, Signal, Slot
from PySide6.QtGui import QFontMetrics, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import snapshots
from ..actions import ActionError
from ..helptext import CANNOT_UNDO, plural
from ..root.client import HELPER, RootClient, check
from ..snapshots import (
    ARCHPM, BY_HAND, PACMAN, PACMANS, SCHEDULED, SNAPPER, TIMED, TIMELINE, TIMESHIFT, YOURS, Pair,
)
from . import theme
from .navrail import kind_icon
from .widgets import BoxedList, FlowLayout, ListRow, human_bytes, mono, scrolling

ORIGIN_ICON = {PACMAN: "pacman", TIMELINE: "timer", SCHEDULED: "timer",
               ARCHPM: "person", BY_HAND: "person"}
ORIGIN_TIP = {PACMAN: "Taken by snap-pac around a pacman transaction",
              TIMELINE: "Taken by Snapper's timeline timer",
              SCHEDULED: "Taken by Timeshift's schedule",
              ARCHPM: "Taken from this page", BY_HAND: "Taken by a person, by hand"}
GROUP_TIP = {YOURS: "Snapshots you took, from this page or by hand.",
             PACMANS: {SNAPPER: "snap-pac's pair around each pacman transaction, one row per "
                                "transaction: click it for the before and the after.",
                       TIMESHIFT: "Timeshift's autosnap before each pacman transaction."},
             TIMED: {SNAPPER: "Snapper's timeline timer.", TIMESHIFT: "Timeshift's schedule."}}
ICON = 16
CHEVRON = 12
NO_DESCRIPTION = "no description"
LAST_ONE = ("The last snapshot stays: ArchPM does not delete the only way back. "
            "Take another one first.")


class _Read(QThread):
    """Detection and the plain read: two or three short commands, off the UI thread."""
    done = Signal(object, object)

    def run(self) -> None:
        setup = snapshots.detect()
        self.done.emit(setup, snapshots.read_as_user(setup))


class SnapshotsView(QWidget):
    status = Signal(str)
    help_requested = Signal(str)

    def __init__(self, client: RootClient, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.setup: snapshots.Setup | None = None
        self.listing: snapshots.Listing | None = None
        self._thread: _Read | None = None
        self._proc: QProcess | None = None
        self._pending: tuple = ()      # ("list",) | ("create",) | ("delete", snapshot)
        self._t0 = 0.0
        self._open: set[tuple[str, str]] = set()   # (config, before's id) of open pairs
        self._pairs: dict[tuple[str, str], tuple[ListRow, QLabel, list[ListRow]]] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(*theme.page_margins())
        outer.setSpacing(theme.CARD_GAP)

        head = FlowLayout(spacing=12)
        title = QLabel("Snapshots")
        title.setFont(theme.font("title", bold=True))
        head.addWidget(title)
        self.lbl_state = QLabel("")
        theme.style(self.lbl_state, "color: {MUTED};")
        head.addWidget(self.lbl_state)
        head.addStretch(1)
        self.btn_create = QPushButton("Take a snapshot…")
        self.btn_create.setToolTip("Takes a snapshot of the system now, through the root helper. "
                                   "It is kept until you delete it.")
        self.btn_create.clicked.connect(self._create)
        self.btn_create.hide()
        head.addWidget(self.btn_create)
        self.btn_read = QPushButton("Refresh")
        self.btn_read.setToolTip("Reads the list again. This and opening the page are the only "
                                 "times it is read; it is not on a timer.")
        self.btn_read.clicked.connect(self.read)
        self.btn_read.hide()
        head.addWidget(self.btn_read)
        outer.addLayout(head)

        self.list = BoxedList("", "")
        page = QWidget()
        groups = QVBoxLayout(page)
        groups.setContentsMargins(0, 0, 0, 0)
        groups.addWidget(self.list)
        groups.addStretch(1)
        outer.addWidget(scrolling(page), 1)

    # -- reading -------------------------------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.listing is None and self._thread is None:
            self.read()

    def read(self) -> None:
        """The plain read first. Once the list has been read as root, the
        button reads as root again: polkit keeps the authentication for a
        few minutes, so that is silent, and the plain read would only be
        refused again."""
        if self._proc is not None or self._thread is not None:
            return
        if self.listing is not None and self.listing.as_root:
            self.read_root()
            return
        self.lbl_state.setText("reading…")
        self._thread = _Read(self)
        self._thread.done.connect(self._plain_done)
        self._thread.finished.connect(self._thread_done)
        self._thread.start()

    @Slot()
    def _thread_done(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None

    @Slot(object, object)
    def _plain_done(self, setup, listing) -> None:
        self.setup = setup
        self._show(listing)

    def read_root(self) -> None:
        """Through the helper: pkexec asks for the password the first time."""
        if self.setup is None or not check().ready:
            return
        self.lbl_state.setText("reading as root…")
        self._run_helper(("list",), "snapshots-list")

    def _show(self, listing: snapshots.Listing) -> None:
        self.listing = listing
        self._explain()
        self._fill()

    # -- what the page says ------------------------------------------------------------
    def situation(self) -> list[str]:
        """The lines above the list: which tool, what reads without root,
        what needs the helper, how many the boot menu offers, and that
        restoring is done elsewhere."""
        setup, listing, st = self.setup, self.listing, check()
        if setup is None or listing is None:
            return []
        if not setup.tool:
            return ["No snapshot tool found: neither Snapper nor Timeshift is installed on "
                    "this machine."]
        name = "Snapper" if setup.tool == SNAPPER else "Timeshift"
        lines = []
        if setup.tool == SNAPPER and setup.timeshift:
            lines.append("Snapper and Timeshift are both installed; ArchPM shows Snapper's.")
        helper_missing = f"the root helper is not installed ({HELPER})"
        if listing.needs_root and not listing.as_root:
            why = ("Snapper keeps its list for root on this machine: its config names no "
                   "user in ALLOW_USERS or ALLOW_GROUPS." if setup.tool == SNAPPER
                   else "Timeshift keeps its list for root.")
            if st.ready:
                lines.append(f"{why} Read snapshots reads it through the root helper and asks "
                             "for your password once; the next few minutes need none. Taking "
                             "and deleting go the same way.")
            else:
                lines.append(f"{why} Reading it, taking one and deleting one need the root "
                             f"helper, and {helper_missing}.")
        elif listing.as_root:
            lines.append(f"Read as root through the helper, since {name} keeps its list for "
                         "root on this machine. Taking and deleting go the same way.")
        elif st.ready:
            lines.append(f"{name}'s list reads without root. Taking and deleting a snapshot go "
                         "through the root helper and ask for your password.")
        else:
            lines.append(f"{name}'s list reads without root. Taking and deleting a snapshot need "
                         f"the root helper, and {helper_missing}.")
        if listing.snapshots and not listing.sized:
            lines.append("No sizes: Snapper reports what a snapshot holds only when btrfs quota "
                         "is on, and it is off here." if setup.tool == SNAPPER
                         else "No sizes: Timeshift does not report them.")
        if any(isinstance(e, Pair) for e in snapshots.fold(listing.snapshots)):
            lines.append("A pacman transaction is one row: click it for its before and after.")
        if setup.limine_entries and listing.snapshots:
            lines.append(f"The Limine boot menu offers the newest "
                         f"{plural(setup.limine_entries, 'snapshot')} of these.")
        lines.append("Restoring is not done here: it changes what the machine boots, so it "
                     "stays outside ArchPM. " + snapshots.restore_advice(setup))
        return lines

    def _explain(self) -> None:
        setup, listing, st = self.setup, self.listing, check()
        self.list.set_description("<br>".join(self.situation()))
        has_tool = bool(setup and setup.tool)
        self.btn_create.setVisible(has_tool and st.ready)
        # the read button: the plain read when that works, the helper when
        # it is refused and the helper is there; nothing when neither
        readable = has_tool and (not listing.needs_root or st.ready)
        self.btn_read.setVisible(readable)
        self.btn_read.setText("Read snapshots" if listing.needs_root and not listing.as_root
                              else "Refresh")
        if listing.error:
            self.lbl_state.setText(listing.error)
            theme.style(self.lbl_state, "color: {WARN};")
            return
        theme.style(self.lbl_state, "color: {MUTED};")
        if not has_tool or (listing.needs_root and not listing.as_root):
            self.lbl_state.setText("")
            return
        when = time.strftime("%H:%M:%S", time.localtime(listing.taken_at))
        text = f"read at {when} in {listing.took_ms:.0f} ms"
        if listing.as_root:
            text += f" as root (the whole helper call {listing.call_ms:.0f} ms)"
        self.lbl_state.setText(text)

    def _fill(self) -> None:
        self.list.clear()
        self._pairs = {}
        setup, listing, st = self.setup, self.listing, check()
        if setup is None or listing is None or not setup.tool:
            return
        if listing.needs_root and not listing.as_root:
            return
        name = "Snapper" if setup.tool == SNAPPER else "Timeshift"
        if not listing.snapshots:
            if not listing.error:
                row = ListRow(f"{name} is installed and has no snapshots yet.")
                row.dim("MUTED")
                self.list.add_row(row)
            return
        entries = snapshots.fold(listing.snapshots)
        metrics = QFontMetrics(mono("body"))
        widths = (metrics.horizontalAdvance("999.9 MB"),
                  max(metrics.horizontalAdvance(e.label) for e in entries),
                  QPushButton("Delete…").sizeHint().width() if st.ready else 0)
        last = len(listing.snapshots) <= 1
        slot = any(isinstance(e, Pair) for e in entries)   # the chevron column, for every row
        for group, members in snapshots.grouped(entries):
            header = ListRow()
            header.make_header()
            header.set_count(group, len(members))
            tip = GROUP_TIP[group]
            tip = tip if isinstance(tip, str) else tip[setup.tool]
            pairs = sum(1 for e in members if isinstance(e, Pair))
            if pairs:
                tip += (f" {plural(len(members), 'row')}, "
                        f"{plural(len(members) + pairs, 'snapshot')}.")
            header.setToolTip(tip)
            self.list.add_row(header)
            for e in members:
                if isinstance(e, Pair):
                    self._add_pair(e, widths, last, st.ready)
                else:
                    self.list.add_row(self._row(e, widths, last, st.ready, slot=slot))

    def _icon(self, origin: str) -> QLabel:
        icon = QLabel()
        icon.setFixedSize(ICON + 4, ICON + 4)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pm = kind_icon(ORIGIN_ICON.get(origin, "person")).pixmap(ICON, ICON)
        if not pm.isNull():
            icon.setPixmap(pm)
        icon.setToolTip(ORIGIN_TIP.get(origin, ""))
        return icon

    @staticmethod
    def _chevron(opened: bool) -> QLabel:
        lbl = QLabel()
        lbl.setFixedSize(CHEVRON + 4, CHEVRON + 4)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pm = kind_icon("collapse" if opened else "expand").pixmap(CHEVRON, CHEVRON)
        if pm.isNull():
            lbl.setText("▾" if opened else "▸")
        else:
            lbl.setPixmap(pm)
        return lbl

    @staticmethod
    def _prefix(*widgets: QWidget) -> QWidget:
        """The chevron slot and the origin icon side by side, so the titles
        of every row start in one column; a half gets one more empty slot,
        which puts it a level under its pair."""
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        for w in widgets:
            lay.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)
        return box

    @staticmethod
    def _slot(size: int) -> QWidget:
        w = QWidget()
        w.setFixedSize(size + 4, size + 4)
        return w

    @staticmethod
    def _columns(e, widths: tuple) -> tuple[QLabel, QLabel]:
        """The number and the size, in columns of one width each."""
        size_w, num_w, _btn_w = widths
        num = QLabel(e.label)
        theme.style(num, "color: {MUTED}; font-family: monospace;")
        num.setMinimumWidth(num_w)
        size = QLabel(human_bytes(e.size) if e.size is not None else "")
        theme.style(size, "font-family: monospace;")
        size.setMinimumWidth(size_w)
        size.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return num, size

    def _row(self, s: snapshots.Snapshot, widths: tuple, last: bool, ready: bool,
             half: bool = False, slot: bool = False) -> ListRow:
        """One snapshot: its origin's icon, when and who, the description,
        the number, the size and the Delete button. With `slot` an empty
        chevron slot in front, so the row's title lines up with a pair's;
        a half of a pair sits one level further in."""
        num, size = self._columns(s, widths)
        size.setToolTip("What this snapshot holds that no other one does"
                        if s.size is not None else "")
        suffix: list[QWidget] = [num, size]
        if ready:
            btn = QPushButton("Delete…")
            btn.setObjectName("danger")
            btn.setAccessibleName(f"Delete snapshot {s.label}")
            if last:
                btn.setEnabled(False)
                btn.setToolTip(LAST_ONE)
            else:
                btn.clicked.connect(lambda _=False, snap=s: self._delete(snap))
            suffix.append(btn)
        sub = s.description or NO_DESCRIPTION
        if s.pair and not half:
            sub += f"  ·  pair with #{s.pair}"
        icon = self._icon(s.origin)
        if half:
            icon = self._prefix(self._slot(CHEVRON), self._slot(ICON), icon)
        elif slot:
            icon = self._prefix(self._slot(CHEVRON), icon)
        row = ListRow(f"{s.when}  ·  {s.why}", sub, prefix=icon, suffix=suffix)
        if not s.description:
            theme.style(row.subtitle, "color: {FAINT}; font-size: {FONT_SMALL}pt;")
        row.setToolTip(f"{s.label}: {s.description or NO_DESCRIPTION}")
        return row

    def _add_pair(self, pair: Pair, widths: tuple, last: bool, ready: bool) -> None:
        """The transaction's row, then its two halves, hidden until the row
        is clicked. The row has no Delete of its own: each half keeps its
        own, so a pair is taken apart one snapshot at a time."""
        key = (pair.config, pair.pre.id)
        opened = key in self._open
        chevron = self._chevron(opened)
        num, size = self._columns(pair, widths)
        size.setToolTip("What the two together hold that no other snapshot does"
                        if pair.size is not None else "")
        suffix: list[QWidget] = [num, size]
        if ready:
            gap = QWidget()          # the Delete column, so the numbers line up
            gap.setFixedWidth(widths[2])
            suffix.append(gap)
        row = ListRow(f"{pair.when}  ·  {pair.why}", pair.description or NO_DESCRIPTION,
                      prefix=self._prefix(chevron, self._icon(PACMAN)), suffix=suffix)
        if not pair.description:
            theme.style(row.subtitle, "color: {FAINT}; font-size: {FONT_SMALL}pt;")
        row.setToolTip(f"{pair.pre.label} before and {pair.post.label} after: "
                       f"{pair.description or NO_DESCRIPTION}. Click for the two snapshots.")
        row.setAccessibleName(f"pacman transaction {pair.label}, "
                              + ("open" if opened else "closed"))
        row.set_activatable(True)
        row.activated.connect(lambda k=key: self._toggle(k))
        self.list.add_row(row)
        halves = []
        for s in pair.halves:
            child = self._row(s, widths, last, ready, half=True)
            self.list.add_row(child)
            self.list.set_shown(child, opened)
            halves.append(child)
        self._pairs[key] = (row, chevron, halves)

    def _toggle(self, key: tuple[str, str]) -> None:
        entry = self._pairs.get(key)
        if entry is None:
            return
        row, chevron, halves = entry
        opened = key not in self._open
        (self._open.add if opened else self._open.discard)(key)
        pm = kind_icon("collapse" if opened else "expand").pixmap(CHEVRON, CHEVRON)
        if pm.isNull():
            chevron.setText("▾" if opened else "▸")
        else:
            chevron.setPixmap(pm)
        row.setAccessibleName(row.accessibleName().rsplit(", ", 1)[0]
                              + (", open" if opened else ", closed"))
        for child in halves:
            self.list.set_shown(child, opened)

    # -- the helper ------------------------------------------------------------------------
    def _run_helper(self, pending: tuple, *args: str) -> None:
        if self._proc is not None:
            return
        self._pending = pending
        self._t0 = time.perf_counter()
        self.btn_read.setEnabled(False)
        self.btn_create.setEnabled(False)
        self._proc = QProcess(self)
        self._proc.finished.connect(self._helper_done)
        argv = self.client.argv(*args)
        self._proc.start(argv[0], argv[1:])

    def _helper_done(self, code: int, *_) -> None:
        proc, self._proc = self._proc, None
        pending, self._pending = self._pending, ()
        self.btn_read.setEnabled(True)
        self.btn_create.setEnabled(True)
        if proc is None or not pending:
            return
        out = bytes(proc.readAllStandardOutput()).decode(errors="replace")
        err = bytes(proc.readAllStandardError()).decode(errors="replace")
        elapsed = (time.perf_counter() - self._t0) * 1000
        try:
            result = self.client.parse(code, out, err)
        except ActionError as exc:
            if pending[0] == "list":
                listing = self.listing or snapshots.Listing(tool=self.setup.tool if self.setup
                                                            else "")
                listing.error = f"Not read: {exc}"
                self._show(listing)
                listing.error = ""
            else:
                self.status.emit(f"Not done: {exc}")
            return
        if pending[0] == "list":
            listing = snapshots.from_helper(result)
            listing.call_ms = elapsed
            self._show(listing)
            return
        if pending[0] == "create":
            label = result.get("id", "")
            self.status.emit(f"Snapshot {'#' + label if label.isdigit() else label} taken"
                             if label else "Snapshot taken")
        else:
            snap = pending[1]
            left = result.get("remaining")
            self.status.emit(f"Snapshot {snap.label} deleted"
                             + (f", {plural(int(left), 'snapshot')} left" if left is not None
                                else ""))
        self._after_change()

    def _after_change(self) -> None:
        """The list again, by the route that worked: the helper's authentication
        is fresh, so a root read is silent."""
        if self.listing is not None and (self.listing.as_root or self.listing.needs_root):
            self.read_root()
        else:
            self.read()

    # -- taking one -------------------------------------------------------------------------
    def _config(self) -> str:
        if self.setup is None:
            return ""
        if self.setup.tool == SNAPPER:
            return self.setup.configs[0] if self.setup.configs else "root"
        return TIMESHIFT

    def _create(self) -> None:
        if self.setup is None or not self.setup.tool or self._proc is not None:
            return
        dlg = QInputDialog(self)
        dlg.setWindowTitle("Take a snapshot")
        dlg.setInputMode(QInputDialog.InputMode.TextInput)
        dlg.setLabelText(
            "A snapshot of the system as it is now, kept until you delete it.<br>"
            "Description, so you know later why it exists. Letters, digits, space, dot, "
            f"underscore and hyphen, up to {snapshots.DESCRIPTION_MAX}; anything else is dropped."
        )
        dlg.setOkButtonText("Take it")
        edit = dlg.findChild(QLineEdit)
        if edit is not None:
            edit.setValidator(QRegularExpressionValidator(
                QRegularExpression(snapshots.DESCRIPTION_RE.pattern), edit))
            edit.setMaxLength(snapshots.DESCRIPTION_MAX)
            edit.setPlaceholderText("before nvidia 580")
        if dlg.exec() != QInputDialog.DialogCode.Accepted:
            return
        desc = snapshots.sanitise(dlg.textValue())
        args = ["snapshots-create", self._config()]
        if desc:
            args.append(desc)
        self.status.emit("Taking a snapshot…")
        self._run_helper(("create",), *args)

    # -- deleting one -------------------------------------------------------------------------
    def confirmation(self, snap: snapshots.Snapshot) -> str:
        """What is lost and what remains: the snapshot itself, its place in
        the order, and the range that stays."""
        rows = self.listing.snapshots if self.listing else [snap]
        left = snapshots.remaining(snap, rows)
        where = snapshots.position(snap, rows)
        text = (f"<b>Delete {snap.label}?</b><br>{snap.when}, {snap.why}<br>"
                f"{snap.description or NO_DESCRIPTION}<br><br>")
        home = "the system" if snap.config in ("root", TIMESHIFT) else snap.config
        text += f"Lost: {home} as it was at that moment, and the way back to it."
        if snap.pair:
            half = "after" if snap.kind == "pre" else "before"
            text += (f" Its pair #{snap.pair} (the {half} half) stays; the comparison "
                     "between the two goes.")
        if where:
            text += f"<br>This is {where} snapshot."
        if left:
            text += (f"<br>Left after it: {plural(len(left), 'snapshot')}, "
                     f"from {left[-1].when} to {left[0].when}.")
        return text + f"<br><br>{CANNOT_UNDO}"

    def _delete(self, snap: snapshots.Snapshot) -> None:
        if self._proc is not None or self.listing is None:
            return
        if len(self.listing.snapshots) <= 1:
            self.status.emit(LAST_ONE)
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Delete this snapshot?")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(self.confirmation(snap))
        delete = box.addButton("Delete", QMessageBox.ButtonRole.DestructiveRole)
        keep = box.addButton("Keep", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(keep)
        box.exec()
        if box.clickedButton() is not delete:
            return
        self.status.emit(f"Deleting {snap.label}…")
        self._run_helper(("delete", snap), "snapshots-delete", snap.config, snap.id)
