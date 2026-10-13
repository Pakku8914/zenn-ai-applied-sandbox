"""セッション9の検証。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session09

処理時間（最初の音までの時間・RTF）は合否に使わない（表示もしない）。
合否は文の数・WAV の諸元とサンプル数・SHA256 の一致・kana・HTTP ステータスとヘッダで決める。
V4 はユーザー辞書を一時的に外すので、ほかの音声の処理が動いていないときに実行する（終わったら必ず登録し直す）。
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import unquote

import httpx2

from kondate.settings import get_settings
from kondate.tts import USER_DICT, Voicevox
from kondate.verifykit import check, eq, finish
from src.session09 import vvapi
from src.session09.app import app
from src.session09.first_audio import fetch_reply
from src.session09.sentences import split_sentences, strip_markdown
from src.session09.timeline import plan_sentences, plan_whole
from src.session09.wavs import join_wavs, wav_info

S = get_settings()
PATH = "/api/voice/speak"
LOOPBACK_TEXT = "鶏むね肉とキャベツで20分で作れる料理は？"
EXPECTED = [
    "鶏むね肉とキャベツがあるなら、20分以内で作れる「鶏むね肉とキャベツの塩炒め」がおすすめです。",
    "鶏むね肉をそぎ切りにして、片栗粉を薄くまぶします。",
    "フライパンで鶏肉を焼き、色が変わったらざく切りのキャベツを加えます。",
    "塩・こしょう・鶏がらスープの素で味をととのえて完成です。",
    "副菜に「豆腐とわかめのみそ汁」を合わせると、たんぱく質と野菜のバランスがよくなります。",
]
UNREACHABLE = "http://127.0.0.1:9"     # 何も待ち受けていないポート（接続が即座に断られる）


@asynccontextmanager
async def running(application) -> AsyncIterator[httpx2.AsyncClient]:
    """lifespan を動かしてから ASGITransport でアプリに直接投げる（api コンテナの APP_MODULE を切り替えなくてよい）。"""
    async with application.router.lifespan_context(application):
        transport = httpx2.ASGITransport(app=application)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
            yield client


@asynccontextmanager
async def voicevox_down(application) -> AsyncIterator[None]:
    """アプリの VOICEVOX を、つながらない宛先に一時的に差し替える。"""
    original = application.state.voicevox
    application.state.voicevox = Voicevox(base_url=UNREACHABLE)
    try:
        yield
    finally:
        await application.state.voicevox.aclose()
        application.state.voicevox = original


async def synthesize_all(texts: list[str]) -> list[bytes]:
    vv = Voicevox()
    try:
        await vv.ensure_user_dict()
        return [(await vv.synthesize(t, sample_rate=24000)).wav for t in texts]
    finally:
        await vv.aclose()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@check("V1 kondate_chat の返答（Markdown）を、番号と記号を除いた 5 文に分ける")
async def _():
    reply = await fetch_reply()
    eq(split_sentences(reply), EXPECTED, "文の分割")
    return "5文・番号付きリストの「1.」「2.」「3.」は読み上げない"


@check("V2 Markdown の記号の除去と、「。？！」・改行での区切り")
def _():
    cases = [
        ("## 今日の献立", ["今日の献立"]),
        ("- **豆腐**とわかめ", ["豆腐とわかめ"]),
        ("[作り方](https://example.com)を見てね！本当？", ["作り方を見てね！", "本当？"]),
        ("> 引用です。続き。", ["引用です。", "続き。"]),
        ("えっ！？そうなの", ["えっ！？", "そうなの"]),
        ("1.5倍の量にします。", ["1.5倍の量にします。"]),
        ("| 材料 | 分量 |\n|---|---|\n| 豆腐 | 1丁 |", ["材料 分量", "豆腐 1丁"]),
        ("---\n\n**\n```python", []),
    ]
    eq([split_sentences(t) for t, _ in cases], [want for _, want in cases], "分割結果")
    eq(strip_markdown("3. `塩`を*少し*入れる"), "塩を少し入れる", "1行の記号の除去")
    return f"{len(cases)} 例すべて期待どおり（小数点の 1.5 は番号と見なさない）"


@check("V3 audio_query の既定値と、文末の「？」による疑問の抑揚")
async def _():
    await synthesize_all([])                     # 辞書を登録しておく（合成はしない）
    async with vvapi.client() as c:
        q = await vvapi.audio_query(c, LOOPBACK_TEXT)
        flat = await vvapi.audio_query(c, LOOPBACK_TEXT.rstrip("？"))
    eq({k: q[k] for k in ("speedScale", "pitchScale", "intonationScale", "volumeScale",
                          "prePhonemeLength", "postPhonemeLength", "outputSamplingRate", "outputStereo")},
       {"speedScale": 1.0, "pitchScale": 0.0, "intonationScale": 1.0, "volumeScale": 1.0,
        "prePhonemeLength": 0.1, "postPhonemeLength": 0.1, "outputSamplingRate": 24000, "outputStereo": False},
       "既定値")
    eq((q["accent_phrases"][-1]["is_interrogative"], flat["accent_phrases"][-1]["is_interrogative"]), (True, False),
       "最後のアクセント句の is_interrogative（？あり・なし）")
    return "speedScale 1.0・前後の無音 0.1 秒・24000Hz・モノラル／「？」ありだけ疑問の抑揚"


@check("V4 ユーザー辞書の有無で読みが変わる（ニワトリムネニク → トリムネニク）")
async def _():
    vv = Voicevox()
    try:
        async with vvapi.client() as c:
            for w in USER_DICT:
                await vvapi.remove_surface(c, w["surface"])
            try:
                without = await vvapi.audio_query(c, LOOPBACK_TEXT)
            finally:
                await vv.ensure_user_dict()          # 外した語を必ず戻す
            with_dict = await vvapi.audio_query(c, LOOPBACK_TEXT)
    finally:
        await vv.aclose()
    eq(vvapi.plain_kana(without["kana"]).startswith("ニワトリムネニク"), True, f"辞書なし（{without['kana']}）")
    eq(vvapi.plain_kana(with_dict["kana"]).startswith("トリムネニク"), True, f"辞書あり（{with_dict['kana']}）")
    eq(vvapi.count_moras(without) - vvapi.count_moras(with_dict), 2, "モーラ数の差（ニワ の 2 拍）")
    return "辞書なし ニワトリムネニク… → 辞書あり トリムネニク…・モーラは 2 減る"


@check("V5 合成は決定的で、出力は 24kHz・モノラル・16bit")
async def _():
    a, b = await synthesize_all([EXPECTED[1], EXPECTED[1]])
    eq(sha(a), sha(b), "同じ文を2回合成した WAV の SHA256")
    eq(wav_info(a)[:3], (24000, 1, 2), "レート・チャンネル・バイト数")
    return "同じ文・話者・設定なら SHA256 が一致／24000Hz・1ch・16bit"


@check("V6 文ごとに合成してつないだ長さは、全文をまとめて合成した長さと一致しない")
async def _():
    sentences = split_sentences(await fetch_reply())
    *parts, whole = await synthesize_all([*sentences, "".join(sentences)])
    eq(len(parts), 5, "文の数")
    eq({wav_info(p)[:3] for p in parts}, {(24000, 1, 2)}, "各文の諸元")
    joined = join_wavs(parts)
    eq(wav_info(joined)[3], sum(wav_info(p)[3] for p in parts), "つないだサンプル数＝各文の合計")
    assert wav_info(joined)[3] != wav_info(whole)[3], "長さが一致してしまった"
    async with vvapi.client() as c:
        q_whole = await vvapi.audio_query(c, "".join(sentences))
        q_parts = [await vvapi.audio_query(c, s) for s in sentences]
    eq(vvapi.count_pauses(q_whole) - sum(vvapi.count_pauses(q) for q in q_parts), len(sentences) - 1,
       "全文にだけある文の境目のポーズの数")
    return "5文・各 24000Hz・1ch／連結 ≠ 全文（前後の無音 0.1 秒×2 が文ごとに付き、全文では境目 4 か所がポーズになる）"


@check("V7 POST /api/voice/speak は 24kHz の WAV とクレジットのヘッダを返し、利用量を記録する")
async def _():
    reply = await fetch_reply()
    expected_wav = join_wavs(await synthesize_all(split_sentences(reply)))
    async with running(app) as client:
        r = await client.post(PATH, json={"text": reply}, headers={"x-user-id": "u003"})
        records = list(app.state.usage.records)
    eq(r.status_code, 200, f"status（本文 {r.text[:200]}）")
    eq(r.headers["content-type"], "audio/wav", "content-type")
    eq(r.headers["x-voice-credit"], "VOICEVOX:%E3%81%9A%E3%82%93%E3%81%A0%E3%82%82%E3%82%93", "ヘッダの値（そのまま）")
    eq(unquote(r.headers["x-voice-credit"]), S.voicevox_credit, "ヘッダの値（デコード後）")
    eq(r.headers["x-request-id"].startswith("req_"), True, "x-request-id")
    eq(wav_info(r.content)[:3], (24000, 1, 2), "WAV の諸元")
    eq(sha(r.content), sha(expected_wav), "文ごとに合成してつないだ WAV と同じ")
    eq([(x.user_id, x.kind, x.model) for x in records], [("u003", "tts", f"voicevox:{S.voicevox_speaker}")], "利用量の記録")
    assert abs(records[0].audio_seconds - wav_info(expected_wav)[3] / 24000) <= 0.001, records[0]   # 記録した音声の秒数
    return f"200・audio/wav・x-voice-credit={S.voicevox_credit}（パーセントエンコード）・利用量 1 件（u003・tts・voicevox:{S.voicevox_speaker}）"


@check("V8 空・空白だけ・記号だけ・501 文字・項目なしは 422（VOICEVOX を呼ぶ前に断る）")
async def _():
    bodies = [{"text": ""}, {"text": "   "}, {"text": "**"}, {"text": "あ" * 501}, {}]
    got = []
    async with running(app) as client:
        async with voicevox_down(app):           # VOICEVOX を呼んでいれば 503 になるので、422 なら呼んでいない
            for body in bodies:
                r = await client.post(PATH, json=body)
                got.append((r.status_code, r.json()["error"]["type"], r.json()["error"]["message"]))
    eq(got, [(422, "invalid_request", "入力値が正しくありません：text")] * len(bodies), "ステータス・種別・文")
    return "5 件とも 422 invalid_request「入力値が正しくありません：text」"


@check("V9 VOICEVOX につながらないときは 503 tts_unavailable（上流のエラー文は返さず、利用量も記録しない）")
async def _():
    async with running(app) as client:
        async with voicevox_down(app):
            r = await client.post(PATH, json={"text": "こんにちは。"})
        records = list(app.state.usage.records)
    err = r.json()["error"]
    eq((r.status_code, err["type"], err["message"]), (503, "tts_unavailable", "音声合成エンジンに接続できませんでした"), "エラー")
    eq(err["request_id"], r.headers["x-request-id"], "request_id")
    eq(len(records), 0, "利用量の記録")
    return "503 tts_unavailable「音声合成エンジンに接続できませんでした」・利用量 0 件"


@check("V10 最初の音までの時間と途切れの計算（5文×3秒の音声、RTF 0.5 と 1.2）")
def _():
    fast = plan_sentences([1.5] * 5, [3.0] * 5)
    eq((fast.first_audio, fast.gaps, fast.finished), (1.5, (0.0, 0.0, 0.0, 0.0), 16.5), "RTF 0.5・文ごと")
    eq((plan_whole(7.5, 15.0).first_audio, plan_whole(7.5, 15.0).finished), (7.5, 22.5), "RTF 0.5・全文")
    slow = plan_sentences([3.6] * 5, [3.0] * 5)
    eq((slow.first_audio, slow.gaps, slow.finished), (3.6, (0.6, 0.6, 0.6, 0.6), 21.0), "RTF 1.2・文ごと")
    eq((plan_whole(18.0, 15.0).first_audio, plan_whole(18.0, 15.0).finished), (18.0, 33.0), "RTF 1.2・全文")
    return "RTF 0.5：最初の音 7.5→1.5 秒・途切れなし／RTF 1.2：18.0→3.6 秒・境目ごとに 0.6 秒の途切れ"


finish("session09")
