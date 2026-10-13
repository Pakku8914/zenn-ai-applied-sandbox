"""セッション10の検証。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session10

WebSocket は ASGI に直接つないで試す（asgi_ws.AsgiWebSocket）。api の APP_MODULE は切り替えなくてよい。
処理時間（latency_ms の値）は合否に使わない（表示もしない）。合否はメッセージの種類と順番・文の数・
WAV の諸元・CER・latency_ms のキーと大小関係・close コード・呼び出し回数で決める。
Whisper は small（キャッシュ済み）を使う。
"""

from __future__ import annotations

import io
import json
import wave
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx2
from anthropic import AsyncAnthropic

from kondate import stt
from kondate.llm import AnthropicProvider, ChatResult, FakeProvider, Usage
from kondate.metrics import cer
from kondate.settings import get_settings
from kondate.tts import Voicevox
from kondate.verifykit import check, eq, finish
from src.session10.app import app
from src.session10.asgi_ws import AsgiWebSocket
from src.session10.latency import KEYS, TurnTimes
from src.session10.sentence_buffer import SentenceBuffer
from src.session10.sentences import split_sentences
from src.session10.session import MSG_CONTROL, MSG_FRAME, MSG_START, MSG_TTS, MSG_UPSTREAM
from src.session10.talk import (START, STOP, chunks, converse, kinds, receive_until, send_frames, silence,
                                speech_pcm, utterance)
from src.session10.vad import FRAME_BYTES, UtteranceDetector

S = get_settings()
ROOT = Path(__file__).resolve().parents[2]
LOOPBACK_TEXT = "鶏むね肉とキャベツで20分で作れる料理は？"
EXPECTED = [
    "鶏むね肉とキャベツがあるなら、20分以内で作れる「鶏むね肉とキャベツの塩炒め」がおすすめです。",
    "鶏むね肉をそぎ切りにして、片栗粉を薄くまぶします。",
    "フライパンで鶏肉を焼き、色が変わったらざく切りのキャベツを加えます。",
    "塩・こしょう・鶏がらスープの素で味をととのえて完成です。",
    "副菜に「豆腐とわかめのみそ汁」を合わせると、たんぱく質と野菜のバランスがよくなります。",
]
MARKDOWN_CASES = "\n".join([
    "## 今日の献立", "- **豆腐**とわかめ", "[作り方](https://example.com)を見てね！本当？",
    "> 引用です。続き。", "えっ！？そうなの", "1.5倍の量にします。", "| 材料 | 分量 |\n|---|---|\n| 豆腐 | 1丁 |",
])
UNREACHABLE = "http://127.0.0.1:9"          # 何も待ち受けていないポート（接続が即座に断られる）
VOICED, SILENT = b"\x01" * FRAME_BYTES, bytes(FRAME_BYTES)
_pcm_cache: dict[str, bytes] = {}


def wav_info(wav: bytes) -> tuple[int, int, int]:
    """(サンプリングレート, チャンネル数, 1サンプルのバイト数)。"""
    with wave.open(io.BytesIO(wav)) as wf:
        return wf.getframerate(), wf.getnchannels(), wf.getsampwidth()


def kondate_chat_text() -> str:
    data = json.loads((ROOT / "mockllm/fixtures/kondate_chat.json").read_text(encoding="utf-8"))
    return data["steps"][0]["text"]


def stream_sentences(text: str, size: int) -> list[str]:
    buf, out = SentenceBuffer(), []
    for i in range(0, len(text), size):
        out += buf.feed(text[i:i + size])
    return out + buf.flush()


async def loopback_pcm() -> bytes:
    if LOOPBACK_TEXT not in _pcm_cache:
        _pcm_cache[LOOPBACK_TEXT] = await speech_pcm(LOOPBACK_TEXT)
    return _pcm_cache[LOOPBACK_TEXT]


def fake_detector() -> UtteranceDetector:
    """先頭のバイトが 1 のフレームを「声あり」とする検出器（webrtcvad を使わずに規則だけを確かめる）。"""
    return UtteranceDetector(is_speech=lambda frame: frame[0] == 1)


def push_all(det: UtteranceDetector, pcm: bytes) -> list:
    events = []
    for c in chunks(pcm):
        events += det.push(c)
    return events


class FixedTranscriber:
    """音声認識の代わりに、決まった文を返す（呼ばれた回数を数える）。"""

    def __init__(self, text: str) -> None:
        self.text, self.calls = text, 0

    def __call__(self, audio, rate: int) -> stt.SttResult:
        self.calls += 1
        return stt.SttResult(self.text, len(audio) / rate, 0.0)


@contextmanager
def swapped(state, **values) -> Iterator[None]:
    """app.state の項目を一時的に差し替え、終わったら元に戻す。"""
    saved = {k: getattr(state, k) for k in values}
    for k, v in values.items():
        setattr(state, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(state, k, v)


async def one_turn(frames: list[bytes]) -> tuple[list, int | None]:
    async with AsgiWebSocket(app) as ws:
        log = await converse(ws, frames)
    return log, ws.close_code


async def exchange(outgoing: list[str | bytes], headers: dict | None = None) -> tuple[bool, list, int | None]:
    """メッセージを順に送り、接続が閉じるまで受け取る。"""
    async with AsgiWebSocket(app, headers=headers) as ws:
        for m in outgoing:
            await (ws.send_text(m) if isinstance(m, str) else ws.send_bytes(m))
        log: list = []
        await receive_until(ws, log, stop_types=())
    return ws.accepted, log, ws.close_code


@check("V1 LLM の差分から文を組み立てる：どこで区切って流しても、全文を split_sentences に渡した結果と同じになる")
def _():
    reply = kondate_chat_text()
    eq(split_sentences(reply), EXPECTED, "全文の分割")
    for size in range(1, 13):
        eq(stream_sentences(reply, size), EXPECTED, f"{size} 文字ずつ")
        eq(stream_sentences(MARKDOWN_CASES, size), split_sentences(MARKDOWN_CASES), f"記号入り・{size} 文字ずつ")
    buf = SentenceBuffer()
    first = next(n for n, i in enumerate(range(0, len(reply), 6), 1) if buf.feed(reply[i:i + 6]))
    eq(first, 8, "6 文字ずつのとき、1文目が完成する差分の番号")
    return "1〜12 文字ずつ×2 種類の返答で一致／6 文字ずつなら 1文目は 8 個目の差分で完成"


@check("V2 VAD の規則（30ms に組み直し、声が 150ms で開始・無音 600ms で終了・15 秒で打ち切り）")
def _():
    det = fake_detector()
    for c in chunks(VOICED * 2)[:3]:
        det.push(c)
    eq(det.frame_index + 1, 2, "20ms を3通送ったときに判定した 30ms のフレーム数")

    blip = push_all(fake_detector(), SILENT * 10 + VOICED * 3 + SILENT * 30)
    eq(blip, [], "0.09 秒だけの声")

    events = push_all(fake_detector(), SILENT * 10 + VOICED * 30 + SILENT * 25)
    eq([(e.kind, (e.frame + 1) * 30) for e in events], [("speech_start", 450), ("speech_end", 1800)],
       "判定の種類と時刻（ms）")
    eq(len(events[1].audio) / 32000, 1.8, "切り出した秒数")

    long = push_all(fake_detector(), VOICED * 533)
    eq([e.kind for e in long], ["speech_start", "speech_end", "speech_start"], "16 秒続く声")
    eq(len(long[1].audio) / 32000, 15.0, "打ち切った発話の秒数")
    return ("20ms×3通 → 30ms×2フレーム／0.09 秒の声 → 判定なし／0.9 秒の声 → 開始 450ms・終了 1800ms・"
            "1.8 秒を切り出し／16 秒の声 → 15.0 秒で打ち切り")


@check("V3 webrtcvad（aggressiveness 2）は、合成した発話で開始と終了を1回ずつ判定し、無音だけでは何も判定しない")
async def _():
    events = push_all(UtteranceDetector(), b"".join(utterance(await loopback_pcm())))
    eq([e.kind for e in events], ["speech_start", "speech_end"], "合成した発話")
    eq(push_all(UtteranceDetector(), silence(2.0)), [], "無音 2 秒")
    return "発話：speech_start・speech_end を1回ずつ／無音 2 秒：判定なし"


@check("V4 遅延の内訳の計算（時刻の差をミリ秒に丸める。返答しなかったターンは null）")
def _():
    t = TurnTimes(last_voice=10.0, speech_end=10.6, transcript=12.4, first_sentence=12.45,
                  tts_first=13.65, first_audio=13.66)
    eq(t.latency_ms(), {"vad": 600, "stt": 1800, "llm_first_sentence": 50, "tts_first": 1200, "first_audio": 3660},
       "内訳")
    t.sentence_ready(99.0)
    eq(t.first_sentence, 12.45, "2文目以降で上書きしない")
    quiet = TurnTimes(last_voice=1.0, speech_end=1.6, transcript=2.0).latency_ms()
    eq(quiet, {"vad": 600, "stt": 400, "llm_first_sentence": None, "tts_first": None, "first_audio": None},
       "聞き取れなかったターン")
    return "vad 600・stt 1800・llm_first_sentence 50・tts_first 1200・first_audio 3660／返答なしは後ろ3つが None"


@check("V5 GET / は音声対話の画面を返し、AudioWorklet のファイルは JavaScript として配信される")
async def _():
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
            page = await client.get("/")
            worklet = await client.get("/static/pcm-worklet.js")
    eq((page.status_code, page.headers["content-type"]), (200, "text/html; charset=utf-8"), "GET /")
    eq("/ws/voice" in page.text and "/static/pcm-worklet.js" in page.text, True, "画面が参照するパス")
    eq(worklet.status_code, 200, "worklet")
    eq(worklet.headers["content-type"].split(";")[0] in ("text/javascript", "application/javascript"), True,
       f"worklet の content-type（{worklet.headers['content-type']}）")
    eq('registerProcessor("pcm-sender"' in worklet.text, True, "worklet の登録名")
    return "GET / 200 text/html・/static/pcm-worklet.js 200 JavaScript（pcm-sender）"


@check("V6 取り決めに反する接続・メッセージは、error（invalid_request）を送って 1008 で閉じる")
async def _():
    got = []
    async with app.router.lifespan_context(app):
        cases = [
            ([bytes(640)], MSG_START),                                             # start より先に音声
            ([json.dumps({"type": "start", "sample_rate": 48000})], MSG_START),    # レート違い
            ([START, bytes(1000)], MSG_FRAME),                                     # 20ms でない音声
            ([START, "hello"], MSG_CONTROL),                                       # JSON でないテキスト
        ]
        for outgoing, message in cases:
            accepted, log, code = await exchange(outgoing)
            err = log[-1]["error"]
            eq(err["request_id"].startswith("req_"), True, "request_id")
            got.append((accepted, kinds(log), err["type"], err["message"] == message, code))
        foreign = await exchange([START], headers={"origin": "http://evil.example"})
    eq(got, [(True, ["error"], "invalid_request", True, 1008), (True, ["error"], "invalid_request", True, 1008),
             (True, ["ready", "error"], "invalid_request", True, 1008),
             (True, ["ready", "error"], "invalid_request", True, 1008)], "受け付け・種類・close コード")
    eq(foreign, (False, [], 1008), "別のサイトの Origin")
    return "start なしの音声・48000Hz・1000 バイトの音声・JSON でないテキスト → 1008／別サイトの Origin → accept せずに 1008"


@check("V7 合成した発話を 20ms ずつ送ると、取り決めどおりの順で返事が届く")
async def _():
    async with httpx2.AsyncClient(base_url=S.mockllm_url, timeout=10) as mock:
        (await mock.post("/_mock/reset")).raise_for_status()
        frames = utterance(await loopback_pcm())
        async with app.router.lifespan_context(app):
            log, code = await one_turn(frames)
            records = [r.kind for r in app.state.usage.records]
        stats = (await mock.get("/_mock/stats")).json()
    k = kinds(log)
    eq(k[:4], ["ready", "vad", "vad", "transcript"], "最初の4通")
    eq((log[0]["credit"], log[1]["state"], log[2]["state"]), (S.voicevox_credit, "speech_start", "speech_end"),
       "ready と vad")
    eq((k[-1], code), ("turn_end", 1000), "最後のメッセージと、stop のあとの close コード")
    eq(k.index("reply_delta") < k.index("audio"), True, "返答の文字は音声より先に届く")
    pairs = []
    for i, m in enumerate(log):
        if isinstance(m, bytes):
            eq(kinds([log[i - 1]]), ["audio"], f"{i} 番目のバイナリの直前")
        elif m["type"] == "audio":
            pairs.append((m, log[i + 1]))
    eq([m["index"] for m, _ in pairs], [0, 1, 2, 3, 4], "audio の index")
    eq([m["text"] for m, _ in pairs], EXPECTED, "読み上げた文")
    eq({(m["sample_rate"], m["bytes"] == len(w), wav_info(w)) for m, w in pairs}, {(24000, True, (24000, 1, 2))},
       "audio の諸元と WAV")
    reply = "".join(m["text"] for m in log if isinstance(m, dict) and m["type"] == "reply_delta")
    eq(split_sentences(reply), EXPECTED, "reply_delta をつないだ返答")
    score = cer(LOOPBACK_TEXT, log[3]["text"])
    assert score <= 0.10, (score, log[3]["text"])
    lat = log[-1]["latency_ms"]
    eq(list(lat), list(KEYS), "latency_ms のキー")
    assert all(isinstance(v, int) and v >= 0 for v in lat.values()), lat
    assert lat["first_audio"] + 3 >= sum(lat[x] for x in KEYS[:4]), lat     # 丸めの誤差（最大 2.5ms）を見込む
    eq(records, ["stt", "llm", "tts"], "利用量の記録")
    eq((stats["by_scenario"], stats["requests"][0]["stream"]), ({"kondate_chat": 1}, True), "mockllm の呼び出し")
    return ("ready → vad(speech_start) → vad(speech_end) → transcript → reply_delta… → audio 0〜4（24000Hz）→ "
            "turn_end／CER ≤ 0.10／latency_ms 5 項目／利用量 stt・llm・tts／kondate_chat を1回")


@check("V8 LLM（529）と VOICEVOX（接続できない）の障害は error で知らせ、接続は閉じない")
async def _():
    frames = utterance(await loopback_pcm())
    async with app.router.lifespan_context(app):
        client = AsyncAnthropic(max_retries=0, default_headers={"x-mock-fault": "529"})
        broken = Voicevox(base_url=UNREACHABLE)
        try:
            with swapped(app.state, transcriber=FixedTranscriber(LOOPBACK_TEXT), llm=AnthropicProvider(client)):
                llm_log, llm_code = await one_turn(frames)
            with swapped(app.state, transcriber=FixedTranscriber(LOOPBACK_TEXT), voicevox=broken):
                tts_log, tts_code = await one_turn(frames)
        finally:
            await client.close()
            await broken.aclose()
    eq(kinds(llm_log), ["ready", "vad", "vad", "transcript", "error"], "LLM の障害")
    eq((llm_log[-1]["error"]["type"], llm_log[-1]["error"]["message"]), ("upstream_unavailable", MSG_UPSTREAM),
       "LLM の障害の error")
    k = kinds(tts_log)
    eq((k[:4], k[-1], "audio" in k, "turn_end" in k), (["ready", "vad", "vad", "transcript"], "error", False, False),
       "VOICEVOX の障害")
    eq((tts_log[-1]["error"]["type"], tts_log[-1]["error"]["message"]), ("tts_unavailable", MSG_TTS),
       "VOICEVOX の障害の error")
    eq((llm_code, tts_code), (1000, 1000), "障害のあとも stop で正常に閉じる")
    return "upstream_unavailable・tts_unavailable（上流のエラー文は返さない）／どちらも stop で 1000"


@check("V9 返答を作っている間に届いた発話は捨て、turn_end のあとの発話には返事をする")
async def _():
    frames = utterance(await loopback_pcm())
    probe = FixedTranscriber("こんにちは")
    replies = [ChatResult("はい。", [], "end_turn", Usage(1, 1)) for _ in range(2)]
    log: list = []
    async with app.router.lifespan_context(app):
        with swapped(app.state, transcriber=probe, llm=FakeProvider(replies)):
            async with AsgiWebSocket(app) as ws:
                await ws.send_text(START)
                await send_frames(ws, frames + frames)     # 2つ続けて話す（2つ目は返答を作っている間に届く）
                await receive_until(ws, log)
                await send_frames(ws, frames)              # turn_end のあとに、もう1回話す
                await receive_until(ws, log)
                await ws.send_text(STOP)
                await receive_until(ws, log, stop_types=())
    k = kinds(log)
    eq((probe.calls, k.count("transcript"), k.count("turn_end"), ws.close_code), (2, 2, 2, 1000),
       "認識の回数・transcript・turn_end・close コード")
    return "3 回話して、認識 2 回・turn_end 2 回（返答中の発話は捨てる）"


finish("session10")
