"""献立相談の返答（mockllm の kondate_chat）を、全文まとめてと文ごとで合成し、最初の音までの時間を比べる。

    docker compose exec api python -m src.session09.first_audio

表示する時間は環境と実行ごとに変わる（verify の合否には使わない）。
"""

from __future__ import annotations

import asyncio

from anthropic import AsyncAnthropic

from kondate.llm import AnthropicProvider, ChatRequest
from kondate.tts import TtsResult, Voicevox
from src.session09.sentences import split_sentences
from src.session09.timeline import plan_sentences, plan_whole

QUESTION = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"
RATE = 24000


async def fetch_reply(question: str = QUESTION) -> str:
    client = AsyncAnthropic()  # 接続先は環境変数 ANTHROPIC_BASE_URL（既定は mockllm）
    try:
        result = await AnthropicProvider(client).complete(ChatRequest(messages=[{"role": "user", "content": question}]))
    finally:
        await client.close()
    return result.text


async def synthesize(sentences: list[str]) -> tuple[TtsResult, list[TtsResult]]:
    vv = Voicevox()
    try:
        await vv.ensure_user_dict()
        await vv.synthesize("準備です。", sample_rate=RATE)      # 初回だけ話者の読み込みが入るので、測る前に1回動かす
        whole = await vv.synthesize("".join(sentences), sample_rate=RATE)
        parts = [await vv.synthesize(s, sample_rate=RATE) for s in sentences]
        return whole, parts
    finally:
        await vv.aclose()


async def main_async() -> int:
    sentences = split_sentences(await fetch_reply())
    whole, parts = await synthesize(sentences)
    print(f"文の数: {len(sentences)}（{RATE}Hz・モノラル）")
    for i, (s, p) in enumerate(zip(sentences, parts, strict=True), 1):
        print(f"  [{i}] 音声 {p.audio_seconds:.2f}秒・合成 {p.processing_seconds:.2f}秒（RTF {p.rtf:.2f}） {s[:16]}…")
    seq = plan_sentences([p.processing_seconds for p in parts], [p.audio_seconds for p in parts])
    one = plan_whole(whole.processing_seconds, whole.audio_seconds)
    print(f"音声の長さ: 全文 {whole.audio_seconds:.2f}秒／文ごとの合計 {sum(p.audio_seconds for p in parts):.2f}秒")
    print(f"最初の音まで: 全文 {one.first_audio:.2f}秒 → 文ごと {seq.first_audio:.2f}秒")
    waits = [g for g in seq.gaps if g > 0]
    print(f"文の間の途切れ: {'なし' if not waits else f'{len(waits)}か所・最大 {max(waits):.2f}秒'}")
    print(f"最後の音まで: 全文 {one.finished:.2f}秒 → 文ごと {seq.finished:.2f}秒")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
