"""The Cleanup tab: free up space by removing what programs rebuild anyway.

The first visit in a session explains what the tab does and does not delete,
then asks for the root password once (polkit) so the two root items can run.
Everything is listed with its size first; nothing is removed until the user
ticks items, presses the button and confirms the list.
"""
from __future__ import annotations

from PySide6.QtCore import QProcess, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..actions import ActionError
from ..cleanup import Cleaner, CleanupItem, human, running_owner
from ..helptext import CANNOT_UNDO
from ..root.client import RootClient, check
from . import theme
from .widgets import BoxedList, ElidedLabel, FlowLayout, ListRow, mono, scrolling


class _Scan(QThread):
    done = Signal(object)

    def __init__(self, cleaner: Cleaner, parent=None) -> None:
        super().__init__(parent)
        self.cleaner = cleaner

    def run(self) -> None:
        self.done.emit(self.cleaner.scan())


class _Empty(QThread):
    """Deleting gigabytes of small files takes seconds; keep the window alive."""
    progress = Signal(str)
    done = Signal(int)

    def __init__(self, cleaner: Cleaner, items: list[CleanupItem], parent=None) -> None:
        super().__init__(parent)
        self.cleaner = cleaner
        self.items = items

    def run(self) -> None:
        total = 0
        for item in self.items:
            freed, errors = self.cleaner.empty(item)
            total += freed
            self.progress.emit(f"  ✓ {item.name}: freed {human(freed)}")
            for e in errors:
                self.progress.emit(f"    ! {e}")
        self.done.emit(total)


class CleanupView(QWidget):
    status = Signal(str)
    help_requested = Signal(str)
    leave = Signal()   # the user did not want this tab after all

    def __init__(self, client: RootClient, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.cleaner = Cleaner()
        self.items: list[CleanupItem] = []
        self._acknowledged = False
        self._thread: QThread | None = None
        self._proc: QProcess | None = None
        self._queue: list[CleanupItem] = []
        self._procs: list = []          # latest process samples, for "running now"
        self._rescan_pending = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(*theme.page_margins())
        outer.setSpacing(theme.CARD_GAP)

        head = FlowLayout(spacing=12)   # wraps when the window is narrow
        title = QLabel("Free up space")
        title.setFont(theme.font("title", bold=True))
        head.addWidget(title)
        self.lbl_state = QLabel("")
        theme.style(self.lbl_state, "color: {MUTED};")
        head.addWidget(self.lbl_state)
        head.addStretch(1)
        self.lbl_total = QLabel("")
        self.lbl_total.setFont(mono("body", bold=True))
        head.addWidget(self.lbl_total)
        self.btn_scan = QPushButton("Scan again")
        self.btn_scan.clicked.connect(self.scan)
        head.addWidget(self.btn_scan)
        self.btn_clean = QPushButton("Remove selected…")
        self.btn_clean.setObjectName("danger")
        self.btn_clean.setEnabled(False)
        self.btn_clean.clicked.connect(self._clean)
        head.addWidget(self.btn_clean)
        outer.addLayout(head)

        # One boxed list, the page's note as its description; the page
        # scrolls as a whole and the log stays put underneath.
        self.list = BoxedList("", (
            "Everything listed here is something a program builds again by itself: caches, "
            "compiled shaders, thumbnails, old package versions, old logs. Removing it costs "
            "you a slower first start of that program (shaders recompile, previews regenerate), "
            "never your files, saves or settings. Tick what you want gone, press the button, "
            "and check the list once more before you confirm.<br>"
            "The sizes are read without root. Two items, the package cache and the system "
            "logs, need root to remove; your password is asked when you press Remove "
            "selected with one of them ticked, not before."
        ))
        self._checks: list[QCheckBox] = []     # one per item
        self._notes: list[QLabel] = []
        page = QWidget()
        groups = QVBoxLayout(page)
        groups.setContentsMargins(0, 0, 0, 0)
        groups.addWidget(self.list)
        groups.addStretch(1)
        outer.addWidget(scrolling(page), 1)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        self.log.setFont(mono("small"))
        theme.style(
            self.log, "QPlainTextEdit {{ background: {SURFACE}; border: 1px solid {BORDER};"
            " border-radius: {RADIUS_CONTROL}px; color: {ACCENT}; padding: 6px; }}"
        )
        outer.addWidget(self.log)

    # -- first visit: explain, then ask for root once ------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._acknowledged:
            QTimer.singleShot(0, self._first_visit_flow)   # a modal inside showEvent is fragile
            return
        if not self.items and self._thread is None:
            self.scan()

    def _first_visit_flow(self) -> None:
        if self._acknowledged:
            return
        if not self._first_visit():
            self.leave.emit()
            return
        self._acknowledged = True
        # No password here: the scan needs none, and a prompt that arrives
        # with the sizes already on screen reads as if asked for nothing. It
        # comes when a root item is actually removed.
        if not self.items and self._thread is None:
            self.scan()

    def _first_visit(self) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("This tab removes files")
        box.setText("<b>Cleanup removes files from your disk.</b>")
        box.setInformativeText(
            "Only things programs rebuild on their own: caches, compiled shaders, thumbnails, "
            "old package versions and old logs. Your documents, game saves and settings are "
            "never touched.<br><br>"
            "Nothing happens until you tick items, press <b>Remove selected…</b> and confirm "
            "the list. The sizes are read without root. Two items, the package cache and the "
            "system logs, need root to remove: your password is asked at that moment, once, "
            "and you can cancel it and still clean the rest."
        )
        ok = box.addButton("I understand", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(ok)
        box.exec()
        return box.clickedButton() is ok

    def _authenticate(self) -> None:
        """Run the helper's harmless `status` through pkexec so polkit asks once."""
        st = check()
        if not st.ready or self.client.authenticated or self._proc is not None:
            return
        self._proc = QProcess(self)
        self._proc.finished.connect(self._auth_done)
        argv = self.client.argv("status")
        self._proc.start(argv[0], argv[1:])

    def _auth_done(self, code: int, *_) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        out = bytes(proc.readAllStandardOutput()).decode(errors="replace")
        err = bytes(proc.readAllStandardError()).decode(errors="replace")
        try:
            self.client.parse(code, out, err)
            self._say("Root unlocked for this session; package cache and logs can be cleaned.")
        except ActionError as exc:
            self._say(f"No root ({exc}); the items marked 'root' stay unavailable.")
        self._fill()

    # -- scanning ------------------------------------------------------------------
    def scan(self) -> None:
        if self._thread is not None:
            return
        self.lbl_state.setText("scanning…")
        self.btn_scan.setEnabled(False)
        self._thread = _Scan(self.cleaner, self)
        self._thread.done.connect(self._scanned)
        self._thread.finished.connect(self._thread_done)
        self._thread.start()

    @Slot()
    def _thread_done(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None
        self.btn_scan.setEnabled(True)
        if self._rescan_pending:
            # After removing: fresh sizes and cleared ticks, so the same cache
            # cannot be "removed" twice by accident.
            self._rescan_pending = False
            self.scan()

    def update_view(self, snap) -> None:
        """Every sample: remember what runs, refresh the 'running now' notes."""
        self._procs = snap.procs
        if self.isVisible() and self.items:
            self._refresh_notes()

    def _note_for(self, it: CleanupItem, root_ok: bool) -> tuple[str, str]:
        """(text, colour token) for the row's note. It says what blocks the
        row when something does: a missing tool, or nothing to remove, which
        is what an empty size means and what makes the row untickable."""
        if it.needs_root:
            if it.note:
                return "root · " + it.note, "WARN"
            if it.size <= 0:
                return "root · nothing to remove", "MUTED"
            if root_ok:
                return "root · unlocked", "OK"
            return "root · asks for your password on Remove", "MUTED"
        if it.size <= 0:
            return "nothing to remove", "MUTED"
        owner = running_owner(it, self._procs)
        if owner:
            return f"running now: {owner}", "WARN"
        return "", "MUTED"

    def _refresh_notes(self) -> None:
        root_ok = check().ready and self.client.authenticated
        for it, label in zip(self.items, self._notes, strict=False):
            text, colour = self._note_for(it, root_ok)
            if label.text() != text:
                self._set_note(label, text, colour)

    @staticmethod
    def _set_note(label: QLabel, text: str, colour: str) -> None:
        label.setText(text)
        theme.style(label, "color: {" + colour + "}; font-size: {FONT_SMALL}pt;")
        label.setToolTip("Can be emptied while the program runs; it recreates what it needs, "
                         "but may stumble for a moment. Closing it first is cleaner."
                         if text.startswith("running") else text)

    @Slot(object)
    def _scanned(self, items) -> None:
        self.items = items
        self.lbl_state.setText("")
        self._fill()

    def _fill(self) -> None:
        root_ok = check().ready and self.client.authenticated
        self.list.clear()
        self._checks, self._notes = [], []
        size_w = QFontMetrics(mono("body")).horizontalAdvance("999.9 MB")
        for it in self.items:
            # a root item can be ticked as soon as the helper is installed; the
            # password comes at removal, through pkexec, not at page entry
            usable = it.size > 0 and (not it.needs_root or (check().ready and it.helper_command))
            box = QCheckBox()
            box.setEnabled(bool(usable))
            box.setAccessibleName(f"Remove {it.name}")
            box.toggled.connect(self._recount)
            note = ElidedLabel()
            self._set_note(note, *self._note_for(it, root_ok))
            size = QLabel(human(it.size) if it.size else "-")
            theme.style(size, "font-family: monospace;")
            size.setMinimumWidth(size_w)     # the sizes line up down the list
            size.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            desc = it.description + (f"  {it.note}" if it.note else "")
            row = ListRow(it.name, desc, prefix=box, suffix=[note, size])
            row.setToolTip("\n".join(str(p) for p in it.paths) or it.helper_command or desc)
            if usable:
                row.set_activatable(True)      # a click anywhere on the row ticks it
                row.activated.connect(box.toggle)
            else:
                row.dim("FAINT")
            self.list.add_row(row)
            self._checks.append(box)
            self._notes.append(note)
        self._recount()

    def _selected(self) -> list[CleanupItem]:
        return [it for it, box in zip(self.items, self._checks, strict=False)
                if box.isChecked()]

    def _recount(self, *_) -> None:
        sel = self._selected()
        total = sum(i.size for i in sel)
        self.lbl_total.setText(f"{len(sel)} selected · {human(total)}" if sel else "")
        self.btn_clean.setEnabled(bool(sel) and self._thread is None and self._proc is None)

    # -- removing ------------------------------------------------------------------
    def _clean(self) -> None:
        sel = self._selected()
        if not sel:
            return
        total = sum(i.size for i in sel)
        lines = []
        running = []
        for i in sel[:12]:
            owner = running_owner(i, self._procs)
            mark = (f" <span style='color:{theme.WARN}'>· running now: {owner}</span>"
                    if owner else "")
            lines.append(f"• {i.name} ({human(i.size)}){mark}")
            if owner:
                running.append(i.name)
        names = "<br>".join(lines)
        if len(sel) > 12:
            names += f"<br>• … and {len(sel) - 12} more"
        caution = ""
        if running:
            caution = (f"<br><br><span style='color:{theme.WARN}'>Some of these belong to a "
                       "program that is running. That is not dangerous, but the program may "
                       "stumble for a moment and starts refilling the cache right away. "
                       "Closing it first is cleaner.</span>")
        if any(i.id == "journal" for i in sel):
            caution += (f"<br><br><span style='color:{theme.WARN}'>System logs: everything "
                        "older than the newest 100 MB is removed for good, including the logs "
                        "of an earlier crash you might still want to look up "
                        "(<code>journalctl -b -1</code> shows the previous boot). If you are "
                        f"chasing a problem, keep them for now. {CANNOT_UNDO}</span>")
        answer = QMessageBox.question(
            self, "Remove these?",
            f"This frees about <b>{human(total)}</b> by emptying:<br><br>{names}{caution}"
            "<br><br>Programs rebuild these when needed. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        user = [i for i in sel if not i.needs_root]
        self._queue = [i for i in sel if i.needs_root]
        self.btn_clean.setEnabled(False)
        self.btn_scan.setEnabled(False)
        self._say(f"Removing {len(sel)} item(s)…")
        if user:
            self._thread = _Empty(self.cleaner, user, self)
            self._thread.progress.connect(self._say)
            self._thread.done.connect(self._user_done)
            self._thread.finished.connect(self._thread_done)
            self._thread.start()
        else:
            self._next_root()

    @Slot(int)
    def _user_done(self, freed: int) -> None:
        self.status.emit(f"Freed {human(freed)}")
        self._next_root()

    def _next_root(self) -> None:
        if not self._queue:
            self._say("Done.")
            if self._thread is not None:
                self._rescan_pending = True   # the worker is still winding down
            else:
                self.scan()
            return
        item = self._queue.pop(0)
        self._say(f"  → {item.name} (root)")
        self._proc = QProcess(self)
        self._proc.finished.connect(lambda code, *_: self._root_done(item, code))
        argv = self.client.argv(item.helper_command)
        self._proc.start(argv[0], argv[1:])

    def _root_done(self, item: CleanupItem, code: int) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        out = bytes(proc.readAllStandardOutput()).decode(errors="replace")
        err = bytes(proc.readAllStandardError()).decode(errors="replace")
        try:
            result = self.client.parse(code, out, err)
            self._say(f"  ✓ {item.name}: {next(iter(result.values()), 'ok')}")
        except ActionError as exc:
            self._say(f"  ✗ {item.name}: {exc}")
        self._next_root()

    def _say(self, text: str) -> None:
        self.log.appendPlainText(text)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
