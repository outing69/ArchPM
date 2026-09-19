"""Who talks to the network: connections per process, TCP bytes per socket,
throughput per interface. No root, no packet capture, no Qt.

One `ss -tunapiH` call per scan lists every socket. For our own processes it
names the owner (`users:(("brave",pid=…))`; other users' sockets have no pid
because their /proc/<pid>/fd is not ours to read). For TCP it adds an info line
with the kernel's byte counters; the difference between two scans is a rate.
UDP has no counters, so a game's traffic shows up as connections, not as a
speed. That is the honest limit of doing this without root.

Ports get a name from /etc/services (local file, no lookups) plus a few that
matter on a gaming PC. Addresses are shown as they are: no DNS, no geolocation.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from .toolenv import english

_USERS = re.compile(r'users:\(\("([^"]*)",pid=(\d+),fd=\d+\)')
_BYTES = re.compile(r"bytes_acked:(\d+)|bytes_received:(\d+)")
_PORT_RE = re.compile(r"^(?P<host>.*):(?P<port>\d+|\*)$")
VPN_PREFIXES = ("tun", "tap", "wg", "proton", "nordlynx", "mullvad", "ppp", "vpn", "ipsec")
EXTRA_SERVICES = {
    27015: "Steam / Source games", 27036: "Steam", 27031: "Steam", 3478: "STUN (voice/video)",
    5353: "mDNS (local discovery)", 1716: "KDE Connect", 1900: "SSDP (UPnP)", 5355: "LLMNR",
    8080: "HTTP (alt)", 3389: "Remote Desktop", 25565: "Minecraft", 6881: "BitTorrent",
    32400: "Plex", 47984: "Sunshine / Moonlight", 47989: "Sunshine / Moonlight",
}


@dataclass(frozen=True)
class Conn:
    proto: str            # "tcp" or "udp"
    state: str            # ESTAB, LISTEN, UNCONN, TIME-WAIT, ...
    laddr: str
    lport: int
    raddr: str            # "" when not connected
    rport: int
    pid: int              # 0 when not ours

    @property
    def listening(self) -> bool:
        return self.state == "LISTEN" or (self.proto == "udp" and self.state == "UNCONN"
                                          and not self.raddr and self.lport > 0)

    @property
    def local_only(self) -> bool:
        local = ("127.", "::1", "[::1]")
        return self.laddr.startswith(local) or self.raddr.startswith(local)

    @property
    def exposed(self) -> bool:
        """Listening on every address: reachable from the network, not just this PC."""
        return self.listening and self.laddr in ("0.0.0.0", "*", "[::]", "::")


@dataclass
class ProcNet:
    pid: int
    name: str
    conns: list[Conn] = field(default_factory=list)
    rx_bps: float = 0.0   # TCP only
    tx_bps: float = 0.0

    @property
    def established(self) -> int:
        return sum(1 for c in self.conns if c.state == "ESTAB")

    @property
    def listening(self) -> list[Conn]:
        return [c for c in self.conns if c.listening]


@dataclass
class Interface:
    name: str
    up: bool
    rx_bps: float
    tx_bps: float
    vpn: bool
    addr: str = ""


@dataclass
class NetSnapshot:
    ts: float
    interfaces: list[Interface]
    procs: dict[int, ProcNet]          # pid -> its sockets and rates (own processes)
    other_sockets: int                 # sockets we cannot attribute (other users)
    tcp_rates: bool                    # False when ss was missing


# -- parsing ----------------------------------------------------------------------
def split_addr(text: str) -> tuple[str, int]:
    """'192.0.2.10%wlan0:46516' -> ('192.0.2.10', 46516); '*:1716' -> ('*', 1716)."""
    m = _PORT_RE.match(text.strip())
    if not m:
        return text, 0
    host = m.group("host")
    host = host.split("%", 1)[0]      # drop the scope id
    port = 0 if m.group("port") == "*" else int(m.group("port"))
    return host, port


def parse_ss(text: str) -> tuple[list[Conn], dict[tuple, tuple[int, int]]]:
    """Sockets from `ss -tunapiH` output, and the TCP byte counters per socket key."""
    conns: list[Conn] = []
    counters: dict[tuple, tuple[int, int]] = {}
    last_key: tuple | None = None
    for line in text.splitlines():
        if not line.strip():
            continue
        if line[0].isspace():                        # info line of the socket above
            if last_key is not None:
                acked = received = 0
                for m in _BYTES.finditer(line):
                    if m.group(1):
                        acked = int(m.group(1))
                    elif m.group(2):
                        received = int(m.group(2))
                if acked or received:
                    counters[last_key] = (received, acked)
            continue
        parts = line.split(None, 6)
        if len(parts) < 6:
            last_key = None
            continue
        proto, state, _rq, _sq, local, peer = parts[:6]
        rest = parts[6] if len(parts) > 6 else ""
        laddr, lport = split_addr(local)
        raddr, rport = split_addr(peer)
        if raddr in ("*", "0.0.0.0", "[::]", "::") and rport == 0:
            raddr = ""
        m = _USERS.search(rest)
        pid = int(m.group(2)) if m else 0
        proto = "tcp" if proto.startswith("tcp") else ("udp" if proto.startswith("udp") else proto)
        c = Conn(proto, state, laddr, lport, raddr, rport, pid)
        conns.append(c)
        last_key = (proto, laddr, lport, raddr, rport, pid) if proto == "tcp" else None
    return conns, counters


def load_services(path: Path = Path("/etc/services")) -> dict[int, str]:
    out: dict[int, str] = dict(EXTRA_SERVICES)
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            fields = line.split()
            if len(fields) < 2 or "/" not in fields[1]:
                continue
            port_s, proto = fields[1].split("/", 1)
            if proto == "tcp" and port_s.isdigit():
                out.setdefault(int(port_s), fields[0])
    except OSError:
        pass
    return out


def is_vpn_interface(name: str) -> bool:
    return name.lower().startswith(VPN_PREFIXES)


# -- sampling ---------------------------------------------------------------------
def _run_ss() -> str | None:
    if not shutil.which("ss"):
        return None
    try:
        proc = subprocess.run(["ss", "-tunapiH"], capture_output=True, text=True, timeout=10,
                              check=False, env=english())
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout


class NetSampler:
    def __init__(self, runner=_run_ss) -> None:
        self._run = runner
        self._prev_counters: dict[tuple, tuple[int, int]] = {}
        self._prev_ts = 0.0
        self._prev_nic: dict[str, tuple[int, int]] = {}
        self._nic_ts = 0.0
        self.services = load_services()

    def service(self, port: int) -> str:
        return self.services.get(port, "")

    def sample(self, names: dict[int, str] | None = None) -> NetSnapshot:
        """`names` maps pid -> display name for the processes we know."""
        now = time.time()
        text = self._run()
        conns, counters = parse_ss(text) if text is not None else ([], {})

        # per-process TCP rates from the counter deltas
        rates: dict[int, list[float]] = {}
        dt = now - self._prev_ts if self._prev_ts else 0.0
        if dt > 0:
            for key, (rx, tx) in counters.items():
                prev = self._prev_counters.get(key)
                if prev is None:
                    continue
                pid = key[5]
                if not pid:
                    continue
                d_rx, d_tx = max(0, rx - prev[0]), max(0, tx - prev[1])
                r = rates.setdefault(pid, [0.0, 0.0])
                r[0] += d_rx / dt
                r[1] += d_tx / dt
        self._prev_counters = counters
        self._prev_ts = now

        procs: dict[int, ProcNet] = {}
        other = 0
        for c in conns:
            if not c.pid:
                other += 1
                continue
            pn = procs.get(c.pid)
            if pn is None:
                pn = ProcNet(c.pid, (names or {}).get(c.pid, ""))
                procs[c.pid] = pn
            pn.conns.append(c)
        for pid, (rx, tx) in rates.items():
            if pid in procs:
                procs[pid].rx_bps, procs[pid].tx_bps = rx, tx

        return NetSnapshot(ts=now, interfaces=self._interfaces(now), procs=procs,
                           other_sockets=other, tcp_rates=text is not None)

    def _interfaces(self, now: float) -> list[Interface]:
        counters = psutil.net_io_counters(pernic=True)
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
        dt = now - self._nic_ts if self._nic_ts else 0.0
        out: list[Interface] = []
        for name, c in counters.items():
            if name == "lo":
                continue
            prev = self._prev_nic.get(name)
            rx = tx = 0.0
            if prev is not None and dt > 0:
                rx = max(0, c.bytes_recv - prev[0]) / dt
                tx = max(0, c.bytes_sent - prev[1]) / dt
            self._prev_nic[name] = (c.bytes_recv, c.bytes_sent)
            st = stats.get(name)
            v4 = [a.address for a in addrs.get(name, []) if a.family.name == "AF_INET"]
            out.append(Interface(name, bool(st and st.isup), rx, tx, is_vpn_interface(name),
                                 v4[0] if v4 else ""))
        self._nic_ts = now
        out.sort(key=lambda i: (not i.up, -(i.rx_bps + i.tx_bps), i.name))
        return out


def to_payload(snap: NetSnapshot, names: dict[int, str], top_n: int = 5) -> dict:
    """The widget's view of the network: interfaces, top talkers, open doors."""
    talkers = sorted(snap.procs.values(), key=lambda p: p.rx_bps + p.tx_bps, reverse=True)
    talkers = [p for p in talkers if p.rx_bps + p.tx_bps >= 1024][:top_n]
    listening = {p.pid: p for p in snap.procs.values() if any(c.exposed for c in p.conns)}
    return {
        "ifaces": [{"name": i.name, "up": i.up, "rx": round(i.rx_bps), "tx": round(i.tx_bps),
                    "vpn": i.vpn, "addr": i.addr} for i in snap.interfaces],
        "top": [{"name": names.get(p.pid, p.name) or p.name, "pid": p.pid,
                 "rx": round(p.rx_bps), "tx": round(p.tx_bps), "conns": p.established}
                for p in talkers],
        "listening": [{"name": names.get(p.pid, p.name) or p.name, "pid": p.pid,
                       "ports": sorted({c.lport for c in p.conns if c.exposed})}
                      for p in listening.values()],
        "connections": sum(p.established for p in snap.procs.values()),
        "tcp_rates": snap.tcp_rates,
    }
