"""RootClient.parse: the helper's JSON reply wins, pkexec's exit codes speak
when there is none, and the client keeps no lock state of its own."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from archpm.actions import ActionError, Cancelled
from archpm.root import client
from archpm.root.client import ACTION_PREFIX, RootClient


class Parse(unittest.TestCase):
    def test_a_good_reply_is_its_result(self):
        self.assertEqual(RootClient.parse(0, '{"ok": true, "result": {"pid": 5}}', ""),
                         {"pid": 5})
        self.assertEqual(RootClient.parse(0, '{"ok": true, "result": null}', ""), {})

    def test_the_last_line_is_the_reply(self):
        out = "some noise\n{\"ok\": true, \"result\": {\"n\": 1}}\n"
        self.assertEqual(RootClient.parse(0, out, ""), {"n": 1})

    def test_a_refusal_is_the_helpers_words(self):
        with self.assertRaises(ActionError) as ctx:
            RootClient.parse(1, '{"ok": false, "error": "signal FOO not allowed"}', "")
        self.assertEqual(str(ctx.exception), "signal FOO not allowed")

    def test_a_dismissed_dialog_is_cancelled(self):
        with self.assertRaises(Cancelled) as ctx:
            RootClient.parse(126, "", "Error executing command as another user: Request dismissed")
        self.assertEqual(str(ctx.exception), client.CANCELLED)

    def test_no_authorisation_is_cancelled_when_a_prompt_was_possible(self):
        """KDE's agent reports a cancelled dialog as not authorised (127);
        pkcheck says a prompt was possible, so it was cancelled or failed."""
        with patch.object(client, "challenge_possible", lambda _cmd: True), \
                self.assertRaises(Cancelled) as ctx:
            RootClient.parse(127, "", "Error executing command as another user: Not authorized",
                             "cleanup")
        self.assertEqual(str(ctx.exception), client.CANCELLED_OR_REFUSED)
        self.assertIn("nothing was done", str(ctx.exception))

    def test_no_authorisation_is_a_refusal_when_no_prompt_was_possible(self):
        with patch.object(client, "challenge_possible", lambda _cmd: False), \
                self.assertRaises(ActionError) as ctx:
            RootClient.parse(127, "", "", "cleanup")
        self.assertNotIsInstance(ctx.exception, Cancelled)
        self.assertIn("Not authorised", str(ctx.exception))
        self.assertIn("wheel", str(ctx.exception))

    def test_without_the_command_a_127_is_taken_as_cancelled(self):
        with self.assertRaises(Cancelled):
            RootClient.parse(127, "", "")

    def test_other_codes_carry_the_last_stderr_line(self):
        with self.assertRaises(ActionError) as ctx:
            RootClient.parse(2, "", "usage: archpm-helper\narchpm-helper: error: bad")
        self.assertEqual(str(ctx.exception), "archpm-helper: error: bad")

    def test_challenge_possible_reads_pkcheck(self):
        def answer(text, code=1):
            return lambda *a, **k: SimpleNamespace(returncode=code, stdout=text, stderr="")
        challenge = ("polkit\\56result=auth_admin\n"
                     "Authorization requires authentication and -u wasn't passed.\n")
        self.assertTrue(client.challenge_possible("cleanup", answer(challenge)))
        self.assertFalse(client.challenge_possible("cleanup", answer("Not authorized.\n")))
        self.assertTrue(client.challenge_possible("snapshots-list", answer("", 0)))

        def missing(*a, **k):
            raise FileNotFoundError("pkcheck")
        self.assertTrue(client.challenge_possible("cleanup", missing),
                        "no pkcheck: assume a prompt")

    def test_no_lock_state(self):
        client = RootClient()
        self.assertFalse(hasattr(client, "authenticated"))
        self.assertEqual(ACTION_PREFIX, "io.github.outing69.archpm.helper.")


if __name__ == "__main__":
    unittest.main()
