"""The one line at the top of the Overview: is anything straining the
machine, and which program. And the game card's own line: is the game
using the graphics card fully, which for a game is the good outcome.

Computed from the sample already taken, no Qt, every rule testable.

Thresholds and why:

MEM_FULL_PCT 85   RAM in use, cache not counted. Above this the kernel starts
                  reclaiming and swapping, and the desktop stalls; below it
                  free memory is just cache waiting to be used.
PROGRAM_SHARE 25  One program's share of the whole processor, all cores. A
                  quarter of the machine slows everything else down; one core
                  out of sixteen (6 percent) is a compile or a page loading
                  and is not worth a line.
MACHINE_BUSY 85   The whole processor, when no single program reaches the
                  share above: many small things add up.
HOT_C 90          The processor or the graphics card. AMD throttles at 95 and
                  NVIDIA slows down from about 85; 60 to 80 under load is by
                  design and the Help says so.
SUSTAIN 3         Consecutive samples (six seconds at the default interval)
                  before a strain is named. A single tick spikes for a page
                  load or a compile step; three in a row is a state.

For a game, its own rule (GAME_GPU_FULL 85, GAME_CPU_LIMIT 90): the graphics
card fully used is the outcome a gamer wants, so it is green; the processor
near a whole core while the card idles is the processor limiting the game;
neither busy is a menu, a loading screen, a frame cap or waiting for the
network; and hot is red, as everywhere.
"""
from __future__ import annotations

from dataclasses import dataclass

from .game import pick_game
from .model import ProcSample, SystemSample
from .units import gigabytes

MEM_FULL_PCT = 85.0
PROGRAM_SHARE = 25.0
MACHINE_BUSY = 85.0
HOT_C = 90.0
WARM_C = 80.0     # the temperature tiles: "normal" under this, "warm" to HOT_C, then "hot"
SUSTAIN = 3
GAME_GPU_FULL = 85.0
# The load scale of the tiles, the core strip, the CPU column and the widget:
# green under the first, orange from there, red from the second. Used by the
# theme's heat() and named in the Help; one place for both.
LOAD_WARN_PCT = 60.0
LOAD_HOT_PCT = 85.0
GAME_GPU_IDLE = 50.0
GAME_CPU_LIMIT = 90.0      # percent of one core, the game's whole tree

CALM = "Nothing is straining the machine."


@dataclass
class Verdict:
    text: str = CALM
    level: str = "calm"      # calm | game | strain | hot
    pid: int = 0             # the program to show, 0 when there is none
    program: str = ""


def _by_program(procs: list[ProcSample]) -> dict[str, list[ProcSample]]:
    out: dict[str, list[ProcSample]] = {}
    for p in procs:
        if p.pid > 0:
            out.setdefault(p.display_name, []).append(p)
    return out


def candidate(system: SystemSample, procs: list[ProcSample], ncpu: int) -> Verdict:
    """The verdict this one sample would give, before any sustain."""
    ncpu = max(ncpu, 1)
    hot = []
    if system.cpu_temp_c >= HOT_C:
        hot.append(("The processor", system.cpu_temp_c))
    if system.gpu is not None and system.gpu.temp_c >= HOT_C:
        hot.append(("The graphics card", system.gpu.temp_c))
    if hot:
        part, temp = hot[0]
        return Verdict(f"{part} is running hot: {temp:.0f}°.", "hot")

    groups = _by_program(procs)
    if system.mem_pct >= MEM_FULL_PCT and groups:
        name, members = max(groups.items(), key=lambda kv: sum(p.mem_rss for p in kv[1]))
        held = sum(p.mem_rss for p in members)
        lead = max(members, key=lambda p: p.mem_rss)
        return Verdict(f"Memory is nearly full: {name} holds {gigabytes(held)}.", "strain",
                       lead.pid, name)

    if groups:
        name, members = max(groups.items(), key=lambda kv: sum(p.cpu_percent for p in kv[1]))
        share = sum(p.cpu_percent for p in members) / ncpu
        lead = max(members, key=lambda p: p.cpu_percent)
        game = pick_game(procs)
        if share >= PROGRAM_SHARE:
            if game is not None and game.display_name == name:
                return Verdict(f"{name} is using {share:.0f}% of the processor: that is the "
                               "game.", "game", lead.pid, name)
            return Verdict(f"{name} is using {share:.0f}% of the processor.", "strain",
                           lead.pid, name)
        if system.cpu_percent >= MACHINE_BUSY:
            return Verdict(f"The processor is fully busy; the biggest user is {name} "
                           f"({share:.0f}%).", "strain", lead.pid, name)
    return Verdict()


class StrainWatch:
    """Names a strain only when it holds for SUSTAIN samples in a row; calm
    and hot show at once."""

    def __init__(self) -> None:
        self._last: Verdict = Verdict()
        self._streak = 0
        self.verdict = Verdict()

    def update(self, system: SystemSample, procs: list[ProcSample], ncpu: int) -> Verdict:
        now = candidate(system, procs, ncpu)
        if now.level in ("calm", "hot"):
            self._streak = 0
            self.verdict = now
            self._last = now
            return self.verdict
        if self.verdict.level == "hot":
            # Hot is this sample's reading and no longer holds: the line is
            # calm until the strain now building has held for SUSTAIN samples.
            # (Through 0.2.53 the hot line stayed up for those samples.)
            self.verdict = Verdict()
        if now.level == self._last.level and now.program == self._last.program:
            self._streak += 1
            if self._streak >= SUSTAIN:
                self.verdict = now
            elif self.verdict.level in ("strain", "game"):
                self.verdict = now     # already named: keep the numbers fresh
        else:
            self._streak = 1
            if self.verdict.level in ("strain", "game"):
                self.verdict = Verdict()   # the old strain is over; the new one must hold
        self._last = now
        return self.verdict


def game_verdict(cpu_tree: float, gpu: float, cpu_temp: float, gpu_temp: float) -> tuple[str, str]:
    """(text, colour token) for a running game. Its own rule: the card fully
    used is green, the processor as the limit orange, idle muted, hot red."""
    if gpu_temp >= HOT_C or cpu_temp >= HOT_C:
        part, temp = (("The graphics card", gpu_temp) if gpu_temp >= HOT_C
                      else ("The processor", cpu_temp))
        return f"Running hot: {part.lower()} is at {temp:.0f}°.", "CRIT"
    if gpu >= GAME_GPU_FULL:
        return "The graphics card is fully used: the game is the limit, as it should be.", "OK"
    if gpu < GAME_GPU_IDLE and cpu_tree >= GAME_CPU_LIMIT:
        return "The processor is the limit: the graphics card is waiting for it.", "WARN"
    if gpu < GAME_GPU_IDLE:
        return ("Neither is busy: a menu, a loading screen, a frame cap or waiting for the "
                "network.", "MUTED")
    return "The graphics card is working, with room to spare.", "TEXT"


def gpu_caption(gpu: float) -> str:
    if gpu >= GAME_GPU_FULL:
        return "fully used"
    if gpu < GAME_GPU_IDLE:
        return "mostly idle"
    return "room to spare"


def temp_level(temp_c: float) -> tuple[str, str]:
    """(word, colour token) for a temperature tile: the reference a user
    needs to judge the number, on the tile and not only in a tooltip.
    60 to 80 under load is by design, so it is "normal" and not orange."""
    if temp_c >= HOT_C:
        return "hot", "CRIT"
    if temp_c >= WARM_C:
        return "warm", "WARN"
    return "normal", "OK"
