"""土台（kondate/）の部品が契約どおりに動くことの確認。api コンテナの中で実行する。

本文で読者が直接使うのは次のセッション以降。ここでは①バックエンド編から持ち込んだ部品が壊れていないことだけを見る。
"""

from __future__ import annotations

import asyncio

import numpy as np
import webrtcvad
from anthropic import AsyncAnthropic

from kondate.audio import float32_to_wav, wav_to_float32
from kondate.clock import FixedClock
from kondate.jobs import JobQueue
from kondate.llm import AnthropicProvider, ChatRequest, ChatResult, Done, FakeProvider, TextDelta, ToolCallDone, Usage
from kondate.metrics import cer, normalize_ja
from kondate.tts import Voicevox
from kondate.usage import UsageLog
from kondate.verifykit import check, eq, finish

TOOLS = [
    {"name": "search_recipes", "description": "条件に合うレシピを探す", "input_schema": {"type": "object", "properties": {"ingredients": {"type": "array", "items": {"type": "string"}}}}},
    {"name": "get_recipe", "description": "レシピを1件取得する", "input_schema": {"type": "object", "properties": {"recipe_id": {"type": "string"}}, "required": ["recipe_id"]}},
]


@check("K1 AnthropicProvider.stream が mockllm のツール呼び出しを ToolCallDone と Done に正規化する")
async def _():
    client = AsyncAnthropic()
    try:
        llm = AnthropicProvider(client)
        req = ChatRequest(messages=[{"role": "user", "content": "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるレシピを探して"}], tools=TOOLS)
        events = [e async for e in llm.stream(req)]
    finally:
        await client.close()
    calls = [e for e in events if isinstance(e, ToolCallDone)]
    eq([(c.name, c.input) for c in calls], [("search_recipes", {"ingredients": ["鶏むね肉", "キャベツ"], "max_minutes": 20})], "ツール呼び出し")
    eq(events[-1].stop_reason, "tool_use", "stop_reason")
    return f"テキスト差分 {sum(isinstance(e, TextDelta) for e in events)} 個 → search_recipes → stop_reason=tool_use"


@check("K2 FakeProvider は用意した結果を同じイベントの形で返す")
async def _():
    fake = FakeProvider([ChatResult("キャベツと鶏むね肉です。", [], "end_turn", Usage(10, 8))])
    events = [e async for e in fake.stream(ChatRequest(messages=[{"role": "user", "content": "x"}]))]
    eq("".join(e.text for e in events if isinstance(e, TextDelta)), "キャベツと鶏むね肉です。", "テキスト")
    eq(events[-1], Done("end_turn", Usage(10, 8)), "Done")


@check("K3 JobQueue が進捗を通知し、キャンセルできる")
async def _():
    q = JobQueue(concurrency=1)

    async def work(progress):
        for i in range(1, 4):
            await asyncio.sleep(0)
            progress(i)
        return "ok"

    job = q.submit(work, total=3)
    seen = [ev["done"] async for ev in q.events(job.id)]
    eq((job.status, job.result, seen[-1]), ("succeeded", "ok", 3), "完了したジョブ")

    async def slow(progress):
        await asyncio.sleep(30)

    job2 = q.submit(slow, total=1)
    await asyncio.sleep(0.01)
    eq(q.cancel(job2.id), True, "cancel の戻り値")
    last = [ev async for ev in q.events(job2.id)][-1]
    eq(last["status"], "cancelled", "キャンセルしたジョブ")
    assert job.id.startswith("job_") and len(job.id) == 30, job.id
    return f"進捗 {seen} → succeeded／キャンセル → cancelled"


@check("K4 UsageLog は注入した時計の時刻で記録し、ユーザー別に合計する")
def _():
    log = UsageLog(clock=FixedClock())
    log.add("u001", "llm", "m", input_tokens=100, output_tokens=20)
    log.add("u001", "stt", "whisper:small", audio_seconds=4.1, processing_seconds=2.0)
    log.add("u002", "llm", "m", input_tokens=5, output_tokens=5)
    eq(log.records[0].at, "2026-10-02T18:00:00+09:00", "時刻")
    eq(log.totals("u001"), {"input_tokens": 100, "output_tokens": 20, "audio_seconds": 4.1, "processing_seconds": 2.0}, "u001 の合計")


@check("K5 CER は正規化（NFKC・句読点と空白の除去）してから文字単位で数える")
def _():
    eq(normalize_ja("２０分で、作れる？ "), "20分で作れる", "正規化")
    eq(cer("鶏むね肉とキャベツ", "鶏むね肉とキャベツ。"), 0.0, "句読点だけの違い")
    eq(round(cer("鶏むね肉とキャベツ", "鶏胸肉とキャベツ"), 4), 0.2222, "かなと漢字の違いは誤りとして数える")


@check("K6 VOICEVOX の WAV を読み書きでき、webrtcvad が発話と無音を見分ける")
async def _():
    vv = Voicevox()
    try:
        tts = await vv.synthesize("次の手順に進んでください。")
    finally:
        await vv.aclose()
    audio, rate = wav_to_float32(tts.wav)
    eq(rate, 16000, "サンプリングレート")
    back, _ = wav_to_float32(float32_to_wav(audio, rate))
    assert np.max(np.abs(back - audio)) < 1e-3
    vad = webrtcvad.Vad(2)
    frame = int(rate * 0.03)                       # 30ms のフレーム
    pcm = (audio * 32767).astype("<i2").tobytes()
    speech = sum(vad.is_speech(pcm[i * 2:(i + frame) * 2], rate) for i in range(0, len(audio) - frame, frame))
    silence = np.zeros(rate, dtype="<i2").tobytes()
    vad = webrtcvad.Vad(2)                         # 直前の発話の余韻（ハングオーバー）を持ち越さないよう作り直す
    quiet = sum(vad.is_speech(silence[i * 2:(i + frame) * 2], rate) for i in range(0, rate - frame, frame))
    eq(quiet, 0, "無音を発話と判定したフレーム数")
    assert speech > 0
    return f"発話フレーム {speech}/{(len(audio) - frame) // frame + 1}・無音 0/{(rate - frame) // frame + 1}"


finish("session01-kit")
