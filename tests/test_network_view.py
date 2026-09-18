"""The Network tree: program, then the process when a program holds sockets
in more than one, then the sockets. A program with a single socket-holding
process keeps its sockets directly under it.

Needs PySide6 and runs offscreen; skipped where PySide6 is missing.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication
except ImportError:                       # pragma: no cover
    QApplication = None

from archpm.model import ProcSample, Snapshot, SystemSample
from archpm.net import Conn, NetSnapshot, ProcNet


def proc(pid, name, app):
    return ProcSample(pid=pid, ppid=1, name=name, username="alex", owned=True,
                      cmdline=f"/usr/bin/{name}", program=True, app_name=app)


def tcp(pid, lport, raddr="", rport=0, state="ESTAB"):
    return Conn("tcp", state, "192.0.2.10", lport, raddr, rport, pid)


def udp_listen(pid, lport):
    return Conn("udp", "UNCONN", "0.0.0.0", lport, "", 0, pid)


PROCS = [proc(100, "brave", "Brave Web Browser"), proc(101, "brave", "Brave Web Browser"),
         proc(102, "brave", "Brave Web Browser"),            # no sockets
         proc(200, "steam", "Steam")]


def net_snapshot(ts: float) -> NetSnapshot:
    brave_main = ProcNet(100, "Brave Web Browser", [
        udp_listen(100, 5353), tcp(100, 40001, "198.51.100.7", 443)], rx_bps=5000.0)
    brave_net = ProcNet(101, "Brave Web Browser", [
        tcp(101, 40002, "198.51.100.8", 443), tcp(101, 40003, "198.51.100.9", 8443),
        tcp(101, 40004, "198.51.100.9", 443)], rx_bps=90000.0)
    steam = ProcNet(200, "Steam", [tcp(200, 27036, state="LISTEN"),
                                   tcp(200, 40005, "203.0.113.5", 27017)])
    return NetSnapshot(ts=ts, interfaces=[], procs={100: brave_main, 101: brave_net, 200: steam},
                       other_sockets=0, tcp_rates=True)


@unittest.skipUnless(QApplication, "PySide6 not installed")
class ProcessLevel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from archpm.ui.network import NetworkView
        self.view = NetworkView(lambda port: {443: "https", 5353: "mDNS"}.get(port, ""))
        self.view.resize(900, 600)
        self.view.show()
        self.feed(1.0)

    def feed(self, ts: float):
        self.view.update_view(Snapshot(SystemSample(ts=ts), list(PROCS), net=net_snapshot(ts)))

    def top(self, name):
        from archpm.ui.network import COL_NAME
        tree = self.view.tree
        for i in range(tree.topLevelItemCount()):
            if tree.topLevelItem(i).text(COL_NAME) == name:
                return tree.topLevelItem(i)
        names = [tree.topLevelItem(i).text(COL_NAME) for i in range(tree.topLevelItemCount())]
        self.fail(f"no row for {name}: {names}")

    def test_a_single_process_program_keeps_its_sockets_directly_under_it(self):
        from archpm.ui.network import COL_INFO, COL_NAME
        steam = self.top("Steam")
        self.assertEqual(steam.text(COL_INFO), "2 socket(s), pid 200")
        self.assertEqual(steam.childCount(), 2)
        for i in range(2):
            sock = steam.child(i)
            self.assertEqual(sock.text(COL_NAME), "")
            self.assertEqual(sock.childCount(), 0)
        self.assertTrue(steam.child(0).text(COL_INFO).startswith("Listening on port 27036"))

    def test_a_multi_process_program_gets_a_row_per_process_with_name_pid_and_ports(self):
        from archpm.ui.network import COL_CONNS, COL_INFO, COL_NAME, COL_RX
        brave = self.top("Brave Web Browser")
        self.assertEqual(brave.text(COL_INFO), "5 socket(s) in 2 processes")
        self.assertEqual(brave.text(COL_CONNS), "4")
        self.assertEqual(brave.childCount(), 2, "one row per process that holds sockets")
        busy, main = brave.child(0), brave.child(1)          # the busier process first
        self.assertEqual([busy.text(COL_NAME), main.text(COL_NAME)], ["brave", "brave"])
        self.assertEqual(busy.text(COL_RX), "87.9 KB/s")
        self.assertEqual(busy.text(COL_INFO), "pid 101 · 3 socket(s) · → 443 (https), 8443")
        self.assertEqual(main.text(COL_INFO),
                         "pid 100 · 2 socket(s) · listening 5353 (mDNS) · → 443 (https)")
        self.assertEqual(busy.childCount(), 3)
        self.assertEqual(main.childCount(), 2)
        self.assertTrue(main.child(0).text(COL_INFO).startswith("Listening on port 5353"))
        self.assertTrue(main.child(1).text(COL_INFO).startswith("→ 198.51.100.7:443"))

    def test_the_port_summary_shows_only_while_the_process_row_is_collapsed(self):
        from archpm.ui.network import COL_INFO
        brave = self.top("Brave Web Browser")
        brave.setExpanded(True)
        row = brave.child(1)
        row.setExpanded(True)
        self.assertEqual(row.text(COL_INFO), "pid 100 · 2 socket(s)")
        row.setExpanded(False)
        self.assertEqual(row.text(COL_INFO),
                         "pid 100 · 2 socket(s) · listening 5353 (mDNS) · → 443 (https)")
        # the open state survives the next scan, and the summary stays out while open
        row.setExpanded(True)
        self.feed(2.0)
        brave = self.top("Brave Web Browser")
        self.assertTrue(brave.isExpanded())
        row = brave.child(1)
        self.assertTrue(row.isExpanded())
        self.assertEqual(row.text(COL_INFO), "pid 100 · 2 socket(s)")
        self.assertFalse(brave.child(0).isExpanded())

    def test_process_rows_stay_closed_unless_opened_by_hand(self):
        from archpm.ui.network import COL_INFO
        brave = self.top("Brave Web Browser")
        self.assertFalse(brave.isExpanded())
        self.assertFalse(brave.child(0).isExpanded() or brave.child(1).isExpanded())
        brave.setExpanded(True)
        brave.child(1).setExpanded(True)                 # by hand
        self.view.search.setText("443")                  # a filter opens the program ...
        brave = self.top("Brave Web Browser")
        self.assertTrue(brave.isExpanded())
        self.assertTrue(brave.child(1).isExpanded(), "the hand-opened process stays open")
        self.assertFalse(brave.child(0).isExpanded(), "... but not the other process")
        self.assertTrue(brave.child(0).text(COL_INFO).endswith("→ 443 (https), 8443"))
        self.view.search.setText("")
        brave = self.top("Brave Web Browser")
        self.assertTrue(brave.isExpanded(), "programs keep the open state a filter gave them")
        self.assertEqual([brave.child(0).isExpanded(), brave.child(1).isExpanded()], [False, True])

    def test_the_filter_reaches_the_process_row(self):
        from archpm.ui.network import COL_NAME
        self.view.search.setText("8443")
        tree = self.view.tree
        self.assertEqual(tree.topLevelItemCount(), 1)
        brave = tree.topLevelItem(0)
        self.assertEqual(brave.childCount(), 1)
        self.assertEqual(brave.child(0).text(COL_NAME), "brave")
        self.assertEqual(brave.child(0).childCount(), 1)
        self.view.search.setText("101")
        self.assertEqual(tree.topLevelItem(0).childCount(), 1)
        self.assertEqual(tree.topLevelItem(0).child(0).childCount(), 3,
                         "a pid keeps all its sockets")


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(QApplication, "PySide6 not installed")
class FirewallBlock(unittest.TestCase):
    """The firewall lines under the open doors: read-only, three lines at
    most, the link reads or refreshes, and without a client the block
    never reads by itself."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def view(self, ready: bool, client=True):
        from archpm.root.client import RootClient, RootStatus
        from archpm.ui import network as N
        view = N.NetworkView(lambda port: {443: "https", 53: "domain"}.get(port, ""),
                             RootClient() if client else None)
        fake = RootStatus(helper=ready, policy=ready, pkexec=ready)
        original = N.check
        N.check = lambda: fake
        self.addCleanup(setattr, N, "check", original)
        return view

    def test_without_a_client_nothing_is_read_and_nothing_shown(self):
        view = self.view(ready=True, client=False)
        view.show()
        self.app.processEvents()
        self.assertIsNone(view.fw_state)
        self.assertFalse(view.lbl_fw.isVisibleTo(view))

    def test_ufw_before_the_helper_offers_the_read_link(self):
        from archpm import firewall as F
        view = self.view(ready=True)
        setup = F.Setup(ufw=True, active={"ufw.service": True}, ufw_enabled=True)
        view.set_firewall(setup, F.read_as_user(setup, run=lambda *a, **k: None))
        text = view.firewall_text()
        self.assertTrue(text.startswith("ufw is installed"))
        self.assertEqual(view.lbl_fw_title.text(), "Firewall")
        self.assertTrue(view.sep_fw.isVisibleTo(view), "a hairline sets the block apart")
        self.assertIn("Read the firewall", text)
        self.assertTrue(view.link_fw.isVisibleTo(view))
        self.assertEqual(view.link_fw._text, "Read the firewall")

    def test_ufw_without_the_helper_says_so_and_offers_nothing(self):
        from archpm import firewall as F
        view = self.view(ready=False)
        setup = F.Setup(ufw=True, active={"ufw.service": True}, ufw_enabled=True)
        view.set_firewall(setup, F.read_as_user(setup, run=lambda *a, **k: None))
        self.assertIn("root helper is not installed", view.firewall_text())
        self.assertFalse(view.link_fw.isVisibleTo(view))

    def test_read_as_root_shows_three_lines_and_a_refresh(self):
        from archpm import firewall as F
        view = self.view(ready=True)
        st = F.State(tool=F.UFW, running=True, incoming=F.DROP, as_root=True,
                     rules=[F.Rule("53/udp", "", "virbr0")], took_ms=80, call_ms=900,
                     taken_at=1000.0)
        view.set_firewall(F.Setup(ufw=True, active={"ufw.service": True}), st)
        lines = view.firewall_text().split("\n")
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0], "ufw is on.")
        self.assertEqual(lines[2], "1 door open to other machines")
        self.assertEqual(view.firewall_rows(), ["53/udp · domain · on virbr0"])
        self.assertFalse(view.lbl_fw_doors._link, "few doors: the count is plain text")
        self.assertEqual(view.link_fw._text, "Refresh")
        self.assertIn("80 ms as root (the whole helper call 900 ms)", view.link_fw.toolTip())

    def test_no_firewall_is_one_line(self):
        from archpm import firewall as F
        view = self.view(ready=True)
        view.set_firewall(F.Setup(), F.State())
        lines = view.firewall_text().split("\n")
        self.assertEqual(len(lines), 1)
        self.assertIn("No firewall", lines[0])
        self.assertEqual(view.link_fw._text, "Refresh")

    def test_no_control_to_change_anything(self):
        """Read-only: no button, switch or box in the doors card."""
        from PySide6.QtWidgets import QAbstractButton
        view = self.view(ready=True)
        self.assertEqual(view.card_doors.findChildren(QAbstractButton), [])

    def test_ten_doors_fold_behind_their_count_and_open_on_a_click(self):
        from archpm import firewall as F
        view = self.view(ready=True)
        rules = [F.Rule(f"{p}/tcp") for p in range(1000, 1010)]
        st = F.State(tool=F.UFW, running=True, incoming=F.DROP, as_root=True, rules=rules)
        view.set_firewall(F.Setup(ufw=True, active={"ufw.service": True}), st)
        self.assertEqual(len(view.firewall_text().split("\n")), 3)
        self.assertTrue(view.lbl_fw_doors._link)
        self.assertEqual(view.lbl_fw_doors._text, "10 doors open to other machines ▸")
        self.assertEqual(view.firewall_rows(), [], "closed by default")
        view.lbl_fw_doors.activated.emit()
        self.assertEqual(len(view.firewall_rows()), 10)
        self.assertEqual(view.lbl_fw_doors._text, "10 doors open to other machines ▾")
        view.set_firewall(F.Setup(ufw=True, active={"ufw.service": True}), st)
        self.assertEqual(len(view.firewall_rows()), 10, "a refresh keeps it open")
        view.lbl_fw_doors.activated.emit()
        self.assertEqual(view.firewall_rows(), [])

    def test_the_link_has_its_own_width_beside_the_label(self):
        """A link, not a field: as wide as its words, on the label's line,
        right after it, the way the failed services block places its control."""
        from archpm import firewall as F
        view = self.view(ready=True)
        view.resize(900, 500)
        view.show()
        view.set_firewall(F.Setup(), F.State())
        self.app.processEvents()
        link, title, text = view.link_fw, view.lbl_fw_title, view.lbl_fw
        self.assertLess(link.width(), text.width() // 2)
        self.assertEqual(link.width(), link.sizeHint().width())
        self.assertGreater(link.x(), title.x() + title.width())
        self.assertEqual(link.y() + link.height() // 2, title.y() + title.height() // 2)
        self.assertLess(title.y(), text.y(), "the label is a line of its own above the text")
