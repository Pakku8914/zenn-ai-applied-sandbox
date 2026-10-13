"""VOICEVOX ENGINE の API を、中身が見える形で呼ぶ小さな関数。

土台の kondate.tts.Voicevox.synthesize は audio_query → synthesis を1回で済ませるので、
本章では2つの呼び出しを分け、間にある audio_query（読み・アクセント・速さなどの設計図）を読む。
"""

from __future__ import annotations

import re

import httpx2

from kondate.settings import get_settings


def client() -> httpx2.AsyncClient:
    return httpx2.AsyncClient(base_url=get_settings().voicevox_url, timeout=60.0)


def _speaker(speaker: int | None) -> int:
    return speaker if speaker is not None else get_settings().voicevox_speaker


async def audio_query(c: httpx2.AsyncClient, text: str, speaker: int | None = None) -> dict:
    """文 → audio_query（JSON）。ユーザー辞書はこの時点で読みに反映される。"""
    r = await c.post("/audio_query", params={"text": text, "speaker": _speaker(speaker)})
    r.raise_for_status()
    return r.json()


async def synthesis(c: httpx2.AsyncClient, query: dict, speaker: int | None = None) -> bytes:
    """audio_query → WAV。読みは query の accent_phrases で決まる（kana は表示用で、書き換えても音は変わらない）。"""
    r = await c.post("/synthesis", params={"speaker": _speaker(speaker)}, json=query)
    r.raise_for_status()
    return r.content


def plain_kana(kana: str) -> str:
    """kana からアクセント（'）・無声化（_）・区切り（/ 、）・疑問（？）の記号を除き、読みの文字だけにする。"""
    return re.sub(r"['_/、？]", "", kana)


def count_moras(query: dict) -> int:
    """モーラ（拍）の数。ポーズ（pause_mora）は数えない。"""
    return sum(len(ap["moras"]) for ap in query["accent_phrases"])


def count_pauses(query: dict) -> int:
    """アクセント句の後ろに入る間（pause_mora）の数。"""
    return sum(1 for ap in query["accent_phrases"] if ap.get("pause_mora"))


async def list_words(c: httpx2.AsyncClient) -> dict[str, dict]:
    """ユーザー辞書の全語（キーは語の UUID）。"""
    r = await c.get("/user_dict")
    r.raise_for_status()
    return r.json()


async def remove_surface(c: httpx2.AsyncClient, surface: str) -> int:
    """表記が surface の語をすべて辞書から消し、消した数を返す。"""
    removed = 0
    for word_uuid, word in (await list_words(c)).items():
        if word["surface"] == surface:
            r = await c.delete(f"/user_dict_word/{word_uuid}")
            r.raise_for_status()
            removed += 1
    return removed
