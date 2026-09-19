"""RootClient.parse: the helper's JSON reply wins, pkexec's exit codes speak
when there is none, and the client keeps no lock state of its own."""
from __future__ import annotations

import unittest

from archpm.actions import ActionError
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

    def test_pkexec_codes_speak_when_the_helper_did_not(self):
        with self.assertRaises(ActionError) as ctx:
            RootClient.parse(126, "", "")
        self.assertIn("cancelled", str(ctx.exception))
        with self.assertRaises(ActionError) as ctx:
            RootClient.parse(127, "", "")
        self.assertIn("Not authorised", str(ctx.exception))
        with self.assertRaises(ActionError) as ctx:
            RootClient.parse(2, "", "usage: archpm-helper\narchpm-helper: error: bad")
        self.assertEqual(str(ctx.exception), "archpm-helper: error: bad")

    def test_no_lock_state(self):
        client = RootClient()
        self.assertFalse(hasattr(client, "authenticated"))
        self.assertEqual(ACTION_PREFIX, "io.github.outing69.archpm.helper.")


if __name__ == "__main__":
    unittest.main()
