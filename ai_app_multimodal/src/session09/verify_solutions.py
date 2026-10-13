"""セッション9 練習問題の解答の検証。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session09

問題4 は文章で答える問題なのでコードはない。処理時間は合否に使わない。
"""

from __future__ import annotations

from urllib.parse import unquote

import httpx2

from kondate.settings import get_settings
from kondate.tts import USER_DICT, Voicevox
from kondate.verifykit import check, eq, finish
from src.session09 import vvapi
from src.session09.solutions.q1_summary import summarize_query
from src.session09.solutions.q2_cases import mismatches
from src.session09.solutions.q3_dict import WORD, try_reading
from src.session09.solutions.q5_prefetch import compare
from src.session09.solutions.q6_credit_guard import demo
from src.session09.solutions.q7_first_short import shorten_first
from src.session09.wavs import wav_info

SAMPLE_QUERY = {
    "accent_phrases": [
        {"moras": [
            {"text": "ト", "consonant": "t", "consonant_length": 0.05, "vowel": "o", "vowel_length": 0.1, "pitch": 5.5},
            {"text": "リ", "consonant": "r", "consonant_length": 0.04, "vowel": "i", "vowel_length": 0.08, "pitch": 5.8},
        ], "accent": 2, "is_interrogative": False,
         "pause_mora": {"text": "、", "consonant": None, "consonant_length": None, "vowel": "pau", "vowel_length": 0.3, "pitch": 0.0}},
        {"moras": [
            {"text": "ハ", "consonant": "h", "consonant_length": 0.06, "vowel": "a", "vowel_length": 0.12, "pitch": 5.6},
            {"text": "ク", "consonant": "k", "consonant_length": 0.05, "vowel": "U", "vowel_length": 0.04, "pitch": 0.0},
        ], "accent": 1, "pause_mora": None, "is_interrogative": True},
    ],
    "speedScale": 1.0, "pitchScale": 0.0, "intonationScale": 1.0, "volumeScale": 1.0,
    "prePhonemeLength": 0.1, "postPhonemeLength": 0.1, "outputSamplingRate": 24000, "outputStereo": False,
    "kana": "トリ'、ハ'_ク？",
}
FIRST = "鶏むね肉とキャベツがあるなら、20分以内で作れる「鶏むね肉とキャベツの塩炒め」がおすすめです。"


@check("S1 audio_query の要約（手で作った query で数える）")
def _():
    eq(summarize_query(SAMPLE_QUERY), {"reading": "トリハク", "accent_phrases": 2, "moras": 4, "devoiced": 1,
                                       "pauses": 1, "interrogative": True, "seconds_estimate": 1.04}, "要約")
    return "4 拍・無声化 1・ポーズ 1・疑問・目安 1.04 秒（0.2＋0.54＋0.3）"


@check("S2 文分割の予想がすべて当たる（URL はそのまま残る）")
def _():
    eq(mismatches(), [], "予想と違うもの")
    return "7 例すべて一致"


@check("S3 鶏もも肉を辞書に登録すると読みが直り、試したあと辞書に残らない")
async def _():
    vv = Voicevox()
    try:
        await vv.ensure_user_dict()
    finally:
        await vv.aclose()
    before, after, cleaned = await try_reading()
    eq(vvapi.plain_kana(after).startswith(WORD["pronunciation"]), True, f"登録後（{after}）")
    eq(cleaned, True, "片付け")
    async with vvapi.client() as c:
        surfaces = {w["surface"] for w in (await vvapi.list_words(c)).values()}
    eq({w["surface"] for w in USER_DICT} <= surfaces, True, "本書の辞書（鶏むね肉）は消していない")
    return "登録後 トリモモニク…・片付け済み・鶏むね肉の登録は残る"


@check("S5 先読みの有無と、RTF が 1 より小さくても途切れる例")
def _():
    def row(audio, rtf):
        return {k: (t.first_audio, t.gaps, t.finished) for k, t in compare(audio, rtf).items()}

    eq(row([3.0] * 5, 0.5), {"全文": (7.5, (), 22.5), "文ごと・先読みなし": (1.5, (1.5,) * 4, 22.5),
                            "文ごと・先読みあり": (1.5, (0.0,) * 4, 16.5)}, "5文×3秒・RTF 0.5")
    eq(row([3.0] * 5, 1.2), {"全文": (18.0, (), 33.0), "文ごと・先読みなし": (3.6, (3.6,) * 4, 33.0),
                            "文ごと・先読みあり": (3.6, (0.6,) * 4, 21.0)}, "5文×3秒・RTF 1.2")
    eq(row([1.0, 6.0], 0.5), {"全文": (3.5, (), 10.5), "文ごと・先読みなし": (0.5, (3.0,), 10.5),
                             "文ごと・先読みあり": (0.5, (2.0,), 9.5)}, "短い文→長い文・RTF 0.5")
    return "先読みなしは最後が全文と同じ時刻／短い文の次に長い文が来ると RTF 0.5 でも 2.0 秒途切れる"


@check("S6 音声の応答だけに、ミドルウェアがクレジットを付ける")
async def _():
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=demo), base_url="http://test") as client:
        audio = await client.get("/api/voice/silence")
        text = await client.get("/api/hello")
    eq(unquote(audio.headers["x-voice-credit"]), get_settings().voicevox_credit, "音声の応答")
    eq("x-voice-credit" in text.headers, False, "JSON の応答")
    return f"audio/wav には {get_settings().voicevox_credit}・JSON には付けない"


@check("S7 最初の文を読点で短くすると、1つ目の音声が短くなる")
async def _():
    short = shorten_first([FIRST, "次の文です。"])
    eq(short, ["鶏むね肉とキャベツがあるなら、", "20分以内で作れる「鶏むね肉とキャベツの塩炒め」がおすすめです。", "次の文です。"], "分割")
    eq(shorten_first(["短い文です。"]), ["短い文です。"], "短い文は分けない")
    eq(shorten_first(["読点のない長い文がここに二十文字以上続いています。"]), ["読点のない長い文がここに二十文字以上続いています。"], "読点がなければ分けない")
    vv = Voicevox()
    try:
        await vv.ensure_user_dict()
        whole = await vv.synthesize(FIRST, sample_rate=24000)
        head = await vv.synthesize(short[0], sample_rate=24000)
    finally:
        await vv.aclose()
    assert wav_info(head.wav)[3] < wav_info(whole.wav)[3], "短くした1つ目の方が長い"
    return "1文目 → 15 文字＋残り・1つ目の音声のサンプル数が減る"


finish("session09-solutions")
