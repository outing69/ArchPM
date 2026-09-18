"""The firewall block, read-only: detection, the two parsers on the tools'
own output, the plain read's routes, and the three lines.

Run with:  python3 -m unittest discover tests
"""
from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace

from archpm import firewall as F

# ufw status verbose on this machine (0.36.2, default DROP, two rules bound
# to the VM bridge, two route rules, the IPv6 twins) as ufw prints it
UFW_THIS_MACHINE = """\
Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), deny (routed)
New profiles: skip

To                         Action      From
--                         ------      ----
53/udp on virbr0           ALLOW IN    Anywhere
67/udp on virbr0           ALLOW IN    Anywhere
Anywhere on wlan0          ALLOW FWD   Anywhere on virbr0
Anywhere on virbr0         ALLOW FWD   Anywhere on wlan0
53/udp (v6) on virbr0      ALLOW IN    Anywhere (v6)
67/udp (v6) on virbr0      ALLOW IN    Anywhere (v6)
Anywhere (v6) on wlan0     ALLOW FWD   Anywhere (v6) on virbr0
Anywhere (v6) on virbr0    ALLOW FWD   Anywhere (v6) on wlan0

"""

# a desktop with more: a profile, a range, a rate limit, a subnet, a block,
# a comment, and a rule that opens everything to one host
UFW_DESKTOP = """\
Status: active
Logging: on (low)
Default: reject (incoming), allow (outgoing), disabled (routed)
New profiles: skip

To                         Action      From
--                         ------      ----
22/tcp                     LIMIT IN    Anywhere                   # ssh
KDE Connect                ALLOW IN    Anywhere
1714:1764/udp              ALLOW IN    Anywhere
80/tcp                     ALLOW IN    192.168.1.0/24
23/tcp                     DENY IN     Anywhere
Anywhere                   ALLOW IN    192.168.1.5
25/tcp                     ALLOW OUT   Anywhere
22/tcp (v6)                LIMIT IN    Anywhere (v6)              # ssh
KDE Connect (v6)           ALLOW IN    Anywhere (v6)
1714:1764/udp (v6)         ALLOW IN    Anywhere (v6)
"""

UFW_OFF = "Status: inactive\n"

FIREWALLD_PUBLIC = """\
public (default, active)
  target: default
  icmp-block-inversion: no
  interfaces: wlan0
  sources:
  services: dhcpv6-client ssh
  ports: 8080/tcp
  protocols:
  forward: yes
  masquerade: no
  forward-ports:
  source-ports:
  icmp-blocks:
  rich rules:
"""


def fake_run(responses):
    """A subprocess.run that answers by the argv's first words."""
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        for key, (code, out, err) in responses.items():
            if " ".join(argv).startswith(key):
                return SimpleNamespace(returncode=code, stdout=out, stderr=err)
        raise AssertionError(f"unexpected command {argv}")
    run.calls = calls
    return run


def which_of(*names):
    return lambda name: f"/usr/bin/{name}" if name in names else None


def active(*units):
    return {f"systemctl is-active {u}": (0 if u in units else 3,
                                         "active\n" if u in units else "inactive\n", "")
            for u in F.UNITS}


class Detect(unittest.TestCase):
    def test_nothing_installed_nothing_running(self):
        setup = F.detect(which=which_of(), run=fake_run(active()), conf="/nonexistent")
        self.assertEqual(setup.tool, "")
        self.assertFalse(setup.ufw)
        self.assertIsNone(setup.ufw_enabled)

    def test_ufw_with_its_service_and_conf(self):
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as fh:
            fh.write("# comment\nENABLED=yes\nLOGLEVEL=low\n")
        self.addCleanup(os.unlink, fh.name)
        setup = F.detect(which=which_of("ufw", "nft", "iptables"),
                         run=fake_run(active("ufw.service")), conf=fh.name)
        self.assertEqual(setup.tool, F.UFW)
        self.assertTrue(setup.active["ufw.service"])
        self.assertTrue(setup.ufw_enabled)

    def test_ufw_conf_says_no(self):
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as fh:
            fh.write('ENABLED="no"\n')
        self.addCleanup(os.unlink, fh.name)
        setup = F.detect(which=which_of("ufw"), run=fake_run(active()), conf=fh.name)
        self.assertIs(setup.ufw_enabled, False)

    def test_firewalld_running_wins_over_ufw_installed(self):
        setup = F.detect(which=which_of("ufw", "firewall-cmd"),
                         run=fake_run(active("firewalld.service")), conf="/nonexistent")
        self.assertEqual(setup.tool, F.FIREWALLD)

    def test_ufw_installed_wins_over_firewalld_installed_when_neither_runs(self):
        setup = F.detect(which=which_of("ufw", "firewall-cmd"), run=fake_run(active()),
                         conf="/nonexistent")
        self.assertEqual(setup.tool, F.UFW)

    def test_nftables_or_iptables_only_when_their_unit_runs(self):
        setup = F.detect(which=which_of("nft"), run=fake_run(active("nftables.service")))
        self.assertEqual(setup.tool, F.NFTABLES)
        setup = F.detect(which=which_of("iptables"), run=fake_run(active("iptables.service")))
        self.assertEqual(setup.tool, F.IPTABLES)
        setup = F.detect(which=which_of("nft", "iptables"), run=fake_run(active()))
        self.assertEqual(setup.tool, "", "the binaries alone are not a firewall")

    def test_systemctl_failing_means_not_running(self):
        def run(argv, **kw):
            raise OSError("no systemctl")
        setup = F.detect(which=which_of("ufw"), run=run, conf="/nonexistent")
        self.assertFalse(any(setup.active.values()))


class ParseUfw(unittest.TestCase):
    def test_this_machine(self):
        st = F.parse_ufw(UFW_THIS_MACHINE)
        self.assertTrue(st.running)
        self.assertEqual(st.incoming, F.DROP)
        self.assertEqual([(r.to, r.iface, r.source) for r in st.rules],
                         [("53/udp", "virbr0", ""), ("67/udp", "virbr0", "")],
                         "route rules are not doors, and the v6 twins fold")
        self.assertEqual(st.error, "")

    def test_desktop(self):
        st = F.parse_ufw(UFW_DESKTOP)
        self.assertEqual(st.incoming, F.REJECT)
        rules = {r.to: r for r in st.rules}
        self.assertEqual(set(rules), {"22/tcp", "KDE Connect", "1714:1764/udp", "80/tcp",
                                      "Anywhere"},
                         "DENY and OUT rules are not doors; a comment is not a source")
        self.assertTrue(rules["22/tcp"].limited)
        self.assertEqual(rules["80/tcp"].source, "192.168.1.0/24")
        self.assertEqual(rules["Anywhere"].source, "192.168.1.5")
        self.assertEqual(rules["22/tcp"].port, 22)
        self.assertEqual(rules["1714:1764/udp"].port, 0)
        self.assertEqual(rules["KDE Connect"].port, 0)

    def test_off(self):
        st = F.parse_ufw(UFW_OFF)
        self.assertIs(st.running, False)
        self.assertEqual(st.rules, [])
        self.assertTrue(st.known)

    def test_garbage_is_an_error_not_a_state(self):
        st = F.parse_ufw("ERROR: You need to be root to run this script\n")
        self.assertIsNone(st.running)
        self.assertNotEqual(st.error, "")

    def test_rule_text_names_the_port(self):
        svc = {22: "ssh", 80: "http"}.get
        self.assertEqual(F.Rule("22/tcp").text(svc), "22/tcp (ssh)")
        self.assertEqual(F.Rule("80/tcp", "192.168.1.0/24", "wlan0").text(svc),
                         "80/tcp (http) on wlan0 from 192.168.1.0/24")
        self.assertEqual(F.Rule("KDE Connect").text(svc), "KDE Connect")


class ParseFirewalld(unittest.TestCase):
    def test_public_zone(self):
        st = F.parse_firewalld("running", "public", FIREWALLD_PUBLIC)
        self.assertTrue(st.running)
        self.assertEqual(st.incoming, F.REJECT, "the public zone's default target rejects")
        self.assertEqual([r.to for r in st.rules], ["dhcpv6-client", "ssh", "8080/tcp"])
        self.assertEqual(st.rules[0].iface, "wlan0")

    def test_not_running(self):
        st = F.parse_firewalld("not running", "", "")
        self.assertIs(st.running, False)
        self.assertEqual(st.error, "")

    def test_targets(self):
        for target, incoming in (("DROP", F.DROP), ("%%REJECT%%", F.REJECT),
                                 ("ACCEPT", F.ALLOW), ("default", F.REJECT)):
            st = F.parse_firewalld("running", "z", f"z\n  target: {target}\n  services:\n")
            self.assertEqual(st.incoming, incoming, target)


class PlainRead(unittest.TestCase):
    def test_no_tool_is_an_empty_state(self):
        st = F.read_as_user(F.Setup(), run=fake_run({}))
        self.assertEqual((st.tool, st.needs_root, st.running), ("", False, None))

    def test_ufw_is_not_even_asked(self):
        run = fake_run({})
        st = F.read_as_user(F.Setup(ufw=True), run=run)
        self.assertTrue(st.needs_root)
        self.assertEqual(run.calls, [])
        self.assertFalse(st.known)

    def test_nftables_alone_is_running_and_nothing_more(self):
        run = fake_run({})
        st = F.read_as_user(F.Setup(active={"nftables.service": True}), run=run)
        self.assertEqual((st.tool, st.running, st.rules), (F.NFTABLES, True, []))
        self.assertEqual(run.calls, [])

    def test_firewalld_answers_a_plain_user(self):
        run = fake_run({"firewall-cmd --state": (0, "running\n", ""),
                        "firewall-cmd --get-default-zone": (0, "public\n", ""),
                        "firewall-cmd --zone=public --list-all": (0, FIREWALLD_PUBLIC, "")})
        st = F.read_as_user(F.Setup(firewalld=True, active={"firewalld.service": True}), run=run)
        self.assertTrue(st.known)
        self.assertEqual(len(st.rules), 3)
        self.assertGreaterEqual(st.took_ms, 0)
        self.assertEqual(len(run.calls), 3)

    def test_firewalld_not_running_stops_after_the_state(self):
        run = fake_run({"firewall-cmd --state": (252, "not running\n", "")})
        st = F.read_as_user(F.Setup(firewalld=True), run=run)
        self.assertIs(st.running, False)
        self.assertEqual(len(run.calls), 1)

    def test_firewalld_refusal_means_needs_root(self):
        run = fake_run({"firewall-cmd": (255, "", "Error: NOT_AUTHORIZED\n")})
        st = F.read_as_user(F.Setup(firewalld=True), run=run)
        self.assertTrue(st.needs_root)
        self.assertEqual(st.error, "")

    def test_other_error_is_reported(self):
        run = fake_run({"firewall-cmd": (1, "", "some other failure\n")})
        st = F.read_as_user(F.Setup(firewalld=True), run=run)
        self.assertEqual(st.error, "some other failure")

    def test_from_helper(self):
        st = F.from_helper({"tool": "ufw", "outputs": [["status", UFW_THIS_MACHINE]],
                            "took_ms": 80.5})
        self.assertTrue(st.as_root)
        self.assertTrue(st.known)
        self.assertEqual(st.took_ms, 80.5)
        self.assertEqual(len(st.rules), 2)


class Lines(unittest.TestCase):
    svc = staticmethod({22: "ssh", 53: "domain", 67: "bootps", 80: "http"}.get)

    def test_no_firewall_is_one_line_without_advice(self):
        out = F.lines(F.Setup(), F.State())
        self.assertEqual(len(out), 1)
        self.assertIn("No firewall", out[0])
        self.assertNotIn("install", out[0].lower())

    def test_this_machine_before_the_helper(self):
        setup = F.Setup(ufw=True, active={"ufw.service": True}, ufw_enabled=True)
        st = F.read_as_user(setup, run=fake_run({}))
        out = F.lines(setup, st, self.svc, helper_ready=True)
        self.assertEqual(len(out), 2)
        self.assertIn("set to start at boot", out[0])
        self.assertIn("Read the firewall", out[1])
        out = F.lines(setup, st, self.svc, helper_ready=False, helper_path="/x/helper")
        self.assertIn("not installed (/x/helper)", out[1])

    def test_this_machine_read_as_root(self):
        setup = F.Setup(ufw=True, active={"ufw.service": True}, ufw_enabled=True)
        st = F.from_helper({"tool": "ufw", "outputs": [["status", UFW_THIS_MACHINE]]})
        out = F.lines(setup, st, self.svc)
        self.assertEqual(out, [
            "ufw is on.",
            "Whatever arrives that no rule covers is dropped without a reply.",
            "2 doors open to other machines: 53/udp (domain) on virbr0, "
            "67/udp (bootps) on virbr0.",
        ])

    def test_desktop_lines_and_the_reject_words(self):
        setup = F.Setup(ufw=True, active={"ufw.service": True}, ufw_enabled=True)
        st = F.from_helper({"tool": "ufw", "outputs": [["status", UFW_DESKTOP]]})
        out = F.lines(setup, st, self.svc)
        self.assertIn("refused, and the sender is told", out[1])
        self.assertEqual(out[2], "5 doors open to other machines: 22/tcp (ssh) (rate-limited), "
                                 "KDE Connect, 1714:1764/udp, 80/tcp (http) from 192.168.1.0/24, "
                                 "everything from 192.168.1.5.",
                         "an Anywhere rule from one host is a door, not everything open")

    def test_wide_open(self):
        st = F.State(tool=F.UFW, running=True, incoming=F.DROP, rules=[F.Rule("Anywhere")])
        out = F.lines(F.Setup(ufw=True), st)
        self.assertIn("Everything is open", out[2])
        st = F.State(tool=F.UFW, running=True, incoming=F.ALLOW)
        out = F.lines(F.Setup(ufw=True), st)
        self.assertIn("let in unless a rule blocks it", out[1])
        self.assertIn("Every open door above is reachable", out[2])

    def test_many_doors_are_counted_and_a_few_named(self):
        rules = [F.Rule(f"{p}/tcp") for p in range(1000, 1009)]
        st = F.State(tool=F.UFW, running=True, incoming=F.DROP, rules=rules)
        out = F.lines(F.Setup(ufw=True), st)
        self.assertTrue(out[2].startswith("9 doors open to other machines: 1000/tcp, "))
        self.assertTrue(out[2].endswith("1003/tcp and 5 more."))

    def test_off_and_nftables_and_errors(self):
        setup = F.Setup(ufw=True, active={"ufw.service": True}, ufw_enabled=False)
        st = F.from_helper({"tool": "ufw", "outputs": [["status", UFW_OFF]]})
        out = F.lines(setup, st)
        self.assertEqual(len(out), 1)
        self.assertIn("off", out[0])
        st = F.read_as_user(setup, run=fake_run({}))
        self.assertIn("ENABLED=no", F.lines(setup, st)[0])
        out = F.lines(F.Setup(active={"nftables.service": True}),
                      F.State(tool=F.NFTABLES, running=True))
        self.assertEqual(len(out), 1)
        self.assertIn("not summarised", out[0])
        st = F.State(tool=F.UFW, needs_root=True, error="Authentication cancelled.")
        out = F.lines(F.Setup(ufw=True), st)
        self.assertEqual(out[-1], "Not read: Authentication cancelled.")
        self.assertEqual(len(out), 3)

    def test_never_more_than_three_lines_without_an_error(self):
        for text in (UFW_THIS_MACHINE, UFW_DESKTOP, UFW_OFF):
            st = F.from_helper({"tool": "ufw", "outputs": [["status", text]]})
            self.assertLessEqual(len(F.lines(F.Setup(ufw=True), st)), 3)


class OnThisMachine(unittest.TestCase):
    def test_the_plain_read_never_raises_and_is_quick(self):
        import time
        t0 = time.perf_counter()
        setup = F.detect()
        st = F.read_as_user(setup)
        ms = (time.perf_counter() - t0) * 1000
        self.assertEqual(st.tool, setup.tool)
        self.assertIsInstance(F.lines(setup, st), list)
        self.assertLess(ms, 2000)


if __name__ == "__main__":
    unittest.main()
