#!/usr/bin/env python3
"""問題8の参照解答：タイムアウトと孤児プロセス（セッション9）。

打ち切りは「殺す」だけでは終わらない。殺した相手が子を作っていたら、その子は残る。
残った子（孤児プロセス）は、誰にも見られないまま CPU を使い、
作業領域にファイルを書き、次の実行の邪魔をする。

  A: 直接の子だけを殺す（`Popen.kill`）        → 孫が生き残る
  B: プロセスグループごと殺す（`os.killpg`）   → 孫も止まる

    python src/session09/ex_orphan.py
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentkit.sandbox import run_python  # noqa: E402

ORPHAN_DIR = ROOT / "workspace" / "session09" / "orphan"
ORPHAN_RUNNER = "/work/session09/orphan"

GRANDCHILD_SLEEP = 1.5   # 孫が目印を書くまでの待ち時間（秒）
PARENT_TIMEOUT = 0.8     # 親を打ち切るまでの時間（秒）
WATCH_AFTER = 2.2        # 打ち切ってから目印を見に行くまでの待ち時間（秒）


def _child_code(marker: Path) -> str:
    """孫プロセスを1つ作ってから寝る子のコード。"""
    grand = (f"import pathlib, time\n"
             f"time.sleep({GRANDCHILD_SLEEP})\n"
             f"pathlib.Path({str(marker)!r}).write_text('alive', encoding='utf-8')\n")
    return ("import subprocess, sys, time\n"
            f"subprocess.Popen([sys.executable, '-c', {grand!r}])\n"
            "time.sleep(30)\n")


def supervised_run(code: str, *, timeout: float, kill_group: bool) -> dict:
    """打ち切りつきでコードを実行する。kill_group=True でプロセスグループごと殺す。"""
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        # 新しいセッションを開くと、この子を長とするプロセスグループができる
        start_new_session=kill_group,
    )
    try:
        proc.communicate(timeout=timeout)
        return {"timed_out": False, "returncode": proc.returncode}
    except subprocess.TimeoutExpired:
        if kill_group:
            try:
                # start_new_session=True なので pgid == 子の pid
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            proc.kill()
        try:
            # 孫がパイプを握っていると、ここで待たされることがある
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        return {"timed_out": True, "returncode": proc.returncode}


def orphan_demo(kill_group: bool) -> dict:
    """孫が生き残るかどうかを目印ファイルで観測する。"""
    ORPHAN_DIR.mkdir(parents=True, exist_ok=True)
    marker = ORPHAN_DIR / ("group.txt" if kill_group else "single.txt")
    marker.unlink(missing_ok=True)
    result = supervised_run(_child_code(marker), timeout=PARENT_TIMEOUT,
                            kill_group=kill_group)
    time.sleep(WATCH_AFTER)
    alive = marker.exists()
    marker.unlink(missing_ok=True)
    return {"殺し方": "プロセスグループごと" if kill_group else "直接の子だけ",
            "打ち切った": result["timed_out"],
            "孫が生き残った": alive}


# --- 同梱のワーカーはどちらか -----------------------------------------------
RUNNER_GRANDCHILD_SLEEP = 3.0
RUNNER_WATCH_AFTER = 2.5


def runner_orphan_demo() -> dict:
    """`tool-runner` の worker は直接の子だけを殺す。孫が残ることを確かめる。"""
    ORPHAN_DIR.mkdir(parents=True, exist_ok=True)
    marker = ORPHAN_DIR / "runner.txt"
    marker.unlink(missing_ok=True)
    target = f"{ORPHAN_RUNNER}/runner.txt"
    grand = (f"import pathlib, time\n"
             f"time.sleep({RUNNER_GRANDCHILD_SLEEP})\n"
             f"pathlib.Path({target!r}).write_text('alive', encoding='utf-8')\n")
    code = ("import os, subprocess, sys, time\n"
            f"os.makedirs({ORPHAN_RUNNER!r}, exist_ok=True)\n"
            f"subprocess.Popen([sys.executable, '-c', {grand!r}])\n"
            "time.sleep(30)\n")
    started = time.perf_counter()
    res = run_python(code, timeout=2.0)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    time.sleep(RUNNER_WATCH_AFTER)
    alive = marker.exists()
    marker.unlink(missing_ok=True)
    return {"打ち切った": not res.ok,
            "孫が生き残った": alive,
            "打ち切りに掛かった時間(ms)": elapsed_ms}


def render() -> str:
    lines = ["=== 打ち切り方の違い（app コンテナで実験）===",
             "殺し方 | 打ち切った | 孫が生き残った"]
    for kill_group in (False, True):
        row = orphan_demo(kill_group)
        lines.append(f"{row['殺し方']} | {row['打ち切った']} | {row['孫が生き残った']}")
    runner = runner_orphan_demo()
    lines += ["",
              "=== 同梱の worker（subprocess.run の timeout）===",
              f"打ち切った: {runner['打ち切った']} / "
              f"孫が生き残った: {runner['孫が生き残った']} / "
              f"打ち切りに掛かった時間: {runner['打ち切りに掛かった時間(ms)']} ms",
              "（2 秒で打ち切ったのに時間が伸びるのは、孫が標準出力のパイプを握っているため）"]
    shutil.rmtree(ORPHAN_DIR, ignore_errors=True)
    return "\n".join(lines)


def main() -> None:
    print(render())


if __name__ == "__main__":
    main()
