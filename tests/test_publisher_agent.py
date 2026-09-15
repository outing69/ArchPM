"""The GUI must not write status.json while the agent service does: the two
carry different content (the agent reads no PSS) and the widget would
alternate between them."""
from __future__ import annotations

import subprocess
import unittest
from types import SimpleNamespace

from archpm import publisher


class AgentServiceActive(unittest.TestCase):
    def test_active_when_systemctl_says_so(self):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            return SimpleNamespace(returncode=0)
        self.assertTrue(publisher.agent_service_active(run))
        self.assertEqual(calls[0][:4], ["systemctl", "--user", "is-active", "--quiet"])
        self.assertEqual(calls[0][4], publisher.AGENT_UNIT)

    def test_inactive_failed_or_missing_means_not_active(self):
        self.assertFalse(publisher.agent_service_active(
            lambda *a, **k: SimpleNamespace(returncode=3)))

        def missing(*a, **k):
            raise FileNotFoundError("systemctl")
        self.assertFalse(publisher.agent_service_active(missing))

        def slow(*a, **k):
            raise subprocess.TimeoutExpired("systemctl", 3)
        self.assertFalse(publisher.agent_service_active(slow))

    def test_on_this_machine_it_matches_systemctl(self):
        expected = subprocess.run(["systemctl", "--user", "is-active", "--quiet", "archpm-agent"],
                                  capture_output=True, check=False).returncode == 0
        self.assertEqual(publisher.agent_service_active(), expected)


if __name__ == "__main__":
    unittest.main()
