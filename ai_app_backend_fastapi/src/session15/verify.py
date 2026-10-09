"""Session 15（テスト戦略）の動作確認。api コンテナの中で実行する：

    docker compose exec api python src/session15/verify.py

pytest は別プロセスで動かし、終了コードと件数（passed・skipped など）を検査する。
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from kondate.verifykit import check, eq, finish
from src.session15.cassette import event_from_json, load_cassette
from src.session15.record import CASSETTE_DIR, record_all

ROOT = Path(__file__).resolve().parents[2]
TESTS = "src/session15/tests"
LAYER_FILES = [f"{TESTS}/test_unit_fake.py", f"{TESTS}/test_replay.py", f"{TESTS}/test_sse.py"]


def pytest_run(*args: str, env: dict[str, str] | None = None) -> tuple[int, str]:
    run_env = {k: v for k, v in os.environ.items() if k != "RUN_LIVE"}  # 実 API の確認は動かさない
    run_env.update(env or {})
    r = subprocess.run([sys.executable, "-m", "pytest", *args, "-p", "no:cacheprovider"],
                       cwd=ROOT, capture_output=True, text=True, env=run_env)
    return r.returncode, r.stdout + r.stderr


def counts(output: str) -> dict[str, int]:
    """最後の要約行（例：24 passed, 1 skipped in 3.21s）から件数を取り出す。"""
    summary = [line for line in output.splitlines() if re.search(r"\b(passed|skipped|deselected|failed)\b", line)]
    assert summary, output[-3000:]
    return {k: int(n) for n, k in re.findall(r"(\d+) (passed|skipped|deselected|failed|errors?)", summary[-1])}


def shape(events: list[dict]) -> str:
    runs: list[list] = []
    for d in events:
        item = event_from_json(d)
        name = type(item).__name__
        name = f"{name}({item.kind})" if name == "ProviderError" else name
        if runs and runs[-1][0] == name:
            runs[-1][1] += 1
        else:
            runs.append([name, 1])
    return " → ".join(k if n == 1 else f"{k}×{n}" for k, n in runs)


@check("V1 録画：mockllm から2本のカセットを録る。2回録っても同じバイト列になる（決定的）")
def _():
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        first = asyncio.run(record_all(Path(a)))
        second = asyncio.run(record_all(Path(b)))
        eq([p.read_bytes() for p in first], [p.read_bytes() for p in second], "2回の録画のバイト列")
    paths = asyncio.run(record_all(CASSETTE_DIR))
    got = {}
    for path in paths:
        [entry] = load_cassette(path)  # どちらも上流への呼び出しは1回
        got[path.stem] = shape(entry["events"])
    eq(got, {"chat_ok": "TextDelta×32 → Done",
             "chat_sse_error": "TextDelta×2 → ProviderError(stream_error)"}, "カセットの中身")
    ok = event_from_json(load_cassette(CASSETTE_DIR / "chat_ok.jsonl")[0]["events"][-1])
    eq((ok.stop_reason, ok.usage.input_tokens, ok.usage.output_tokens), ("end_turn", 34, 181), "chat_ok の Done")
    return ("chat_ok：TextDelta×32 → Done（end_turn・34／181）・chat_sse_error：TextDelta×2 → "
            "ProviderError(stream_error)・2回録っても同じバイト列")


@check("V2 テストの層：ファイルごとの件数（単体・再生・SSE は外部に触れない／結合は mockllm と DB・Redis／live は任意）")
def _():
    code, out = pytest_run(TESTS, "--collect-only")
    eq(code, 0, f"収集の終了コード\n{out[-3000:]}")
    per_file = Counter(line.split("::")[0].rsplit("/", 1)[-1] for line in out.splitlines() if "::" in line)
    expected = {"test_unit_fake.py": 6, "test_replay.py": 5, "test_sse.py": 4,
                "test_faults.py": 7, "test_isolation.py": 2, "test_live.py": 1}
    eq(dict(per_file), expected, "ファイルごとの件数")
    return "・".join(f"{k.removesuffix('.py')} {v}" for k, v in expected.items()) + f"（計 {sum(expected.values())}）"


@check("V3 pytest src/session15/tests：課金なしで完走する（live は skip）")
def _():
    code, out = pytest_run(TESTS)
    eq(code, 0, f"pytest の終了コード\n{out[-4000:]}")
    eq(counts(out), {"passed": 24, "skipped": 1}, "件数")
    return "24 passed, 1 skipped"


@check("V4 単体・再生・SSE の層は、mockllm・PostgreSQL・Redis に届かなくても通る")
def _():
    dead = {"MOCKLLM_URL": "http://127.0.0.1:9", "DATABASE_URL": "postgresql+asyncpg://x:x@127.0.0.1:9/x",
            "REDIS_URL": "redis://127.0.0.1:9/0"}
    code, out = pytest_run(*LAYER_FILES, env=dead)
    eq(code, 0, f"pytest の終了コード\n{out[-4000:]}")
    eq(counts(out), {"passed": 15}, "件数")
    return "接続先を存在しないポートにしても 15 passed"


@check("V5 -m live：実 API の確認は既定で skip され、ほかのテストは選ばれない")
def _():
    code, out = pytest_run(TESTS, "-m", "live")
    eq(code, 0, f"pytest の終了コード\n{out[-3000:]}")
    eq(counts(out), {"skipped": 1, "deselected": 24}, "件数")
    return "1 skipped, 24 deselected（RUN_LIVE が無いので課金されない）"


finish("session15")
