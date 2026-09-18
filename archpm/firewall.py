"""The firewall, read-only: which one this machine has, whether it is on,
what it does with incoming traffic no rule covers, and which ports it lets
other machines reach. Read once when the Network page opens and again on
the block's own Refresh, never on the sampling cycle, never on a timer (the
failed services check's pattern). ArchPM changes no rule and switches no
firewall on or off; what it would take to do that is not in this file.

What reads without root: which tools are installed (their binaries), which
of their units run (`systemctl is-active` answers a plain user), and ufw's
own ENABLED flag in /etc/ufw/ufw.conf, which is world-readable and says
whether ufw is set to start at boot, not whether its rules are loaded now.
`ufw status` refuses a plain user outright ("You need to be root to run
this script"), and so do `nft list ruleset` and `iptables -S`. firewalld
answers `firewall-cmd` over D-Bus, and its polkit policy lets an active
session read (state, default zone, list-all) without root; that is taken
from firewalld's own policy, not verified on a machine that has it. When
the plain read is refused, the page reads through the root helper on
request; the helper runs the tool's own status command and nothing else,
and this file parses what either side returns.

The raw nftables ruleset is shown to nobody: it is unreadable for this
audience. ufw's and firewalld's status output is read where those are the
tool in use. A machine with only nftables.service or iptables.service gets
one line: that it runs, and that its rules are not summarised here. A
machine with none of them gets one line too, without advice.

No Qt in this file.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field

UFW, FIREWALLD, NFTABLES, IPTABLES = "ufw", "firewalld", "nftables", "iptables"
TOOL_NAME = {UFW: "ufw", FIREWALLD: "firewalld", NFTABLES: "nftables", IPTABLES: "iptables"}
UNITS = ("ufw.service", "firewalld.service", "nftables.service", "iptables.service",
         "ip6tables.service")
UFW_CONF = "/etc/ufw/ufw.conf"
TIMEOUT = 10
FOLD_ABOVE = 6           # more doors than this fold behind their count until opened
ENV = {"PATH": "/usr/bin:/usr/sbin:/bin:/sbin", "LC_ALL": "C"}   # the tools' English

# the default for incoming traffic, in plain words; the tools' own words are
# deny/reject/allow (ufw) and a zone target of default, DROP, %%REJECT%% or
# ACCEPT (firewalld)
DROP, REJECT, ALLOW = "drop", "reject", "allow"
INCOMING_WORDS = {
    DROP: "Whatever arrives that no rule covers is dropped without a reply.",
    REJECT: "Whatever arrives that no rule covers is refused, and the sender is told.",
    ALLOW: "Whatever arrives is let in unless a rule blocks it.",
}


@dataclass
class Rule:
    """One line of a status table that opens something: what (a port, a
    range, an application profile, or everything), to whom, on which
    interface. A rule that blocks is not kept: the default already says
    what happens to the rest, and a block on top of a deny default changes
    nothing a reader of three lines needs."""
    to: str                       # "22/tcp", "1714:1764/udp", "KDE Connect", "Anywhere"
    source: str = ""              # "" for anywhere, else "192.168.1.0/24" or a host
    iface: str = ""               # "" for every interface, else "virbr0"
    limited: bool = False         # ufw LIMIT: open, but rate-limited

    @property
    def port(self) -> int:
        """The port when `to` is one port: 22 for "22/tcp", 0 otherwise."""
        m = re.fullmatch(r"(\d+)(?:/(?:tcp|udp))?", self.to)
        return int(m.group(1)) if m else 0

    def text(self, service=None) -> str:
        """One row: "22/tcp · ssh · on virbr0 · from 192.168.1.0/24", the
        port and protocol, the service's name, the interface or source
        where there is one, the way a socket is a row under a program."""
        parts = ["everything" if self.to.lower() == "anywhere" else self.to]
        name = service(self.port) if service and self.port else ""
        if name:
            parts.append(name)
        if self.iface:
            parts.append(f"on {self.iface}")
        if self.source:
            parts.append(f"from {self.source}")
        if self.limited:
            parts.append("rate-limited")
        return " · ".join(parts)


@dataclass
class Setup:
    ufw: bool = False             # the binary
    firewalld: bool = False
    active: dict[str, bool] = field(default_factory=dict)   # unit -> running
    ufw_enabled: bool | None = None   # ENABLED= in ufw.conf; None when unreadable or absent

    @property
    def tool(self) -> str:
        """The firewall in use: the one whose unit runs, else the one
        installed, ufw before firewalld; nftables or iptables only when
        their unit runs and neither front end is installed."""
        if self.firewalld and self.active.get("firewalld.service"):
            return FIREWALLD
        if self.ufw:
            return UFW
        if self.firewalld:
            return FIREWALLD
        if self.active.get("nftables.service"):
            return NFTABLES
        if self.active.get("iptables.service") or self.active.get("ip6tables.service"):
            return IPTABLES
        return ""


@dataclass
class State:
    tool: str = ""
    running: bool | None = None   # None: not known without root
    incoming: str = ""            # DROP, REJECT, ALLOW, or "" when not known
    rules: list[Rule] = field(default_factory=list)   # what is open, IPv4 and IPv6 folded
    needs_root: bool = False      # the plain read was refused
    as_root: bool = False         # read through the helper
    took_ms: float = 0.0          # the tool's own time
    call_ms: float = 0.0          # the whole helper call, pkexec included (as_root only)
    taken_at: float = 0.0
    error: str = ""

    @property
    def known(self) -> bool:
        """The rules were read, by either route."""
        return self.running is not None and not self.needs_root


# -- detection -----------------------------------------------------------------
def unit_active(unit: str, run=subprocess.run) -> bool:
    """`systemctl is-active` answers a plain user; "active" is the only yes."""
    try:
        proc = run(["systemctl", "is-active", unit], capture_output=True, text=True,
                   timeout=TIMEOUT, check=False, env=ENV)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return (proc.stdout or "").strip() == "active"


def ufw_enabled(path: str = UFW_CONF) -> bool | None:
    """ENABLED=yes in ufw.conf: set to start at boot, which is what `ufw
    enable` writes and `ufw disable` clears. World-readable. It is not the
    live state: a masked unit leaves the file saying yes and the rules
    unloaded, so the page treats it as a hint, never as the answer."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                key, _, value = line.partition("=")
                if key.strip() == "ENABLED":
                    return value.strip().strip('"').lower() == "yes"
    except OSError:
        return None
    return None


def detect(which=shutil.which, run=subprocess.run, conf: str = UFW_CONF) -> Setup:
    setup = Setup(ufw=which("ufw") is not None, firewalld=which("firewall-cmd") is not None,
                  active={u: unit_active(u, run) for u in UNITS})
    if setup.ufw:
        setup.ufw_enabled = ufw_enabled(conf)
    return setup


# -- parsing: ufw's own status output -------------------------------------------
_UFW_RULE = re.compile(r"^(?P<to>.+?)\s{2,}(?P<action>ALLOW|DENY|REJECT|LIMIT)"
                       r"(?:\s+(?P<dir>IN|OUT|FWD))?\s{2,}(?P<from>.+?)\s*$")
_UFW_DEFAULT = re.compile(r"^Default:\s*(?P<in>\w+)\s*\(incoming\)")
_ON_IFACE = re.compile(r"^(?P<what>.+?)\s+on\s+(?P<iface>\S+)$")
_V6 = re.compile(r"\s*\(v6\)")
UFW_INCOMING = {"deny": DROP, "reject": REJECT, "allow": ALLOW}


def parse_ufw(text: str) -> State:
    """`ufw status verbose`: "Status: active" or "Status: inactive", then
    "Default: deny (incoming), allow (outgoing), disabled (routed)", then a
    table of To / Action / From. The To column may hold spaces ("53/udp on
    virbr0", "KDE Connect"), so the columns are split at two spaces or more.
    A rule's IPv6 twin ("22/tcp (v6)  ALLOW IN  Anywhere (v6)") folds into
    its IPv4 line; a comment after the From column is dropped."""
    state = State(tool=UFW)
    seen: set[tuple[str, str, str]] = set()
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if line.startswith("Status:"):
            state.running = line.split(":", 1)[1].strip().lower() == "active"
            continue
        m = _UFW_DEFAULT.match(line)
        if m:
            state.incoming = UFW_INCOMING.get(m.group("in").lower(), "")
            continue
        m = _UFW_RULE.match(line)
        if not m or m.group("to") in ("To", "--"):
            continue
        if m.group("dir") not in (None, "IN") or m.group("action") not in ("ALLOW", "LIMIT"):
            continue
        to = _V6.sub("", m.group("to")).strip()
        source = _V6.sub("", m.group("from")).split("#", 1)[0].strip()
        iface = ""
        mi = _ON_IFACE.match(to)
        if mi:
            to, iface = mi.group("what"), mi.group("iface")
        if source.lower() == "anywhere":
            source = ""
        else:
            mi = _ON_IFACE.match(source)
            if mi:
                source, iface = mi.group("what"), iface or mi.group("iface")
        key = (to, source, iface)
        if key in seen:
            continue
        seen.add(key)
        state.rules.append(Rule(to, source, iface, limited=m.group("action") == "LIMIT"))
    if state.running is None:
        state.error = "ufw's status output was not understood"
    return state


# -- parsing: firewalld's own output ---------------------------------------------
FIREWALLD_TARGET = {"default": REJECT, "%%reject%%": REJECT, "reject": REJECT,
                    "drop": DROP, "accept": ALLOW}


def parse_firewalld(state_text: str, zone: str, list_all: str) -> State:
    """`firewall-cmd --state` ("running" / "not running"), `--get-default-zone`
    and `--list-all` for it: an indented "target: default", "services: ssh
    dhcpv6-client", "ports: 8080/tcp", "interfaces: wlan0", "sources:". The
    public zone's "default" target rejects with an ICMP reply; drop drops;
    ACCEPT (the trusted zone) lets everything in."""
    state = State(tool=FIREWALLD)
    state.running = (state_text or "").strip().lower().startswith("running")
    fields: dict[str, str] = {}
    for line in (list_all or "").splitlines():
        if not line.startswith((" ", "\t")):
            continue
        key, _, value = line.strip().partition(":")
        fields[key.strip().lower()] = value.strip()
    state.incoming = FIREWALLD_TARGET.get(fields.get("target", "").lower(), "")
    ifaces = fields.get("interfaces", "").split()
    iface = ifaces[0] if len(ifaces) == 1 else ""
    sources = fields.get("sources", "").split()
    source = ", ".join(sources) if sources else ""
    for svc in fields.get("services", "").split():
        state.rules.append(Rule(svc, source, iface))
    for port in fields.get("ports", "").split():
        state.rules.append(Rule(port, source, iface))
    if state.incoming == ALLOW and not state.rules:
        state.rules.append(Rule("Anywhere", source, iface))
    if state.running and not fields and not zone:
        state.error = "firewalld's zone output was not understood"
    return state


def parse(tool: str, outputs: list) -> State:
    """(name, text) pairs from the plain read or the helper's reply."""
    texts = {name: text for name, text in outputs}
    if tool == UFW:
        return parse_ufw(texts.get("status", ""))
    if tool == FIREWALLD:
        return parse_firewalld(texts.get("state", ""), texts.get("zone", ""),
                               texts.get("list-all", ""))
    return State(tool=tool, error=f"no parser for {tool}")


# -- the plain read ------------------------------------------------------------------
def _cmd(argv: list[str], run=subprocess.run):
    return run(argv, capture_output=True, text=True, timeout=TIMEOUT, check=False, env=ENV)


def read_as_user(setup: Setup | None = None, run=subprocess.run) -> State:
    """Try without root. ufw refuses every plain user, so it is not even
    asked (Timeshift's pattern on the Snapshots page); firewalld answers a
    plain user in an active session; nftables and iptables alone are
    summarised from their unit's state and nothing else."""
    setup = detect(run=run) if setup is None else setup
    tool = setup.tool
    state = State(tool=tool, taken_at=time.time())
    if not tool:
        return state
    if tool == UFW:
        state.needs_root = True
        return state
    if tool in (NFTABLES, IPTABLES):
        state.running = True
        return state
    start = time.perf_counter()
    outputs: list[tuple[str, str]] = []
    zone = ""
    for name, argv in (("state", ["firewall-cmd", "--state"]),
                       ("zone", ["firewall-cmd", "--get-default-zone"]),
                       ("list-all", ["firewall-cmd", "--zone=", "--list-all"])):
        if name == "list-all":
            argv[1] = f"--zone={zone}"
        try:
            proc = _cmd(argv, run)
        except (OSError, subprocess.TimeoutExpired) as exc:
            state.error = f"firewall-cmd could not be asked: {exc}"
            return state
        text = (proc.stdout or "").strip()
        if proc.returncode != 0:
            err = ((proc.stderr or "") + (proc.stdout or "")).strip()
            if name == "state" and ("not running" in err.lower() or proc.returncode == 252):
                outputs.append(("state", "not running"))
                break
            if _refused(err):
                state.needs_root = True
                return state
            state.error = _last_line(err) or f"firewall-cmd returned code {proc.returncode}"
            return state
        outputs.append((name, text))
        if name == "zone":
            zone = text
    parsed = parse(FIREWALLD, outputs)
    parsed.taken_at, parsed.took_ms = state.taken_at, (time.perf_counter() - start) * 1000
    return parsed


def _refused(err: str) -> bool:
    """firewalld says NOT_AUTHORIZED (its D-Bus error) or "Authorization
    failed"; a tool that checks itself says "permission" or "denied"."""
    low = err.lower()
    return any(word in low for word in ("not_authorized", "not authorized", "authoriz",
                                        "permission", "access denied"))


def _last_line(err: str) -> str:
    lines = [ln for ln in err.splitlines() if ln.strip()]
    return lines[-1].strip() if lines else ""


def from_helper(result: dict) -> State:
    """The helper's `firewall-status` reply: {"tool", "outputs": [[name, text]], "took_ms"}."""
    tool = str(result.get("tool") or "")
    state = parse(tool, [tuple(o) for o in result.get("outputs") or [] if len(o) == 2])
    state.as_root, state.taken_at = True, time.time()
    state.took_ms = float(result.get("took_ms") or 0.0)
    return state


# -- text: the three lines and the rows ---------------------------------------------
@dataclass
class Block:
    """What the page shows: the summary lines (two at most), the doors line
    (the count, "" when the doors are one sentence in `lines` instead), one
    row per door, and a read's error when there is one."""
    lines: list[str] = field(default_factory=list)
    doors: str = ""
    rows: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def folded(self) -> bool:
        """Closed by default: the rows wait behind their count."""
        return len(self.rows) > FOLD_ABOVE


def block(setup: Setup, state: State, service=None, helper_ready: bool = True,
          helper_path: str = "") -> Block:
    """Three lines at most: whether a firewall runs and which; what it does
    with incoming traffic no rule covers, in plain words; how many doors it
    opens to other machines, with one row per door under it. A read that
    failed adds its reason as one more line, under what is known.
    `service` maps a port to its name, as the page does elsewhere."""
    out = Block(lines=_lines(setup, state, service, helper_ready, helper_path),
                error=f"Not read: {state.error}" if state.error else "")
    if state.known and state.running and state.rules and tool_reads(setup.tool):
        n = len(state.rules)
        out.doors = f"{n} {'door' if n == 1 else 'doors'} open to other machines"
        out.rows = [r.text(service) for r in state.rules]
    return out


def tool_reads(tool: str) -> bool:
    return tool in (UFW, FIREWALLD)


def lines(setup: Setup, state: State, service=None, helper_ready: bool = True,
          helper_path: str = "") -> list[str]:
    """The block as lines: the summary, the doors line, the error."""
    b = block(setup, state, service, helper_ready, helper_path)
    return b.lines + ([b.doors] if b.doors else []) + ([b.error] if b.error else [])


def _lines(setup: Setup, state: State, service, helper_ready: bool, helper_path: str) -> list[str]:
    tool = setup.tool
    if not tool:
        return ["No firewall: nothing on this machine filters incoming connections, so every "
                "open door above is reachable from the network."]
    name = TOOL_NAME.get(tool, tool)
    if tool in (NFTABLES, IPTABLES):
        return [f"{name} is running ({tool}.service); its rules are not summarised here."]
    if state.needs_root and not state.as_root:
        first = _installed_line(setup) if tool == UFW else f"{name} is installed."
        if not helper_ready:
            where = f" ({helper_path})" if helper_path else ""
            return [first, f"What it allows needs the root helper, and the root helper is not "
                           f"installed{where}."]
        return [first, "What it allows needs the root helper: Read the firewall asks for your "
                       "password once; the next few minutes need none."]
    if not state.known:
        return [f"{name} is installed; its state was not read."]
    if not state.running:
        return [f"{name} is installed but off: nothing filters incoming connections, so every "
                "open door above is reachable from the network."]
    out = [f"{name} is on."]
    if state.incoming:
        out.append(INCOMING_WORDS[state.incoming])
    if not state.rules:
        out.append(doors_sentence(state))
    return out


def _installed_line(setup: Setup) -> str:
    """ufw without root: what the plain facts say, and no more than that."""
    running = setup.active.get("ufw.service")
    if setup.ufw_enabled is False:
        return "ufw is installed and switched off (ufw.conf says ENABLED=no)."
    if setup.ufw_enabled and running:
        return "ufw is installed, set to start at boot, and its service is running."
    if running:
        return "ufw is installed and its service is running."
    return "ufw is installed; its service is not running."


def doors_sentence(state: State) -> str:
    """The third line when there is no row to show: the default lets
    everything in, or nothing is open."""
    if state.incoming == ALLOW:
        return "Every open door above is reachable from other machines."
    return "No port is open to other machines."
