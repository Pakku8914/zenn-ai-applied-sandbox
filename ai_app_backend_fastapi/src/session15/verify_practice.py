"""Session 15 の練習問題の検証。api コンテナの中で実行する：

    docker compose exec api python src/session15/verify_practice.py
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from kondate.verifykit import check, eq, finish

ROOT = Path(__file__).resolve().parents[2]
PRACTICE = "src/session15/practice"


def pytest_run(*args: str) -> tuple[int, str]:
    env = {k: v for k, v in os.environ.items() if k != "RUN_LIVE"}
    r = subprocess.run([sys.executable, "-m", "pytest", *args, "-p", "no:cacheprovider"],
                       cwd=ROOT, capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr


# 問題の順に並べる（前半の問題1はコードを書かない問題なので、テストのファイルが無い）
FIRST_HALF = {"test_q2_unit.py": 2, "test_cassette_summary.py": 2, "test_failing_store.py": 1,
              "test_q5_complete.py": 2, "test_cassette_mode.py": 2}
SECOND_HALF = {"test_q3_contract.py": 3, "test_prestart_json.py": 2, "test_usage_fixture.py": 2,
               "test_q4_faults.py": 3, "test_hidden_retries.py": 1, "test_q6_loop_scope.py": 2}


def label(files: dict[str, int]) -> str:
    return "・".join(f"{k.removeprefix('test_').removesuffix('.py')} {v}" for k, v in files.items())


@check("P1 解答のテストの件数（前半：問題2〜6／後半：問題1〜6）")
def _():
    code, out = pytest_run(PRACTICE, "--collect-only")
    eq(code, 0, f"収集の終了コード\n{out[-3000:]}")
    per_file = Counter(line.split("::")[0].rsplit("/", 1)[-1] for line in out.splitlines() if "::" in line)
    eq(dict(per_file), {**FIRST_HALF, **SECOND_HALF}, "ファイルごとの件数")
    return f"前半 {label(FIRST_HALF)}／後半 {label(SECOND_HALF)}"


@check("P2 pytest src/session15/practice がすべて通る")
def _():
    code, out = pytest_run(PRACTICE)
    eq(code, 0, f"pytest の終了コード\n{out[-4000:]}")
    lines = [line for line in out.splitlines() if re.search(r"\b(passed|failed)\b", line)]
    total = sum(FIRST_HALF.values()) + sum(SECOND_HALF.values())
    eq(re.findall(r"(\d+) (passed|skipped|failed|errors?)", lines[-1]), [(str(total), "passed")], "件数")
    return f"{total} passed（前半 {sum(FIRST_HALF.values())}・後半 {sum(SECOND_HALF.values())}）"


finish("session15-practice")
