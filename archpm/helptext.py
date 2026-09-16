"""The Help tab's content: a glossary in plain language, what the colours mean,
and where the changelog lives. No Qt, so it can be tested and reused."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import __version__

REPO = "https://github.com/outing69/ArchPM"
ISSUES = f"{REPO}/issues"
LICENSE = "MIT"


@dataclass(frozen=True)
class Term:
    name: str
    text: str
    where: str = ""     # where you meet it in ArchPM


@dataclass(frozen=True)
class Section:
    title: str
    terms: tuple[Term, ...]


GLOSSARY: tuple[Section, ...] = (
    Section("Processes", (
        Term("Process",
             "A running program, or one piece of it. A browser is many processes: one "
             "main window, one per tab, a few helpers. The Processes tab shows them as a "
             "tree so the pieces stay under the program they belong to.",
             "Processes tab"),
        Term("PID",
             "Process ID: the number the system gives every process when it starts. It is "
             "unique while the process runs, and may be reused by a new process later. "
             "It is how you tell two processes with the same name apart.",
             "PID column"),
        Term("Parent and children",
             "Every process was started by another one, its parent. Kill a parent and its "
             "children usually keep running as orphans; that is why \"Terminate with "
             "children\" exists.",
             "Tree view, right-click menu"),
        Term("Thread",
             "One line of work inside a process. A game with 160 threads is not using 160 "
             "cores; most threads sleep most of the time. The Thr column counts them.",
             "Thr column"),
        Term("Status",
             "What the process is doing right now. \"sleeping\" is normal: it waits for "
             "something to do. \"running\" means it is on a CPU this instant. \"stopped\" "
             "means it was paused with Suspend. \"zombie\" is a finished process whose "
             "parent has not collected it yet; it uses nothing and goes away on its own.",
             "Status column"),
        Term("Started",
             "How long ago the process began. Something that started \"just now\" is "
             "highlighted for a minute: when the PC suddenly slows down, that is usually "
             "the row you are looking for.",
             "Started column"),
        Term("Command",
             "The exact command line the process was started with, including its options. "
             "Useful to tell a browser tab from the browser itself.",
             "Command column, tooltip on the name"),
        Term("Category",
             "What kind of program it is, taken from its menu entry: Game, Internet, "
             "Office, System and so on. Steam games are Game. Processes without a menu "
             "entry have no category; that is normal for helpers and services.",
             "Processes tab, Category column and dropdown"),
        Term("User",
             "Whose process it is. Almost everything you see is yours; root owns the "
             "system's services and other names belong to services that run under their "
             "own account (for example \"nobody\" or \"systemd-network\"). ArchPM can only "
             "act on your own processes unless you unlock root.",
             "Processes tab, User column"),
        Term("Show all processes",
             "Off, the list shows your own programs (anything with a menu entry or a Steam "
             "game) plus whatever is actually busy. On, it shows every process on the "
             "machine, including the system's and the kernel's.",
             "Processes tab toolbar"),
    )),
    Section("CPU and priority", (
        Term("CPU %",
             "How much processor time a process uses. In the Processes tab 100% means one "
             "core fully used, so a game can show 140% on a 16-thread CPU; tick "
             "\"CPU% ÷ cores\" to see it as a share of the whole machine instead. The "
             "Overview always shows the share of the whole machine.",
             "CPU % column, Overview"),
        Term("Nice",
             "The process's priority, from -20 to 19. Lower is more important: nice -5 gets "
             "the CPU before nice 0, nice 19 only gets what is left. Raising the number "
             "(making a process less important) is always allowed; lowering it needs root, "
             "which is why \"Game priority\" asks for it. A game at nice -5 with the "
             "background at nice 10 stutters less.",
             "Nice column, right-click → Priority"),
        Term("Disk priority",
             "Like nice, but for reading and writing the disk. \"Idle only\" makes a process "
             "wait until nothing else wants the disk: right for a backup, wrong for a game.",
             "Right-click → Disk priority"),
        Term("Affinity",
             "Which cores a process may run on. Pinning a game to the physical cores (the "
             "even numbers) and away from core 0 sometimes smooths frame times. Threads is "
             "how many the process has; affinity is how many cores it is allowed.",
             "Right-click → CPU affinity, game card"),
        Term("CPU temperature",
             "The processor's own sensor; on Ryzen it is the one the chip uses to decide "
             "how fast it may boost (AMD calls it Tctl). Under 60 °C is idle, 70 to 85 °C "
             "under a game is normal, above 85 °C the tile turns red and the CPU will slow "
             "itself down to stay safe.",
             "Overview CPU TEMP tile"),
        Term("Load",
             "The average number of processes wanting the CPU over the last minute. Below "
             "the number of cores means nobody waits; above it means they queue.",
             "Overview CPU tile"),
        Term("Core strip",
             "One bar per logical core. A game using two cores at 100% and fourteen at 0% "
             "is CPU-bound on those two; the strip shows that where a total of 12% hides it.",
             "Overview, widget"),
    )),
    Section("Network and disk", (
        Term("Connection",
             "A conversation between a program on your PC and one somewhere else (or on this "
             "PC). A browser tab opens a few; a game opens one or two and keeps them. The "
             "Network tab lists them per program with the address and port on the other end.",
             "Network tab"),
        Term("Port",
             "The number behind the colon in an address: it says which service is meant. 443 "
             "is https, 22 is ssh, 27036 is Steam. ArchPM names the common ones from your own "
             "system's list; it never asks the internet.",
             "Network tab, Details column"),
        Term("Listening / open door",
             "A program waiting for others to connect to it. Listening on \"this PC only\" is "
             "harmless. Listening on every address means other devices on your network can "
             "reach it: normal for KDE Connect or Steam, worth a look for something you do "
             "not recognise.",
             "Network tab, Open doors card"),
        Term("TCP and UDP",
             "Two ways to send data. TCP checks that everything arrives, and the kernel counts "
             "its bytes, so ArchPM can show a speed per program. UDP just sends, which games "
             "prefer for low latency, and has no counters: a game shows connections, not a "
             "speed. The total speed on the Overview includes both.",
             "Network tab"),
        Term("Interface and VPN",
             "The wire the traffic goes over: wlan0 is Wi-Fi, enp… is a cable, and a name like "
             "proton0 or wg0 is a VPN tunnel. If the VPN interface carries the traffic and the "
             "Wi-Fi only a little, your VPN is doing its job.",
             "Network tab, Interfaces card"),
        Term("Download and upload",
             "Download is what comes in from the network, upload what goes out, for the "
             "whole machine. A game update downloads; a video call uploads too. The graph's "
             "scale adapts, so read the number in the corner, not just the shape.",
             "Overview Network & Disk card, widget footer"),
        Term("Disk read and write",
             "How much the disks move per second, all disks together. A game loading a level "
             "reads; a download or a recording writes. Per process it is the Disk I/O column.",
             "Overview Network & Disk card, Disk I/O column"),
    )),
    Section("Memory", (
        Term("Memory (RSS)",
             "How much RAM the process holds right now. A browser's tabs share a lot, so "
             "adding them up overcounts a little; the number is still the one that matters "
             "when RAM runs out.",
             "Memory column"),
        Term("Swap in RAM",
             "When RAM is full, the kernel moves the least-used parts to swap. On CachyOS "
             "swap usually lives in zram, a piece of RAM the kernel uses as compressed swap, "
             "much faster than a disk. Some swap "
             "in use is normal; swap growing while a game runs means you are out of RAM.",
             "Overview memory card, System tab"),
        Term("Swappiness",
             "How eagerly the kernel uses swap, 0 to 200. Higher with zram is fine; lower "
             "keeps more in RAM. Changing it needs root.",
             "Root tasks"),
        Term("Drop caches",
             "Asks the kernel to forget files it kept in RAM for speed. It frees memory on "
             "paper; the kernel would have done it itself the moment a program needed the "
             "RAM. Harmless, rarely useful.",
             "Root tasks"),
    )),
    Section("GPU", (
        Term("GPU load",
             "How busy the graphics chip is; NVIDIA calls its compute units SMs, which is "
             "why some tools say \"SM %\". Near 100% while gaming is good: the GPU is the "
             "bottleneck, as it should be. Low GPU with a low frame rate points at the CPU "
             "instead.",
             "GPU % column, Overview, game card"),
        Term("GPU temperature and fan",
             "Modern cards run 60 to 80 °C under load by design; the fan speed shows how hard "
             "the card works to stay there. A fan at 0% while idle is normal: many cards stop "
             "their fans below 50 °C.",
             "Overview GPU TEMP tile"),
        Term("VRAM",
             "The graphics card's own memory. When a game needs more than the card has, "
             "textures stream from RAM and frame times spike.",
             "VRAM column, Overview"),
        Term("Shader cache",
             "Compiled versions of a game's shaders, kept on disk so the next start is "
             "faster. Safe to delete; the cost is stutter during the first minutes as they "
             "are rebuilt.",
             "Cleanup tab"),
    )),
    Section("Stopping things", (
        Term("Terminate (SIGTERM)",
             "Asks the program to quit. It gets the chance to save and clean up. Try this "
             "first; it is what the Terminate button and the Delete key do.",
             "Right-click, Terminate button, Delete"),
        Term("Force kill (SIGKILL)",
             "The kernel ends the process on the spot. Nothing is saved. For a program that "
             "does not react to Terminate. Shift+Delete.",
             "Right-click, Shift+Delete"),
        Term("Suspend and resume",
             "Freezes a process without ending it (SIGSTOP) and lets it continue later "
             "(SIGCONT). Handy for a download while you play; not every program likes it.",
             "Right-click"),
    )),
    Section("Root and safety", (
        Term("Root",
             "The administrator account. Most of ArchPM works without it: your own "
             "processes, raising nice, affinity, your own session's services. Lowering "
             "nice, other users' processes, memory settings and the two cleanup items need it.",
             "Root tasks button"),
        Term("pkexec and polkit",
             "The standard way a desktop program asks for admin rights: polkit shows the "
             "password dialog, pkexec runs one small helper as root. ArchPM's helper is a "
             "single file that accepts only fixed commands and refuses anything that could "
             "break your session. It is described in SECURITY.md.",
             "Password dialog"),
        Term("Protected services",
             "ArchPM only manages the services of your own login session (systemctl --user), "
             "which needs no root; system services are left alone. It refuses to stop the "
             "ones your desktop itself runs on: plasmashell, kwin, the session manager, the "
             "session bus, pipewire, wireplumber and the desktop portal. Restarting them is "
             "allowed, that is how you recover them.",
             "Root tasks → your session's services"),
    )),
    Section("Startup and Cleanup", (
        Term("Autostart entry",
             "A small file that says \"start this program when I log in\". Yours live in "
             "~/.config/autostart, the system's in /etc/xdg/autostart. Switching one off "
             "writes an override in your own folder; nothing outside your home is touched.",
             "Startup tab"),
        Term("Desktop · keep on",
             "Entries that are parts of KDE Plasma itself: panels, shortcuts, power "
             "management, the password prompt. Switching them off breaks the next login.",
             "Startup tab, Kind column"),
        Term("Cache",
             "Data a program keeps to be faster next time: web pages, thumbnails, compiled "
             "shaders, downloaded packages. Deleting it costs a slower first start, never "
             "your files, saves or settings.",
             "Cleanup tab"),
        Term("Package cache",
             "pacman keeps every package it ever installed in /var/cache/pacman/pkg. ArchPM "
             "removes all but the last two versions of each, so you can still downgrade.",
             "Cleanup tab (needs root)"),
    )),
)

COLOURS: tuple[tuple[str, str], ...] = (
    ("Yellow", "Highlight. The active tab, the machine's name, the running game, values that "
               "deserve a look, and a process that started less than a minute ago."),
    ("Blue", "Selection. The selected row, ticked boxes, the focused field. Never anything "
             "else, so a blue row always means \"this is what you picked\"."),
    ("Green · orange · red", "Load and temperature. Green is fine, orange is busy or warm "
                             "(above 60%), red is hot or nearly full (above 85%). The same "
                             "scale everywhere: tiles, core strip, CPU column, widget."),
    ("Series colours", "Each measurement keeps one colour across the app: CPU yellow, GPU "
                       "purple, memory teal, network blue, disk pink, swap orange. A card's "
                       "title takes the colour of the data it shows."),
    ("Grey", "Context. Dimmed text is there when you need it and quiet when you don't: "
             "command lines, users, descriptions, other desktops' startup entries."),
)


@dataclass(frozen=True)
class Hint:
    """One sentence for a tooltip, an optional "is this normal?" line, and the
    glossary term that explains it in full (right-click → Help)."""
    text: str
    term: str = ""
    normal: str = ""


HINTS: dict[str, Hint] = {
    # -- Overview tiles ------------------------------------------------------
    "tile.cpu": Hint(
        "How busy the whole processor is, all cores together.", "CPU %",
        "Idle desktop 1–5%. A browser playing video 10–20%. A game 20–60%. "
        "Stuck at 100% with nothing open: look at Top processes."),
    "tile.cpu temp": Hint(
        "The processor's temperature (Tctl on AMD).", "CPU temperature",
        "Idle 40–55°. Gaming 60–85° is fine; modern CPUs are built to run up to about 95° "
        "and slow themselves down before harm."),
    "tile.gpu": Hint(
        "How hard the graphics card is working.", "GPU load",
        "Idle 0–5%. In a game 90–100% is what you want: the card is fully used. Much "
        "lower with a low frame rate means the CPU is holding it back."),
    "tile.gpu temp": Hint(
        "The graphics card's temperature and fan speed.", "GPU temperature and fan",
        "Idle 30–45°. Gaming 60–80°. Above 85° check dust and case airflow."),
    "tile.memory": Hint(
        "RAM in use by programs, as a share of what the PC has.", "Memory (RSS)",
        "Linux keeps spare RAM as cache, so a high number is not a problem by itself. "
        "It matters when Swap is rising too."),
    "tile.vram": Hint(
        "Graphics memory in use, mostly by games.", "VRAM",
        "A game fills most of it on purpose (textures loaded ahead). Full VRAM plus "
        "stutter means the game's settings are too high for this card."),
    # -- Overview cards --------------------------------------------------------
    "graph.cpu": Hint(
        "Total processor use over the last minutes, and one bar per core below.",
        "Core strip",
        "One tall bar with the rest low: a program that can only use one core. "
        "That is common and not a fault."),
    "graph.gpu": Hint(
        "Purple: how hard the card works. Pink: how full its memory is.", "GPU load",
        "In a game the purple line sits high and flat. Pink climbs when a level loads."),
    "graph.mem": Hint(
        "Green: RAM in use. Orange: swap in use.", "Swap in RAM",
        "Swap a little above zero is fine. Swap climbing while RAM is full means the PC "
        "is short of memory: close something."),
    "graph.net": Hint(
        "Download and upload of the whole PC, every interface together.",
        "Download and upload",
        "Spikes when a page loads or Steam updates; a steady stream while you do "
        "nothing deserves a look at the Network tab."),
    "graph.disk": Hint(
        "Bytes read from and written to disk per second.", "Disk read and write",
        "Big reads when a game loads a level. Constant writes with nothing open: "
        "a backup, an index, or a browser cache at work."),
    "top.cpu": Hint(
        "The five programs using the most processor right now, as a share of all cores.",
        "CPU %"),
    "top.mem": Hint("The five programs using the most RAM.", "Memory (RSS)"),
    "top.vram": Hint("The five programs holding the most graphics memory.", "VRAM"),
    # -- game card ---------------------------------------------------------------
    "game.cpu": Hint(
        "Processor used by the game and everything it started, as a share of all cores.",
        "CPU %", "Most games use two to six cores' worth; the rest of the CPU sits idle."),
    "game.gpu": Hint("How hard the game works the graphics card.", "GPU load",
                     "90–100% is the card fully used, which is what you want."),
    "game.vram": Hint("Graphics memory held by the game.", "VRAM"),
    "game.ram": Hint("RAM held by the game's whole process tree.", "Memory (RSS)"),
    "game.threads": Hint("Threads across the game's processes.", "Thread",
                         "Hundreds is normal for a modern game."),
    "game.cores": Hint("How many cores the game is allowed to use.", "Affinity",
                       "Usually all of them. Fewer only if you pinned it yourself."),
    "game.graph": Hint("CPU (yellow) and GPU (purple) of the game over the last minutes.",
                       "GPU load"),
    # -- Processes columns -------------------------------------------------------
    "col.pid": Hint("The number the system gave this process.", "PID"),
    "col.name": Hint("The program, with its icon when it has a menu entry; a collapsed "
                     "program shows the totals of everything under it.", "Process"),
    "col.cpu": Hint("Processor used by this row; 100% = one core fully used.", "CPU %"),
    "col.mem": Hint("RAM held by this process (RSS).", "Memory (RSS)"),
    "col.gpu": Hint("How hard this process works the graphics card.", "GPU load"),
    "col.vram": Hint("Graphics memory this process holds.", "VRAM"),
    "col.threads": Hint("Threads in this process.", "Thread"),
    "col.nice": Hint("Priority from -20 (first in line) to 19 (last); 0 is normal.", "Nice"),
    "col.io": Hint("Disk read plus write per second by this process.", "Disk read and write"),
    "col.user": Hint("Whose process it is.", "User"),
    "col.status": Hint("Running, sleeping (waiting for something) or stopped.", "Status"),
    "col.started": Hint("How long ago the process started.", "Started"),
    "col.category": Hint("What kind of program it is, from its menu entry.", "Category"),
    "col.cmd": Hint("The exact command that started it.", "Command"),
    # -- Network -------------------------------------------------------------------
    "net.interfaces": Hint("Your network cards and tunnels, with the speed on each.",
                           "Interface and VPN",
                           "With a VPN on, the tunnel carries the traffic and the Wi-Fi "
                           "or cable shows about the same amount."),
    "net.doors": Hint("Programs that other devices on your network can connect to.",
                      "Listening / open door",
                      "KDE Connect, Steam and a printer helper are normal here. A "
                      "program you do not recognise deserves a look."),
    "net.program": Hint("The program; expand it to see each connection. A program that "
                        "holds sockets in several processes, like a browser, shows one row "
                        "per process in between.", "Connection"),
    "net.connections": Hint("Open conversations with another computer.", "Connection",
                            "A browser opens dozens; a game a handful."),
    "net.download": Hint("Bytes received per second over TCP by this program.",
                         "TCP and UDP"),
    "net.upload": Hint("Bytes sent per second over TCP by this program.", "TCP and UDP"),
    "net.listening": Hint("Ports this program waits on; orange when reachable from "
                          "other devices.", "Listening / open door"),
    "net.details": Hint("Sockets and process ids; a process row lists its ports here while "
                        "closed. Expand a row for each address and port.", "Port"),
    # -- Startup ------------------------------------------------------------------
    "startup.on": Hint("Ticked: starts at your next login. Untick to stop that; nothing "
                       "is closed now.", "Autostart entry"),
    "startup.name": Hint("The program that starts when you log in.", "Autostart entry"),
    "startup.what": Hint("What the program is for, from its menu entry.", "Autostart entry"),
    "startup.status": Hint("Whether it is running right now.", "Autostart entry"),
    "startup.kind": Hint("Desktop · keep on marks parts of Plasma itself.",
                         "Desktop · keep on"),
    "startup.source": Hint("Where the entry lives: your home folder or the system.",
                           "Autostart entry"),
    # -- Cleanup ------------------------------------------------------------------
    "cleanup.on": Hint("Tick what to remove; nothing goes until you press and confirm.",
                       "Cache"),
    "cleanup.what": Hint("The cache or leftover; every item comes back by itself when "
                         "needed.", "Cache"),
    "cleanup.why": Hint("Why removing it is safe.", "Cache"),
    "cleanup.size": Hint("Space you get back.", "Cache"),
    "cleanup.note": Hint("Whether it needs root, and other remarks.", "Package cache"),
}


def hint(key: str) -> Hint | None:
    return HINTS.get(key)


def term(name: str) -> Term | None:
    for sec in GLOSSARY:
        for t in sec.terms:
            if t.name == name:
                return t
    return None


def search(query: str) -> list[Section]:
    """Sections reduced to the terms whose name or text contains the query."""
    q = query.strip().lower()
    if not q:
        return list(GLOSSARY)
    out = []
    for sec in GLOSSARY:
        hits = tuple(t for t in sec.terms if q in t.name.lower() or q in t.text.lower()
                     or q in t.where.lower())
        if hits:
            out.append(Section(sec.title, hits))
    return out


def changelog_path() -> Path | None:
    """The CHANGELOG.md of this installation: next to the package in a checkout,
    under /usr/share/doc for the package."""
    here = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
    candidates = [here, Path("/usr/share/doc/archpm/CHANGELOG.md"),
                  Path("/usr/local/share/doc/archpm/CHANGELOG.md")]
    for p in candidates:
        if p.is_file():
            return p
    return None


def changelog_text() -> str:
    p = changelog_path()
    if p is None:
        return f"The changelog is not installed. Read it on GitHub: {REPO}/blob/main/CHANGELOG.md"
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Could not read {p}: {exc}"


def about_lines() -> list[tuple[str, str]]:
    return [
        ("Version", __version__),
        ("Source", REPO),
        ("Bugs and ideas", ISSUES),
        ("License", f"{LICENSE}. Copy it, change it, keep it."),
        ("Built with", "Python, PySide6 (Qt), psutil; the widget in QML for KDE Plasma 6."),
        ("Made by", "Alex, with Claude. Details in the README."),
        ("Running from", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ]
