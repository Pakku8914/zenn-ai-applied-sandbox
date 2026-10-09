"""本番イメージの確認と計測（verify-all.sh には含めない。環境に依存する値を出すので、手で実行する）。

準備（本番イメージを作って起動する）：
    docker compose --profile prod up -d --build --wait api-prod

1) image：イメージの中身を確かめる（api-prod の中で実行する）
    docker compose --profile prod exec api-prod python -m src.session16.prod_check image
2) load：同時ストリーム数とワーカー数の関係を測る（api の中から api-prod へ投げる）
    docker compose exec api python -m src.session16.prod_check load --concurrency 150
3) stop：止め方を確かめる（api の中で実行し、表示が出たら別のターミナルで api-prod を止める）
    docker compose exec api python -m src.session16.prod_check stop
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import statistics
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import httpx2

from kondate.verifykit import check, eq, finish, sse_events

PROMPT = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"
PROD = "http://api-prod:8000"


# ---------------------------------------------------------------- 1) image


def worker_processes() -> int:
    """uvicorn --workers の子プロセス（multiprocessing の spawn で起動される）を数える。"""
    count = 0
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if b"spawn_main" in (proc / "cmdline").read_bytes():
                count += 1
        except OSError:
            continue
    return count


def image_checks() -> None:
    @check("C1 実行ユーザーは uid 10001（root ではない）")
    def _():
        eq(os.getuid(), 10001, "uid")
        return f"uid={os.getuid()}"

    @check("C2 開発用の道具（pytest・pytest-asyncio）が入っていない")
    def _():
        eq([m for m in ("pytest", "pytest_asyncio") if importlib.util.find_spec(m) is not None], [], "見つかったもの")
        return "pytest なし・pytest_asyncio なし"

    @check("C3 PID 1 は設定を検証してから起動する serve で、--reload が無い")
    def _():
        args = [a.decode() for a in Path("/proc/1/cmdline").read_bytes().split(b"\0") if a]
        assert "src.session16.serve" in args and "--reload" not in args, args
        return " ".join(args)

    @check("C4 コードは app ユーザーから書き換えられない")
    def _():
        eq([p for p in ("/app", "/app/src/session16", "/app/src/session16/app.py") if os.access(p, os.W_OK)], [],
           "書き込めた場所")
        return "/app と /app/src/session16 に書き込めない"

    @check("C5 ワーカーのプロセス数が WEB_WORKERS と一致する")
    def _():
        workers = int(os.environ.get("WEB_WORKERS", "2"))
        eq(worker_processes(), workers if workers > 1 else 0, "子プロセスの数（1 なら子を作らない）")
        return f"WEB_WORKERS={workers} → {workers} プロセス"

    @check("C6 /health と /ready が 200")
    def _():
        h = httpx2.get("http://127.0.0.1:8000/health", timeout=5)
        r = httpx2.get("http://127.0.0.1:8000/ready", timeout=5)
        eq((h.status_code, r.status_code), (200, 200), f"status（{r.text}）")
        return f"{h.text}・{r.json()['status']}"

    finish("session16-image")


# ---------------------------------------------------------------- 2) load・3) stop で使う


@dataclass
class Result:
    status: int  # 0 は接続できなかった
    last: str | None = None  # 最後のイベント（done / error）
    error_type: str | None = None
    ttft: float | None = None  # 最初の delta まで（秒）
    total: float = 0.0
    worker: str | None = None


async def one(client: httpx2.AsyncClient, headers: dict[str, str]) -> Result:
    started = time.perf_counter()
    try:
        async with client.stream("POST", "/api/chat/stream", json={"message": PROMPT}, headers=headers) as r:
            res = Result(r.status_code, worker=r.headers.get("x-kondate-worker"))
            if r.status_code != 200:
                res.error_type = json.loads(await r.aread())["error"]["type"]
                res.total = time.perf_counter() - started
                return res
            lines: list[str] = []
            async for line in r.aiter_lines():
                if res.ttft is None and line == "event: delta":
                    res.ttft = time.perf_counter() - started
                lines.append(line)
    except httpx2.HTTPError as exc:
        return Result(0, error_type=type(exc).__name__, total=time.perf_counter() - started)
    events = sse_events([*lines, ""])
    res.last = events[-1]["event"] if events else None
    if res.last == "error":
        res.error_type = events[-1]["data"]["type"]
    res.total = time.perf_counter() - started
    return res


async def load(base: str, concurrency: int, ttft_ms: int, tps: int) -> None:
    headers = {"x-mock-ttft-ms": str(ttft_ms), "x-mock-tps": str(tps)}
    # 計測する側の接続数が先に詰まらないよう、上限を同時数より大きくしておく（既定は 100）
    limits = httpx2.Limits(max_connections=concurrency + 10, max_keepalive_connections=concurrency + 10)
    async with httpx2.AsyncClient(base_url=base, timeout=120, limits=limits) as c:
        ready = await c.get("/ready")
        started = time.perf_counter()
        results = await asyncio.gather(*(one(c, headers) for _ in range(concurrency)))
        wall = time.perf_counter() - started
    done = [r for r in results if r.last == "done"]
    rejected = [r for r in results if r.error_type == "service_unavailable"]
    other = [r for r in results if r.last != "done" and r.error_type != "service_unavailable"]
    ttfts = sorted(r.ttft for r in done if r.ttft is not None)
    print(f"同時 {concurrency} 本（x-mock-ttft-ms={ttft_ms}・x-mock-tps={tps}）", flush=True)
    print(f"  done まで届いた        : {len(done)} 本", flush=True)
    print(f"  断った（service_unavailable）: {len(rejected)} 本"
          f"（うち開始前の 503: {sum(r.status == 503 for r in rejected)} 本）", flush=True)
    print(f"  それ以外               : {len(other)} 本 {Counter(r.error_type for r in other).most_common()}", flush=True)
    if ttfts:
        print(f"  最初の delta まで      : 中央値 {statistics.median(ttfts):.2f} 秒・最大 {ttfts[-1]:.2f} 秒", flush=True)
    print(f"  全体の所要時間         : {wall:.2f} 秒", flush=True)
    print(f"  ワーカー別の done      : {dict(Counter(r.worker for r in done))}", flush=True)

    @check("L1 計測の前に /ready が 200")
    def _():
        eq(ready.status_code, 200, f"/ready（{ready.text}）")

    @check("L2 すべての要求が done か service_unavailable で終わる（それ以外は 0 本）")
    def _():
        eq(len(other), 0, "それ以外の本数")

    finish("session16-load")


async def refused(base: str) -> bool:
    """新しい接続が受け付けられなくなったか（なったら True）。接続を使い回さないよう、毎回クライアントを作る。

    ワーカーが複数のときは、止めている間も親プロセスが待ち受けの口を持ったままなので、
    新しい接続は拒否されずに応答が返らない（ReadTimeout）。どちらも「受け付けなくなった」と数える。
    """
    try:
        async with httpx2.AsyncClient(base_url=base, timeout=2) as fresh:
            await fresh.get("/health")
        return False
    except (httpx2.ConnectError, httpx2.ReadTimeout, httpx2.RemoteProtocolError):
        return True


async def stop(base: str, window: float) -> None:
    async with httpx2.AsyncClient(base_url=base, timeout=120) as c:
        long = asyncio.create_task(one(c, {"x-mock-tps": "4"}))  # 約44秒：猶予（DRAIN_GRACE_SECONDS）を必ず超える
        shorts: list[asyncio.Task[Result]] = []
        print(f"長いストリームを始めました。{window:.0f} 秒以内に、別のターミナルで次を実行してください。", flush=True)
        print("  docker compose --profile prod stop api-prod", flush=True)
        deadline = time.perf_counter() + window
        stopped = False
        while time.perf_counter() < deadline:
            shorts.append(asyncio.create_task(one(c, {"x-mock-tps": "60"})))  # 約3秒：猶予の内に終わる
            await asyncio.sleep(1.0)
            if await refused(base):
                stopped = True
                break
        short_results = await asyncio.gather(*shorts)
        long_result = await long
    accepted = [r for r in short_results if r.status == 200]

    @check("S1 止める操作を検知した（新しい接続が断られた）")
    def _():
        eq(stopped, True, f"{window:.0f} 秒以内に api-prod が止まらなかった")

    @check("S2 受け付け済みの短いストリームは、すべて done まで届く")
    def _():
        eq([r.last for r in accepted if r.last != "done"], [], "done 以外で終わったもの")
        return f"受け付け {len(accepted)} 本・done {sum(r.last == 'done' for r in accepted)} 本"

    @check("S3 長いストリームは、締め切りで error（service_unavailable）で閉じる")
    def _():
        eq((long_result.last, long_result.error_type), ("error", "service_unavailable"), "長いストリームの終わり方")
        return "止めてから閉じるまでの目安は DRAIN_GRACE_SECONDS（compose では 5 秒）"

    finish("session16-stop")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["image", "load", "stop"])
    parser.add_argument("--base", default=PROD, help="計測する相手（既定は compose 内の api-prod）")
    parser.add_argument("--concurrency", type=int, default=150)
    parser.add_argument("--ttft", type=int, default=200, help="x-mock-ttft-ms")
    parser.add_argument("--tps", type=int, default=40, help="x-mock-tps")
    parser.add_argument("--window", type=float, default=30.0, help="stop：止める操作を待つ秒数")
    args = parser.parse_args()
    if args.mode == "image":
        image_checks()
    elif args.mode == "load":
        asyncio.run(load(args.base, args.concurrency, args.ttft, args.tps))
    else:
        asyncio.run(stop(args.base, args.window))


if __name__ == "__main__":
    main()
