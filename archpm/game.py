"""Which process is "the game", and what belongs to it. No Qt: the Overview
card and the agent's status file both use this."""
from __future__ import annotations

from .model import ProcSample


def game_tree(game: ProcSample, procs: list[ProcSample]) -> list[ProcSample]:
    """Everything that belongs to the game: all processes Steam launched for the
    same app id, or, for a game started some other way, the process and its
    descendants."""
    if game.steam_appid:
        return [p for p in procs if p.steam_appid == game.steam_appid]
    children: dict[int, list[ProcSample]] = {}
    for p in procs:
        children.setdefault(p.ppid, []).append(p)
    out, stack = [], [game]
    while stack:
        p = stack.pop()
        out.append(p)
        stack.extend(children.get(p.pid, []))
    return out


def pick_game(procs: list[ProcSample], current_pid: int = 0) -> ProcSample | None:
    """The game to show: a process Steam launched for a game (it carries an app
    id) that uses the GPU, preferring the one shown last tick so the card does
    not hop between a game and its launcher. Steam's own client is category
    Game too and always holds a little VRAM, so it never qualifies. Outside
    Steam, any program doing real GPU work counts."""
    games = [p for p in procs if p.steam_appid and (p.gpu_sm > 0 or p.gpu_mem_mb > 0)]
    if not games:
        games = [p for p in procs if p.program and not p.steam_appid and p.gpu_sm >= 20]
    if not games:
        return None
    for p in games:
        if p.pid == current_pid:
            return p
    return max(games, key=lambda p: (p.gpu_sm, p.gpu_mem_mb, p.cpu_percent))


def game_summary(game: ProcSample, procs: list[ProcSample], ncpu: int) -> dict:
    """Compact numbers for the status file and the widget."""
    tree = game_tree(game, procs)
    cpu = sum(p.cpu_percent for p in tree)
    return {
        "name": game.display_name,
        "pid": game.pid,
        "procs": len(tree),
        "cpu": round(cpu / ncpu, 1),          # share of the whole machine, %
        "cores": round(cpu / 100, 1),          # cores' worth of work
        "gpu": round(max(p.gpu_sm for p in tree), 1),
        "vram": round(sum(p.gpu_mem_mb for p in tree)),
        "rss": sum(p.mem_rss for p in tree),
        "since": game.create_time,
        "pids": [p.pid for p in tree if p.pid != game.pid] + [game.pid],   # children first
    }
