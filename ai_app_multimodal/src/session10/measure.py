"""1ターンの遅延の内訳を表示する。ASGI に直接つなぎ、マイクと同じ速さ（20ms ごと）で発話を送る。

    docker compose exec api python -m src.session10.measure                        # mockllm は待たずに返す
    docker compose exec api python -m src.session10.measure --ttft-ms 400 --tps 40  # 本物の LLM に近い遅れを注入する

表示する時間は環境と実行ごとに変わる（verify の合否には使わない）。api の APP_MODULE は切り替えなくてよい。
"""

from __future__ import annotations

import argparse
import asyncio

import anyio
import numpy as np
from anthropic import AsyncAnthropic

from kondate import stt
from kondate.llm import AnthropicProvider
from src.session10.app import app as default_app
from src.session10.asgi_ws import AsgiWebSocket
from src.session10.latency import KEYS
from src.session10.talk import converse, speech_pcm, utterance

LOOPBACK_TEXT = "鶏むね肉とキャベツで20分で作れる料理は？"
PARTS = KEYS[:4]                     # first_audio 以外の4つ（足すと first_audio にほぼ等しい）


async def measure(app, pcm: bytes, headers: dict[str, str], turns: int) -> list[dict]:
    """turns 回話しかけ、各ターンの latency_ms を返す。"""
    results = []
    async with app.router.lifespan_context(app):
        client = AsyncAnthropic(default_headers=headers)
        app.state.llm = AnthropicProvider(client)
        try:
            # 初回だけかかる準備（Whisper のモデルと VOICEVOX の話者の読み込み）を、計測の前に済ませる
            await anyio.to_thread.run_sync(stt.transcribe, np.zeros(16000, np.float32), 16000)
            await app.state.voicevox.ensure_user_dict()
            await app.state.voicevox.synthesize("準備です。", sample_rate=24000)
            for _ in range(turns):
                async with AsgiWebSocket(app) as ws:
                    log = await converse(ws, utterance(pcm), realtime=True)
                results.append(next(m for m in log if isinstance(m, dict) and m["type"] == "turn_end")["latency_ms"])
        finally:
            await client.close()
    return results


def show(results: list[dict]) -> None:
    for n, lat in enumerate(results, 1):
        top = max(PARTS, key=lambda k: lat[k])
        parts = " ／ ".join(f"{k} {lat[k]}ms" for k in PARTS)
        print(f"ターン{n}: {parts} → first_audio {lat['first_audio']}ms（最も長いのは {top}）")


async def main_async(args: argparse.Namespace) -> int:
    headers = {}
    if args.ttft_ms:
        headers["x-mock-ttft-ms"] = str(args.ttft_ms)
    if args.tps:
        headers["x-mock-tps"] = str(args.tps)
    pcm = await speech_pcm(LOOPBACK_TEXT)
    print(f"発話: {LOOPBACK_TEXT}（{len(pcm) / 32000:.2f}秒）・mockllm の遅れ: {headers or 'なし'}")
    show(await measure(default_app, pcm, headers, args.turns))
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="1ターンの遅延の内訳を表示する")
    p.add_argument("--ttft-ms", type=int, default=0, help="mockllm が最初の差分の前に待つミリ秒")
    p.add_argument("--tps", type=int, default=0, help="mockllm が差分を出す速さ（トークン/秒）")
    p.add_argument("--turns", type=int, default=3)
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(parse_args())))
