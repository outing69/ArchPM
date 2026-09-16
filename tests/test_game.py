"""Tests for archpm.game: which process counts as the game and what belongs to it."""
from __future__ import annotations

import unittest

from archpm.game import game_summary, game_tree, pick_game
from archpm.model import ProcSample


def P(pid, name, ppid=1, appid=0, gpu_sm=0.0, gpu_mem=0.0, cpu=0.0, program=False, cat=""):
    return ProcSample(pid=pid, ppid=ppid, name=name, cmdline=name, steam_appid=appid,
                      gpu_sm=gpu_sm, gpu_mem_mb=gpu_mem, cpu_percent=cpu, program=program,
                      category=cat, app_name=name if program else "", mem_rss=100 << 20,
                      num_threads=4)


class Pick(unittest.TestCase):
    def test_steam_client_never_counts(self):
        procs = [P(1, "steam", appid=0, gpu_mem=117, program=True, cat="Game")]
        self.assertIsNone(pick_game(procs))

    def test_prefers_the_process_shown_last_tick(self):
        procs = [P(10, "reaper", appid=5, gpu_mem=1), P(11, "Game.exe", appid=5, gpu_sm=80)]
        self.assertEqual(pick_game(procs).pid, 11, "highest GPU by default")
        self.assertEqual(pick_game(procs, current_pid=10).pid, 10, "sticky once shown")

    def test_non_steam_program_needs_real_gpu_work(self):
        self.assertIsNone(pick_game([P(3, "kwin", gpu_sm=5, gpu_mem=60, program=False)]))
        self.assertIsNone(pick_game([P(4, "brave", gpu_sm=10, program=True)]))
        self.assertEqual(pick_game([P(5, "heroic-game", gpu_sm=40, program=True)]).pid, 5)


class Tree(unittest.TestCase):
    def test_by_app_id_or_by_descent(self):
        procs = [P(1, "systemd"), P(2, "steam"), P(3, "reaper", ppid=2, appid=9),
                 P(4, "wineserver", ppid=3, appid=9), P(5, "Game.exe", ppid=3, appid=9),
                 P(6, "other", ppid=1), P(7, "native", ppid=1), P(8, "child", ppid=7)]
        self.assertEqual({p.pid for p in game_tree(procs[4], procs)}, {3, 4, 5})
        self.assertEqual({p.pid for p in game_tree(procs[6], procs)}, {7, 8})

    def test_summary_numbers(self):
        procs = [P(3, "reaper", appid=9, cpu=10), P(5, "Game.exe", appid=9, gpu_sm=80,
                 gpu_mem=4000, cpu=150)]
        s = game_summary(procs[1], procs, ncpu=16)
        self.assertEqual((s["procs"], s["gpu"], s["vram"]), (2, 80.0, 4000))
        self.assertEqual(s["cpu"], 10.0)      # 160% of one core = 10% of 16
        self.assertEqual(s["cores"], 1.6)
        self.assertEqual(s["rss"], 200 << 20)
        self.assertNotIn("pids", s, "the widget never signals; the window computes its own tree")


if __name__ == "__main__":
    unittest.main()
