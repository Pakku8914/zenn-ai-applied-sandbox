"""遅延を繰り返し測り、p50・p95 を出す（セッション12）。時間は環境で変わるので、合否には使わない。

    docker compose exec api python -m src.session12.eval_latency
    docker compose exec api python -m src.session12.eval_latency --repeat 30 --ttft-ms 400

測るもの（セッション10の measure.py と同じく、最初の1回は準備として別に記録する）：
    stt          LOOPBACK_TEXT の音声（16kHz）を認識する（limiter 付きで別スレッド）
    tts          LOOPBACK_TEXT を合成する（24kHz）
    fridge_scan  fridge.jpg の前処理済み JPEG を mockllm に送り、食材リストを受け取る
結果は out/s12/latency.json。
"""

from __future__ import annotations

import argparse
import asyncio
import math
import statistics
import time
from collections.abc import Awaitable, Callable, Sequence

import anyio
from anthropic import AsyncAnthropic

from kondate import stt
from kondate.audio import wav_to_float32
from kondate.llm import AnthropicProvider
from kondate.media import media_path
from kondate.tts import Voicevox
from src.session12 import target_fridge as fridge
from src.session12.eval_extract import OUT, write_json

LOOPBACK_TEXT = "鶏むね肉とキャベツで20分で作れる料理は？"
TARGETS = ("stt", "tts", "fridge_scan")
MIN_FOR_P95 = 20   # これより少ないと、p95 は最大値と同じになる


def percentile(values: Sequence[float], p: float) -> float:
    """最近傍順位法：小さい順に並べて ceil(p/100 × n) 番目の値。必ず「実際に測った値のどれか」を返す。"""
    if not values:
        raise ValueError("値が1つもありません")
    if not 0 < p <= 100:
        raise ValueError(f"p は 0 より大きく 100 以下にしてください（{p}）")
    ordered = sorted(values)
    rank = math.ceil(p * len(ordered) / 100)
    return ordered[rank - 1]


def summarize(values: Sequence[int]) -> dict:
    return {
        "n": len(values),
        "mean_ms": round(statistics.fmean(values)),
        "p50_ms": percentile(values, 50),
        "p95_ms": percentile(values, 95),
        "max_ms": max(values),
    }


async def time_ms(op: Callable[[], Awaitable[object]]) -> int:
    started = time.perf_counter()
    await op()
    return round((time.perf_counter() - started) * 1000)


async def measure(op: Callable[[], Awaitable[object]], repeat: int) -> dict:
    """1回目（モデルの読み込みなどを含む）は warmup_ms として別に残し、続く repeat 回を集計する。"""
    warmup = await time_ms(op)
    samples = [await time_ms(op) for _ in range(repeat)]
    return {"warmup_ms": warmup, **summarize(samples), "samples_ms": samples}


async def run(targets: Sequence[str], repeat: int, ttft_ms: int = 0) -> dict[str, dict]:
    headers = {"x-mock-ttft-ms": str(ttft_ms)} if ttft_ms else {}
    client = AsyncAnthropic(default_headers=headers)
    vv = Voicevox()
    limiter = anyio.CapacityLimiter(1)   # 認識は同時に1件（セッション8と同じ）
    try:
        ops: dict[str, Callable[[], Awaitable[object]]] = {}
        if "stt" in targets:
            await vv.ensure_user_dict()
            audio, rate = wav_to_float32((await vv.synthesize(LOOPBACK_TEXT, sample_rate=16000)).wav)
            ops["stt"] = lambda: anyio.to_thread.run_sync(stt.transcribe, audio, rate, limiter=limiter)
        if "tts" in targets:
            await vv.ensure_user_dict()
            ops["tts"] = lambda: vv.synthesize(LOOPBACK_TEXT, sample_rate=24000)
        if "fridge_scan" in targets:
            jpeg = fridge.prepare_image(media_path("fridge.jpg").read_bytes())
            llm = AnthropicProvider(client)
            ops["fridge_scan"] = lambda: fridge.scan_fridge(llm, jpeg)
        return {name: await measure(ops[name], repeat) for name in targets}
    finally:
        await vv.aclose()
        await client.close()


def show(results: dict[str, dict]) -> None:
    for name, s in results.items():
        note = "（n<20 なので p95 は最大値と同じ）" if s["n"] < MIN_FOR_P95 else ""
        print(f"{name:<12} 準備 {s['warmup_ms']}ms ／ n={s['n']}・平均 {s['mean_ms']}ms"
              f"・p50 {s['p50_ms']}ms・p95 {s['p95_ms']}ms・最大 {s['max_ms']}ms{note}")


def main() -> int:
    p = argparse.ArgumentParser(description="遅延の p50・p95 を測る")
    p.add_argument("--targets", nargs="+", default=list(TARGETS), choices=TARGETS)
    p.add_argument("--repeat", type=int, default=MIN_FOR_P95)
    p.add_argument("--ttft-ms", type=int, default=0, help="mockllm が応答の前に待つミリ秒")
    a = p.parse_args()
    print(f"計測：{'・'.join(a.targets)} を各 {a.repeat} 回（最初の1回は準備として別に記録）"
          f"・mockllm の遅れ: {f'{a.ttft_ms}ms' if a.ttft_ms else 'なし'}")
    results = asyncio.run(run(a.targets, a.repeat, a.ttft_ms))
    show(results)
    write_json(OUT / "latency.json", results)
    print(f"→ {OUT / 'latency.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
