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
