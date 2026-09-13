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
        Term("Swap and zram",
             "When RAM is full, the kernel moves the least-used parts to swap. On CachyOS "
             "swap usually lives in zram: compressed RAM, much faster than a disk. Some swap "
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
             "processes, raising nice, affinity. Lowering nice, other users' processes, "
             "services and the two cleanup items need it.",
             "Root tasks button"),
        Term("pkexec and polkit",
             "The standard way a desktop program asks for admin rights: polkit shows the "
             "password dialog, pkexec runs one small helper as root. ArchPM's helper is a "
             "single file that accepts only fixed commands and refuses anything that could "
             "break your session. It is described in SECURITY.md.",
             "Password dialog"),
        Term("Protected services",
             "Services ArchPM refuses to stop even as root, because your session depends on "
             "them: dbus, logind, polkit, the display manager and their sockets.",
             "Root tasks → services"),
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
