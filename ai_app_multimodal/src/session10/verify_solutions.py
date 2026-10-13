"""セッション10：練習問題の解答の検証。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session10

処理時間は合否に使わない。問題4はコードのない問題なので検証しない。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from kondate import stt
from kondate.llm import ChatResult, FakeProvider, Usage
from kondate.verifykit import check, eq, finish
from src.session10.app import app as base_app
from src.session10.asgi_ws import AsgiWebSocket
from src.session10.sentence_buffer import SentenceBuffer
from src.session10.solutions import q6_push_to_talk
from src.session10.solutions.q1_worklet_port import run, to_int16
from src.session10.solutions.q2_vad_cases import CASES, simulate
from src.session10.solutions.q3_breakdown import EXAMPLES, breakdown, dominant
from src.session10.solutions.q5_ordered import demo
from src.session10.solutions.q7_early_first import EarlyFirstBuffer, first_delta
from src.session10.talk import START, STOP, chunks, kinds, receive_until, send_frames, silence, speech_pcm

ROOT = Path(__file__).resolve().parents[2]
LOOPBACK_TEXT = "鶏むね肉とキャベツで20分で作れる料理は？"


def kondate_chat_text() -> str:
    data = json.loads((ROOT / "mockllm/fixtures/kondate_chat.json").read_text(encoding="utf-8"))
    return data["steps"][0]["text"]


def fixed_transcriber(audio, rate: int) -> stt.SttResult:
    return stt.SttResult("こんにちは", len(audio) / rate, 0.0)


@check("S1 worklet の変換を Python に写すと、48kHz も 44.1kHz も 1 秒で 640 バイト×50 個になる")
def _():
    c48, x48 = run(48000)
    eq((len(c48), {len(c) for c in c48}), (50, {640}), "48kHz")
    got48 = np.frombuffer(b"".join(c48), dtype="<i2")
    eq(bool(np.array_equal(got48, to_int16(x48[::3]))), True, "48kHz は入力の 3 つおきのサンプル")
    c44, x44 = run(44100)
    eq((len(c44), {len(c) for c in c44}), (50, {640}), "44.1kHz")
    got44 = np.frombuffer(b"".join(c44), dtype="<i2").astype(int)
    want44 = to_int16(np.interp(np.arange(16000) * 44100 / 16000, np.arange(len(x44)), x44)).astype(int)
    eq(int(np.abs(got44 - want44).max()) <= 1, True, "44.1kHz は線形補間（差は 1 以下）")
    return "48kHz・44.1kHz とも 640 バイト×50 個＝1 秒ぶん／48kHz は 3 つおき・44.1kHz は線形補間"


@check("S2 VAD の予想：無音 600ms なら読点の間で切れず、300ms なら 2 つに分かれる")
def _():
    want = {
        ("雑音（0.09 秒）", 600): [], ("雑音（0.09 秒）", 300): [],
        ("読点の間（0.45 秒）", 600): ["speech_start@450ms", "speech_end@3450ms（3.45秒）"],
        ("読点の間（0.45 秒）", 300): ["speech_start@450ms", "speech_end@1800ms（1.80秒）",
                                   "speech_start@2100ms", "speech_end@3150ms（1.35秒）"],
        ("鳴りっぱなし（16 秒）", 600): ["speech_start@150ms", "speech_end@15000ms（15.00秒）", "speech_start@15150ms"],
        ("鳴りっぱなし（16 秒）", 300): ["speech_start@150ms", "speech_end@15000ms（15.00秒）", "speech_start@15150ms"],
    }
    eq({(name, end): simulate(CASES[name], end) for name, end in want}, want, "判定")
    return "雑音 → なし／読点の間 600ms → 1 発話（3.45 秒）・300ms → 2 発話（1.80＋1.35 秒）／16 秒 → 15 秒で打ち切り"


@check("S3 遅延の内訳から、支配的な部分と割合を出す")
def _():
    got = {label: dominant(lat) for label, lat in EXAMPLES.items()}
    eq(got, {"A": ("stt", 49.7), "B": ("llm_first_sentence", 58.0), "C": ("vad", 41.2), "D": None}, "支配的な部分")
    eq(breakdown(EXAMPLES["A"])[-1], ("other", 5), "A の残り（送信など）")
    return "A：stt 49.7%／B：llm_first_sentence 58.0%／C：vad 41.2%／D：返答なし"


@check("S5 合成を 2 本まで同時に進めても、送る順番は文の順のまま")
async def _():
    one, two = await demo(1), await demo(2)
    in_order = list(enumerate("ABCDE"))
    eq((one["sent"], two["sent"]), (in_order, in_order), "送った順")
    eq((one["peak"], two["peak"]), (1, 2), "同時に動いた合成の最大数")
    eq(one["finished"], list("ABCDE"), "1 本なら終わる順も文の順")
    eq(two["finished"].index("B") < two["finished"].index("A"), True, "2 本なら B が A より先に終わる")
    return "1 本・2 本とも A〜E の順に送る／2 本では B が A より先に終わっても抜かさない"


@check("S6 stop で発話を確定させる：元のアプリは発話を捨てて閉じ、押して話す方式は返事をしてから閉じる")
async def _():
    frames = chunks(silence(0.5) + await speech_pcm(LOOPBACK_TEXT))   # 後ろに無音がない＝VAD は話し終わりを判定できない
    results = []
    for target in (base_app, q6_push_to_talk.app):
        log: list = []
        async with target.router.lifespan_context(target):
            target.state.transcriber = fixed_transcriber
            target.state.llm = FakeProvider([ChatResult("はい。", [], "end_turn", Usage(1, 1))])
            async with AsgiWebSocket(target) as ws:
                await ws.send_text(START)
                await send_frames(ws, frames)
                await ws.send_text(STOP)
                await receive_until(ws, log, stop_types=())
        results.append((kinds(log), ws.close_code))
    (base_kinds, base_code), (push_kinds, push_code) = results
    eq((base_kinds, base_code), (["ready", "vad"], 1000), "元のアプリ")
    eq((push_kinds[:4], push_kinds[-1], push_kinds.count("audio"), push_code),
       (["ready", "vad", "vad", "transcript"], "turn_end", 1, 1000), "押して話す方式")
    return "元：ready・vad(speech_start) のまま 1000／押して話す：speech_end → transcript → audio 1 つ → turn_end → 1000"


@check("S7 最初の文を「、」で早めに区切ると、6 文字ずつの差分で 1文目が 8 個目 → 3 個目に早まる")
def _():
    text = kondate_chat_text()
    base_first, base_out = first_delta(SentenceBuffer(), text)
    early_first, early_out = first_delta(EarlyFirstBuffer(), text)
    eq((base_first, len(base_out)), (8, 5), "ふつう")
    eq((early_first, len(early_out)), (3, 6), "最初の文を早める")
    eq(early_out[0], "鶏むね肉とキャベツがあるなら、", "最初の断片")
    eq((early_out[0] + early_out[1], early_out[2:]), (base_out[0], base_out[1:]), "つなぐと元の 5 文と同じ")
    return "1文目 8 個目 → 3 個目（「鶏むね肉とキャベツがあるなら、」）／つなぐと元の 5 文と同じ"


finish("session10-solutions")
