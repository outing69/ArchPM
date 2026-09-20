"""RootClient: parse reads the helper's JSON reply, and pkexec's exit codes
speak when there is none; invoke is the one place that starts pkexec, for
the synchronous route and the pages' tasks alike, so a pkexec that cannot
start, a helper that hangs and the two reply shapes are handled once; the
client keeps no lock state of its own."""
from __future__ import annotations

import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from archpm.actions import ActionError, Cancelled
from archpm.root import client
from archpm.root.client import ACTION_PREFIX, HELPER, RootClient
from archpm.toolenv import english


def answering(code: int, stdout: str = "", stderr: str = ""):
    """A `run` that records its call and answers like subprocess.run."""
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)
    run.calls = calls
    return run


def raising(exc: BaseException):
    def run(argv, **kwargs):
        raise exc
    return run


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


class Invoke(unittest.TestCase):
    def test_the_process_is_pkexec_the_helper_and_the_words_in_a_c_locale(self):
        run = answering(0, '{"ok": true, "result": {"done": {"journal": "ok"}}}')
        result = RootClient().invoke("cleanup", "journal", timeout=None, run=run)
        self.assertEqual(result, {"done": {"journal": "ok"}})
        (argv, kwargs), = run.calls
        self.assertEqual(argv, ["pkexec", str(HELPER), "cleanup", "journal"])
        self.assertEqual(kwargs["env"], english())
        self.assertEqual(kwargs["env"]["LC_ALL"], "C")
        self.assertIsNone(kwargs["timeout"], "the pages' route: a prompt left open is no hang")
        self.assertTrue(kwargs["capture_output"] and kwargs["text"])
        self.assertFalse(kwargs["check"])

    def test_a_pkexec_that_cannot_be_started_says_so_with_the_reason(self):
        with self.assertRaises(ActionError) as ctx:
            RootClient().invoke("status", run=raising(FileNotFoundError(2, "No such file or "
                                                                        "directory")))
        self.assertEqual(str(ctx.exception),
                         "the root helper could not be started (No such file or directory)")
        self.assertNotIsInstance(ctx.exception, Cancelled)

    def test_a_helper_that_hangs_is_reported_not_waited_for(self):
        with self.assertRaises(ActionError) as ctx:
            RootClient().invoke("status", run=raising(subprocess.TimeoutExpired("pkexec", 180)))
        self.assertEqual(str(ctx.exception), client.TIMED_OUT)

    def test_the_two_reply_shapes_the_helper_can_produce(self):
        # JSON with exit 1: the helper's own refusal, in its words
        with self.assertRaises(ActionError) as ctx:
            RootClient().invoke(
                "proc-signal", "1", "FOO",
                run=answering(1, '{"ok": false, "error": "signal FOO not allowed"}'))
        self.assertEqual(str(ctx.exception), "signal FOO not allowed")
        # argparse's usage with exit 2: no JSON, the last stderr line
        usage = ("usage: archpm-helper [-h] {proc-nice,...} ...\n"
                 "archpm-helper: error: argument cmd: invalid choice: 'bogus'")
        with self.assertRaises(ActionError) as ctx:
            RootClient().invoke("bogus", run=answering(2, "", usage))
        self.assertEqual(str(ctx.exception),
                         "archpm-helper: error: argument cmd: invalid choice: 'bogus'")

    def test_call_checks_readiness_first_and_runs_nothing_when_not_ready(self):
        run = answering(0, '{"ok": true, "result": {}}')
        missing = client.RootStatus(helper=False, policy=True, pkexec=True)
        with patch.object(client, "check", lambda: missing), \
                self.assertRaises(ActionError) as ctx:
            RootClient().call("status", run=run)
        self.assertEqual(str(ctx.exception), missing.problem)
        self.assertEqual(run.calls, [])
        ready = client.RootStatus(helper=True, policy=True, pkexec=True)
        with patch.object(client, "check", lambda: ready):
            self.assertEqual(RootClient().call("status", run=run), {})
        self.assertEqual(run.calls[0][1]["timeout"], 180, "the synchronous route keeps its cap")


if __name__ == "__main__":
    unittest.main()
