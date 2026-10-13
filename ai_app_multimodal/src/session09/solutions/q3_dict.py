"""問題3：ユーザー辞書に語を登録して読みを直し、確かめたら元に戻す。

    docker compose exec api python -m src.session09.solutions.q3_dict
"""

from __future__ import annotations

import asyncio

import httpx2

from src.session09 import vvapi

WORD = {"surface": "鶏もも肉", "pronunciation": "トリモモニク", "accent_type": 3}
TEXT = "鶏もも肉を一口大に切ります。"


async def add_word(c: httpx2.AsyncClient, word: dict) -> str:
    """語を登録し、その語の UUID を返す（あとで消すのに使う）。"""
    r = await c.post("/user_dict_word", params=word)
    r.raise_for_status()
    return r.json()


async def try_reading(word: dict = WORD, text: str = TEXT) -> tuple[str, str, bool]:
    """(登録前の kana, 登録後の kana, 片付けたあと辞書に残っていないか) を返す。"""
    async with vvapi.client() as c:
        await vvapi.remove_surface(c, word["surface"])          # 前回の残りがあれば消してから始める
        before = (await vvapi.audio_query(c, text))["kana"]
        word_uuid = await add_word(c, word)
        try:
            after = (await vvapi.audio_query(c, text))["kana"]
        finally:
            (await c.delete(f"/user_dict_word/{word_uuid}")).raise_for_status()   # 試したら必ず消す
        cleaned = all(w["surface"] != word["surface"] for w in (await vvapi.list_words(c)).values())
    return before, after, cleaned


def main() -> int:
    before, after, cleaned = asyncio.run(try_reading())
    print(f"登録前: {before}")
    print(f"登録後: {after}")
    print(f"片付け: {'済み' if cleaned else '残っている'}")
    return 0 if WORD["pronunciation"] in vvapi.plain_kana(after) and cleaned else 1


if __name__ == "__main__":
    raise SystemExit(main())
