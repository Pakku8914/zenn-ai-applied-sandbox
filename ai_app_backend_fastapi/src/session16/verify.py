"""Session 16 の検証。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session16

ここでは、api コンテナの中で決定的に確かめられることだけを調べる（Dockerfile と依存の一覧・設定の検証・
liveness と readiness・drain・本物の uvicorn での SIGTERM・Celery の設定名）。
本番イメージのビルドと起動、ワーカー数と同時接続数の計測は prod_check.py を手で実行する（値が環境に依存するため）。
"""

from __future__ import annotations

import asyncio
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx2
import uvicorn

from kondate.settings import get_settings
from kondate.verifykit import check, eq, finish
from src.session16.app import create_app
from src.session16.harness import (PROMPT, assert_error, lab_settings, quiet, running, shape, stream_chat,
                                   wait_until)
from src.session16.worker_shutdown import (GRACE_TOO_SHORT, SOFT_SHUTDOWN_SETTINGS, VISIBILITY_TOO_SHORT,
                                           WORKER_SHUTDOWN_CONF, shutdown_problems)

BASE = get_settings()
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # sandbox/ の直下（コンテナの /app）
PORT = 18716
DEV_ONLY = {"iniconfig", "pluggy", "pygments", "pytest", "pytest-asyncio"}
logs = quiet()


def pins(path: Path) -> dict[str, str]:
    """requirements の「名前==版」を {正規化した名前: 版} にする。== で固定されていない行があれば落とす。"""
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^=\s]+)", line)
        assert m, f"== で固定されていない行: {line}"
        out[re.sub(r"[-_.]+", "-", m.group(1)).lower()] = m.group(2)
    return out


@check("V1 Dockerfile.prod：2段・タグ固定・非 root・--reload なし・HEALTHCHECK・exec 形式、依存は開発用と同じ固定版")
def _():
    text = (HERE / "Dockerfile.prod").read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    eq(re.findall(r"^FROM\s+(\S+)", code, re.M), ["python:3.12.14-slim", "python:3.12.14-slim"], "FROM")
    assert re.search(r"^USER 10001$", code, re.M), "USER 10001 が無い"
    assert "--reload" not in code, "--reload が残っている"
    assert re.search(r"^HEALTHCHECK ", code, re.M), "HEALTHCHECK が無い"
    cmds = re.findall(r"^CMD\s+(.*)$", code, re.M)
    assert cmds and cmds[-1].startswith("["), f"CMD が exec 形式ではない: {cmds}"
    assert "pip install --no-deps" in code and "pip check" in code, "--no-deps と pip check が無い"
    dev, prod = pins(ROOT / "requirements.txt"), pins(HERE / "requirements-prod.txt")
    eq({k: dev.get(k) for k in prod}, prod, "本番の版が開発用と同じ")
    eq(set(dev) - set(prod), DEV_ONLY, "本番から除いたもの")
    return (f"FROM python:3.12.14-slim ×2・USER 10001・CMD は exec 形式・依存 {len(prod)} 件"
            f"（開発用 {len(dev)} 件から pytest など {len(DEV_ONLY)} 件を除く）")


VALID = {"DATABASE_URL": BASE.database_url, "REDIS_URL": BASE.redis_url, "ANTHROPIC_API_KEY": "mock-key",
         "ANTHROPIC_BASE_URL": BASE.mockllm_url, "LLM_MODEL": BASE.llm_model}
MISSING = "必須です（環境変数が設定されていません）"


def settings_check(env: dict[str, str]) -> tuple[int, list[str]]:
    """環境変数をこれだけにして python -m src.session16.serve --check を別プロセスで流す。"""
    base = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"}
    p = subprocess.run([sys.executable, "-m", "src.session16.serve", "--check"], env=base | env, cwd=ROOT,
                       capture_output=True, encoding="utf-8", timeout=60)
    return p.returncode, (p.stdout + p.stderr).splitlines()


@check("V2 設定の検証：足りない・形が違う・組み合わせが合わないと exit 1 で理由を並べ、値は表示しない")
def _():
    env = {k: v for k, v in VALID.items() if k not in ("DATABASE_URL", "ANTHROPIC_API_KEY")} | {"WEB_WORKERS": "0"}
    eq(settings_check(env), (1, ["設定エラー：起動を中止します（3 件）", f"- DATABASE_URL: {MISSING}",
                                 f"- ANTHROPIC_API_KEY: {MISSING}", "- WEB_WORKERS: 1 以上にしてください"]),
       "必須2件と範囲外")
    secret_db = "postgresql://kondate:s3cr3t-db-pass@postgres:5432/kondate"
    code, lines = settings_check(VALID | {"DATABASE_URL": secret_db, "ANTHROPIC_API_KEY": "sk-ant-verify-0123456789abcdef"})
    eq((code, lines), (1, ["設定エラー：起動を中止します（1 件）",
                           "- DATABASE_URL: postgresql+asyncpg:// で始めてください（asyncpg で接続するため）"]), "形が違う")
    joined = "\n".join(lines)
    assert "s3cr3t" not in joined and "verify-0123" not in joined, "値が表示されている"
    eq(settings_check(VALID | {"DRAIN_GRACE_SECONDS": "30", "GRACEFUL_TIMEOUT_SECONDS": "25"}),
       (1, ["設定エラー：起動を中止します（1 件）",
            "- 設定の組み合わせ: DRAIN_GRACE_SECONDS（30 秒）は GRACEFUL_TIMEOUT_SECONDS（25 秒）より短くしてください"]),
       "組み合わせ")
    eq(settings_check(VALID), (0, ["設定 OK：WEB_WORKERS=2 GRACEFUL_TIMEOUT_SECONDS=25 DRAIN_GRACE_SECONDS=20 "
                                   "MAX_STREAMS_PER_WORKER=100"]), "そろっている")
    return "必須2件＋範囲外1件／asyncpg でない URL（パスワードは出ない）／DRAIN ≥ GRACEFUL → exit 1・そろえば exit 0"


async def broken() -> None:
    raise ConnectionError("redis://:p4ss@redis:6379 に接続できません")


async def silent() -> None:
    await asyncio.sleep(5)


@check("V3 liveness と readiness：依存先がそろえば /ready は 200、1つでも落ちれば 503（/health は 200 のまま）")
async def _():
    app = create_app(lab_settings(), configure_logging=False)
    async with running(app) as c:
        h1, r1 = await c.get("/health"), await c.get("/ready")
        app.state.probe.checks["redis"] = broken
        app.state.probe.checks["mockllm"] = silent
        h2, r2 = await c.get("/health"), await c.get("/ready")
    eq((h1.status_code, h1.json()), (200, {"status": "ok"}), "/health（正常）")
    eq((r1.status_code, r1.json()),
       (200, {"status": "ready", "checks": {"postgres": "ok", "redis": "ok", "mockllm": "ok"}}), "/ready（正常）")
    eq((h2.status_code, h2.json()), (200, {"status": "ok"}), "/health（依存先が落ちても）")
    eq((r2.status_code, r2.json()),
       (503, {"status": "not_ready", "checks": {"postgres": "ok", "redis": "ng", "mockllm": "timeout"}}),
       "/ready（redis が落ち・mockllm が黙る）")
    assert "p4ss" not in r2.text, "例外の文が本文に出ている"
    return "postgres・redis・mockllm が ok → 200 ready／redis=ng・mockllm=timeout → 503 not_ready／/health はどちらも 200"


@check("V4 drain：/ready は 503、新しいストリームは始める前に 503、配信中のストリームは done まで届く")
async def _():
    app = create_app(lab_settings(drain_grace_seconds=10, graceful_timeout_seconds=15), configure_logging=False)
    async with running(app) as c:
        inflight = asyncio.create_task(stream_chat(c, tps=100))  # 約2秒かかるストリーム
        await wait_until(lambda: app.state.gate.active == 1, 5, "ストリームが始まらない")
        app.state.drain.begin()
        h, r = await c.get("/health"), await c.get("/ready")
        new = await c.post("/api/chat/stream", json={"message": PROMPT})
        run = await inflight
    eq(h.status_code, 200, "/health")
    eq((r.status_code, r.json()), (503, {"status": "draining", "checks": {}}), "/ready")
    assert_error(new, 503, "service_unavailable")
    eq(new.headers.get("retry-after"), "1", "retry-after")
    eq(shape(run.names), "start → delta×32 → usage → done", "配信中のストリーム")
    return ("/health 200・/ready 503 draining・新規 503 service_unavailable（retry-after: 1）・"
            "配信中は start → delta×32 → usage → done")


@check("V5 drain の締め切り：上流が続いていても error（service_unavailable）で閉じ、上流も閉じる")
async def _():
    app = create_app(lab_settings(drain_grace_seconds=1, graceful_timeout_seconds=5), configure_logging=False)
    async with running(app) as c:
        task = asyncio.create_task(stream_chat(c, tps=20))  # 約9秒かかるストリーム
        await wait_until(lambda: app.state.gate.active == 1, 5, "ストリームが始まらない")
        started = time.perf_counter()
        app.state.drain.begin()
        run = await task
        elapsed = time.perf_counter() - started
    eq((run.names[0], run.names[-1]), ("start", "error"), "最初と最後")
    assert "done" not in run.names and "usage" not in run.names, run.names
    eq(run.events[-1]["data"]["type"], "service_unavailable", "error.type")
    assert 0.9 <= elapsed < 3.0, f"締め切りから閉じるまで {elapsed:.2f} 秒"
    outcome = app.state.outcomes[-1]
    eq((outcome.reason, outcome.upstream_closed), ("drained", True), "結末")
    eq(app.state.gate.active, 0, "同時ストリーム数")
    return "start → delta… → error・締め切り（1 秒）で閉じる・reason=drained・上流を閉じた・同時ストリーム数は 0 に戻る"


@check("V6 本物の uvicorn に SIGTERM：短いストリームは done、長いストリームは締め切りで error、新しい接続は断られる")
async def _():
    # uvicorn は止まり終えたあと、受けたシグナルを投げ直す。検証のプロセスまで止まらないよう、先に受け皿を置く
    signal.signal(signal.SIGTERM, lambda *_: None)
    try:
        app = create_app(lab_settings(drain_grace_seconds=2, graceful_timeout_seconds=4), configure_logging=False)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning",
                                               timeout_graceful_shutdown=4))
        serving = asyncio.create_task(server.serve())
        await wait_until(lambda: server.started or serving.done(), 10, "uvicorn が起動しない")
        base = f"http://127.0.0.1:{PORT}"
        async with httpx2.AsyncClient(base_url=base, timeout=30) as c:
            short = asyncio.create_task(stream_chat(c, tps=200))  # 約1秒
            long = asyncio.create_task(stream_chat(c, tps=20))  # 約9秒
            await wait_until(lambda: app.state.gate.active == 2, 5, "2本のストリームが始まらない")
            os.kill(os.getpid(), signal.SIGTERM)  # docker stop と同じ信号を、自分のプロセスに送る
            await wait_until(lambda: app.state.drain.started, 2, "drain が始まらない（シグナルを横取りできていない）")
            await asyncio.sleep(0.5)
            try:
                async with httpx2.AsyncClient(base_url=base, timeout=2) as fresh:
                    await fresh.get("/health")
                refused = "応答した"
            except httpx2.ConnectError:
                refused = "ConnectError"
            s, lg = await short, await long
        await asyncio.wait_for(serving, 10)
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
    eq(refused, "ConnectError", "止まり始めた後の新しい接続")
    eq(shape(s.names), "start → delta×32 → usage → done", "短いストリーム")
    eq((lg.names[0], lg.names[-1], lg.events[-1]["data"]["type"]), ("start", "error", "service_unavailable"),
       "長いストリーム")
    eq(server.should_exit, True, "uvicorn が止まった")
    return ("SIGTERM で drain 開始・新しい接続は ConnectError・短い方 start → delta×32 → usage → done・"
            "長い方 start → delta… → error（service_unavailable）・uvicorn は猶予内に終了")


@check("V7 Celery：止め方に関わる設定名が Celery 5.6.3 に実在し、停止の時間の関係を検査できる")
def _():
    from celery.app.defaults import DEFAULTS

    names = [*WORKER_SHUTDOWN_CONF, *SOFT_SHUTDOWN_SETTINGS]
    eq([n for n in names if n not in DEFAULTS], [], "Celery に無い設定名")
    eq(shutdown_problems(longest_task_seconds=60, stop_grace_seconds=90, visibility_timeout_seconds=3600), [],
       "余裕のある組")
    eq(shutdown_problems(longest_task_seconds=60, stop_grace_seconds=10, visibility_timeout_seconds=100),
       [GRACE_TOO_SHORT, VISIBILITY_TOO_SHORT], "足りない組")
    return f"設定名 {len(names)} 件は実在・最長 60 秒に grace 90／visibility 3600 は問題なし・grace 10／visibility 100 は 2 件"


finish("session16")
