"""Session 16 の練習問題の解答の検証。api コンテナの中で実行する：

    docker compose exec api python src/session16/verify_practice.py

問題6（ワーカー数の計測）は環境に依存するので、ここでは扱わない（prod_check.py load を手で実行する）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import ValidationError

from kondate.verifykit import check, eq, finish
from src.session16.config import ProdSettings, describe_errors
from src.session16.harness import lab_values, quiet
from src.session16.probes import ReadinessProbe
from src.session16.q1_dockerlint import BAD_DOCKERFILE, RULES, lint_dockerfile
from src.session16.q2_probe_cases import run_cases
from src.session16.q3_settings import Q3Settings
from src.session16.q4_shutdown_plan import longest_stream_seconds, plan_shutdown
from src.session16.q5_worker_cases import stop_outcome
from src.session16.q7_cached_probe import CachedProbe

HERE = Path(__file__).resolve().parent
quiet()


@check("P1 問題1：Dockerfile の点検")
def _():
    eq(lint_dockerfile(BAD_DOCKERFILE), list(RULES), "悪い例")
    eq(lint_dockerfile((HERE / "Dockerfile.prod").read_text(encoding="utf-8")), [], "Dockerfile.prod")
    return f"悪い例は {len(RULES)} 件・Dockerfile.prod は 0 件"


@check("P2 問題2：5つの状況の /health と /ready")
async def _():
    eq(await run_cases(), {
        "すべて正常": (200, 200, "ready"),
        "Redis が応答しない": (200, 503, "not_ready"),
        "mockllm が 5 秒黙る": (200, 503, "not_ready"),
        "drain 中": (200, 503, "draining"),
        "drain 中で Redis も応答しない": (200, 503, "draining"),
    }, "状況ごとの結果")
    return "/health はすべて 200・/ready は正常だけ 200（drain 中は依存先を見ずに draining）"


def q3_errors(**update: str) -> list[str]:
    try:
        Q3Settings(**(lab_values() | update))  # type: ignore[arg-type]
    except ValidationError as exc:
        return describe_errors(exc)
    return []


@check("P3 問題3：CORS_ORIGINS の検証")
def _():
    s = Q3Settings(**(lab_values() | {"cors_origins": " http://localhost:3710, https://kondate.example/ "}))  # type: ignore[arg-type]
    eq(s.cors_origin_list, ["http://localhost:3710", "https://kondate.example"], "正規化")
    eq(q3_errors(cors_origins="*"), ["- CORS_ORIGINS: * は使えません。オリジンを1つずつ書いてください"], "*")
    eq(q3_errors(cors_origins="localhost:3710,https://ok.example"),
       ["- CORS_ORIGINS: 1 件が http(s)://ホスト[:ポート] の形ではありません"], "形違い")
    eq(q3_errors(), ["- CORS_ORIGINS: 必須です（環境変数が設定されていません）"], "未設定")
    return "2 件に正規化・* と形違いと未設定は理由つきで落ちる"


@check("P4 問題4：停止の時間設計")
def _():
    longest = longest_stream_seconds(max_tokens=1024, min_tps=25, ttft_seconds=2.0)
    eq(round(longest, 2), 42.96, "最長のストリーム")
    plan = plan_shutdown(longest)
    eq((plan.drain_grace_seconds, plan.graceful_timeout_seconds, plan.compose_stop_grace()), (43, 48, "53s"), "preStop なし")
    eq(plan_shutdown(longest, pre_stop_seconds=10).compose_stop_grace(), "63s", "preStop 10 秒")
    ProdSettings(**(lab_values() | {k.lower(): v for k, v in plan.as_env().items()}))  # type: ignore[arg-type]
    return "最長 42.96 秒 → DRAIN 43・GRACEFUL 48・stop_grace 53s（preStop 10 秒なら 63s）・ProdSettings も受け付ける"


@check("P5 問題5：worker を止めたときのジョブ")
def _():
    common = {"stop_grace_seconds": 10, "visibility_timeout_seconds": 3600}
    eq(stop_outcome(task_seconds=40, elapsed_at_stop=35, acks_late=True, **common),
       "最後まで実行して ack してから止まる", "残り5秒")
    eq(stop_outcome(task_seconds=120, elapsed_at_stop=10, acks_late=True, **common),
       "SIGKILL で中断し、3600 秒後に再配送される", "acks_late あり")
    eq(stop_outcome(task_seconds=120, elapsed_at_stop=10, acks_late=False, **common),
       "SIGKILL で中断し、開始時に ack 済みなので失われる", "acks_late なし")
    return "完了して ack／3600 秒後に再配送／失われる"


class FakeMonotonic:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


@check("P7 問題7：readiness の結果を短い時間だけ共有する")
async def _():
    calls = 0

    async def counted() -> None:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)  # 確認に時間がかかる間に、ほかの要求が重なるようにする

    clock = FakeMonotonic()
    cached = CachedProbe(ReadinessProbe({"postgres": counted}, timeout=1.0), ttl_seconds=1.0, now=clock)
    results = await asyncio.gather(*(cached.run() for _ in range(10)))
    eq((calls, results[0], len({str(r) for r in results})), (1, {"postgres": "ok"}, 1), "同時 10 件")
    clock.t += 0.5
    await cached.run()
    eq(calls, 1, "0.5 秒後")
    clock.t += 1.0
    await cached.run()
    eq(calls, 2, "1.5 秒後")
    return "同時 10 件で確認は 1 回・0.5 秒後も 1 回・1.5 秒後に 2 回目"


finish("session16-practice")
