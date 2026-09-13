"""Tests for archpm.net against captured `ss -tunapiH` output."""
from __future__ import annotations

import unittest

from archpm import net

SS = """\
udp UNCONN 0 0 224.0.0.251:5353 0.0.0.0:* users:(("steamwebhelper",pid=6673,fd=182))
udp UNCONN 0 0 0.0.0.0:5353 0.0.0.0:*
udp UNCONN 0 0 *:1716 *:* users:(("kdeconnectd",pid=54671,fd=16))
udp ESTAB 0 0 192.168.178.28%wlan0:68 192.168.178.1:67
tcp LISTEN 0 128 0.0.0.0:27036 0.0.0.0:* users:(("steam",pid=6463,fd=155))
tcp LISTEN 0 128 127.0.0.1:57343 0.0.0.0:* users:(("steam",pid=6463,fd=60))
tcp ESTAB 0 0 192.168.178.28:46516 35.190.46.17:443 users:(("claude",pid=35084,fd=17))
\t cubic wscale:8,10 rto:219 mss:1400 bytes_sent:2063 bytes_acked:2064 bytes_received:1454
tcp ESTAB 0 0 127.0.0.1:57634 127.0.0.1:34175 users:(("steamwebhelper",pid=6744,fd=30))
\t cubic wscale:2,10 rto:203 bytes_sent:5964 bytes_acked:5965 bytes_received:20632 segs_out:1291
tcp ESTAB 0 0 [2a02:1::5]:51234 [2a00:1450::200e]:443 users:(("brave",pid=41006,fd=99))
\t cubic bytes_acked:1000 bytes_received:50000
tcp TIME-WAIT 0 0 192.168.178.28:40000 1.2.3.4:443
"""


class Parsing(unittest.TestCase):
    def test_sockets_and_owners(self):
        conns, counters = net.parse_ss(SS)
        self.assertEqual(len(conns), 10)
        kde = next(c for c in conns if c.pid == 54671)
        self.assertEqual((kde.proto, kde.lport, kde.raddr, kde.listening, kde.exposed),
                         ("udp", 1716, "", True, True))
        steam_pub = next(c for c in conns if c.lport == 27036)
        steam_loc = next(c for c in conns if c.lport == 57343)
        self.assertTrue(steam_pub.exposed)
        self.assertTrue(steam_loc.listening)
        self.assertFalse(steam_loc.exposed, "127.0.0.1 is only this PC")
        claude = next(c for c in conns if c.pid == 35084)
        self.assertEqual((claude.raddr, claude.rport, claude.state), ("35.190.46.17", 443, "ESTAB"))
        v6 = next(c for c in conns if c.pid == 41006)
        self.assertEqual(v6.raddr, "[2a00:1450::200e]")
        self.assertEqual(sum(1 for c in conns if not c.pid), 3, "sockets we cannot attribute")

    def test_counters_follow_their_socket(self):
        _, counters = net.parse_ss(SS)
        self.assertEqual(len(counters), 3)
        key = next(k for k in counters if k[5] == 35084)
        self.assertEqual(counters[key], (1454, 2064))   # (received, acked)

    def test_split_addr(self):
        self.assertEqual(net.split_addr("192.168.178.28%wlan0:46516"), ("192.168.178.28", 46516))
        self.assertEqual(net.split_addr("*:1716"), ("*", 1716))
        self.assertEqual(net.split_addr("[::]:5353"), ("[::]", 5353))
        self.assertEqual(net.split_addr("0.0.0.0:*"), ("0.0.0.0", 0))

    def test_services(self):
        s = net.load_services()
        self.assertEqual(s.get(443), "https")
        self.assertEqual(s.get(1716), "KDE Connect")
        self.assertTrue(net.is_vpn_interface("proton0"))
        self.assertTrue(net.is_vpn_interface("wg0"))
        self.assertFalse(net.is_vpn_interface("wlan0"))


class Rates(unittest.TestCase):
    def test_tcp_rates_from_two_scans(self):
        first = SS
        second = SS.replace("bytes_acked:2064 bytes_received:1454",
                            "bytes_acked:12064 bytes_received:51454")
        outputs = iter([first, second])
        s = net.NetSampler(runner=lambda: next(outputs))
        s._interfaces = lambda now: []          # not under test here
        a = s.sample({35084: "Claude"})
        self.assertEqual(a.procs[35084].rx_bps, 0.0, "no rate on the first scan")
        s._prev_ts -= 10.0                       # pretend ten seconds passed
        b = s.sample({35084: "Claude"})
        self.assertAlmostEqual(b.procs[35084].rx_bps, 5000.0, delta=50)
        self.assertAlmostEqual(b.procs[35084].tx_bps, 1000.0, delta=10)
        self.assertEqual(b.procs[35084].name, "Claude")
        self.assertEqual(b.other_sockets, 3)
        self.assertTrue(b.tcp_rates)

    def test_without_ss(self):
        s = net.NetSampler(runner=lambda: None)
        s._interfaces = lambda now: []
        snap = s.sample()
        self.assertFalse(snap.tcp_rates)
        self.assertEqual(snap.procs, {})


class Payload(unittest.TestCase):
    def test_widget_payload(self):
        outputs = iter([SS, SS.replace("bytes_received:50000", "bytes_received:1050000")])
        s = net.NetSampler(runner=lambda: next(outputs))
        s._interfaces = lambda now: [net.Interface("wlan0", True, 100.0, 50.0, False, "10.0.0.2"),
                                     net.Interface("proton0", True, 90.0, 40.0, True)]
        s.sample(); s._prev_ts -= 10.0
        snap = s.sample()
        p = net.to_payload(snap, {41006: "Brave", 6463: "Steam", 54671: "KDE Connect"})
        self.assertEqual(p["ifaces"][1]["vpn"], True)
        self.assertEqual(p["top"][0]["name"], "Brave")
        self.assertGreater(p["top"][0]["rx"], 90000)
        doors = {d["name"]: d["ports"] for d in p["listening"]}
        self.assertEqual(doors["Steam"], [27036])
        self.assertEqual(doors["KDE Connect"], [1716])
        self.assertEqual(p["connections"], 3)


if __name__ == "__main__":
    unittest.main()
