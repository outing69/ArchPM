"""The instance socket carries one request line per connection. The widgets
use it too: "Open ArchPM" is a plain launch, "End game" a launch with
--end-game. Only the exact words do anything; a line with anything appended
is dropped, and nothing from the line is ever run."""
from __future__ import annotations

import os
import sys
import unittest

try:
    from PySide6.QtCore import QTimer
    from PySide6.QtNetwork import QLocalSocket
    from PySide6.QtWidgets import QApplication

    from archpm.ui import app
except ImportError:   # PySide6 not installed
    app = None

EXACT = {b"show\n": "show", b"end-game\n": "end-game",
         b"show\r\n": "show", b"end-game\r\n": "end-game",
         b"show": "show", b"end-game": "end-game"}
APPENDED = [b"show \n", b"show extra\n", b"showx\n", b"show;reboot\n", b"show\x00\n",
            b"end-game --now\n", b"end-game; rm -rf ~\n", b"end-games\n", b"end-game-1\n",
            b" show\n", b"\tshow\n", b"SHOW\n", b"End-Game\n", b"\n", b"", b"\r\n",
            b"kill -9 1\n", b"\xff\xfe\n"]


@unittest.skipUnless(app, "PySide6 not installed")
class ParseRequest(unittest.TestCase):
    def test_exactly_the_two_words(self):
        for data, want in EXACT.items():
            self.assertEqual(app.parse_request(data), want, data)

    def test_anything_appended_or_prepended_is_dropped(self):
        for data in APPENDED:
            self.assertIsNone(app.parse_request(data), data)

    def test_only_the_first_line_counts(self):
        self.assertEqual(app.parse_request(b"show\nend-game\n"), "show")
        self.assertIsNone(app.parse_request(b"show extra\nend-game\n"))


@unittest.skipUnless(app, "PySide6 not installed")
class SocketPlace(unittest.TestCase):
    """The socket lives in the session's runtime directory, which only this
    user can enter, so another user cannot take its name first; without one
    it is a bare name in the shared temporary directory, as before."""

    def test_in_the_runtime_directory_when_there_is_one(self):
        name = app.instance_socket({"XDG_RUNTIME_DIR": "/run/user/1000"})
        self.assertEqual(name, f"/run/user/1000/archpm-{os.getuid()}")

    def test_a_bare_name_without_one(self):
        self.assertEqual(app.instance_socket({}), f"archpm-{os.getuid()}")
        self.assertEqual(app.instance_socket({"XDG_RUNTIME_DIR": ""}), f"archpm-{os.getuid()}")

    def test_a_name_that_cannot_be_taken_is_reported_not_hidden(self):
        import io
        from contextlib import redirect_stderr
        err = io.StringIO()
        with redirect_stderr(err):
            server = app.listen_for_launches(lambda _w: None, "/nonexistent-dir/archpm-test")
        try:
            self.assertFalse(server.isListening())
            self.assertIn("not listening", err.getvalue())
        finally:
            server.close()


@unittest.skipUnless(app, "PySide6 not installed")
class OverTheSocket(unittest.TestCase):
    """The same through a real server and client, in process. On a socket of
    its own, so a running ArchPM window keeps the real one."""

    NAME = f"archpm-test-{os.getuid()}-{os.getpid()}"

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def setUp(self):
        self.got: list[str] = []
        self.server = app.listen_for_launches(self.got.append, self.NAME)

    def tearDown(self):
        self.server.close()

    def send(self, data: bytes) -> None:
        sock = QLocalSocket()
        sock.connectToServer(self.NAME)
        self.assertTrue(sock.waitForConnected(1000))
        if data:
            sock.write(data)
            sock.waitForBytesWritten(1000)
        sock.disconnectFromServer()
        self.settle()

    def settle(self, ms: int = 100) -> None:
        loop_done = []
        QTimer.singleShot(ms, lambda: loop_done.append(True))
        while not loop_done:
            self.app.processEvents()

    def test_exact_words_arrive_and_appended_lines_do_not(self):
        for data in APPENDED:
            self.send(data)
        self.assertEqual(self.got, [], "nothing but the exact words may act")
        self.send(b"end-game\n")
        self.send(b"show\n")
        self.assertEqual(self.got, ["end-game", "show"])

    def test_the_client_side_sends_the_word_with_a_newline(self):
        self.assertTrue(app.raise_running_instance(app.END_GAME, self.NAME))
        self.assertTrue(app.raise_running_instance(name=self.NAME))
        self.settle()
        self.assertEqual(self.got, ["end-game", "show"])


if __name__ == "__main__":
    unittest.main()
