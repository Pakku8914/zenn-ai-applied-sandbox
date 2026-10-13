"""audio_query の中身（読み・アクセント句・モーラ・調整値）を表示する。

    docker compose exec api python -m src.session09.inspect_query "鶏むね肉とキャベツで20分で作れる料理は？"
    docker compose exec api python -m src.session09.inspect_query --no-dict "鶏むね肉とキャベツで20分で作れる料理は？"

--no-dict は USER_DICT の語をいったん辞書から外して問い合わせ、終わったら登録し直す。
辞書は VOICEVOX ENGINE 全体で共有されるので、ほかの処理が動いていないときに使う。
"""

from __future__ import annotations

import argparse
import asyncio

from kondate.tts import USER_DICT, Voicevox
from src.session09 import vvapi

KEYS = ("speedScale", "pitchScale", "intonationScale", "volumeScale",
        "prePhonemeLength", "postPhonemeLength", "outputSamplingRate", "outputStereo")


async def fetch(text: str, *, use_dict: bool = True) -> dict:
    vv = Voicevox()
    try:
        async with vvapi.client() as c:
            if use_dict:
                await vv.ensure_user_dict()
                return await vvapi.audio_query(c, text)
            for w in USER_DICT:
                await vvapi.remove_surface(c, w["surface"])
            try:
                return await vvapi.audio_query(c, text)
            finally:
                await vv.ensure_user_dict()      # 外した語を必ず戻す
    finally:
        await vv.aclose()


def describe(query: dict) -> list[str]:
    lines = [
        f"kana: {query['kana']}",
        f"読み: {vvapi.plain_kana(query['kana'])}",
        f"アクセント句 {len(query['accent_phrases'])}・モーラ {vvapi.count_moras(query)}・ポーズ {vvapi.count_pauses(query)}",
    ]
    for i, ap in enumerate(query["accent_phrases"], 1):
        moras = "".join(m["text"] for m in ap["moras"])
        marks = ("（疑問）" if ap.get("is_interrogative") else "") + ("＋ポーズ" if ap.get("pause_mora") else "")
        lines.append(f"  {i}. {moras}  アクセント {ap['accent']}/{len(ap['moras'])}{marks}")
    lines += [f"{k}: {query[k]}" for k in KEYS]
    return lines


def main() -> int:
    p = argparse.ArgumentParser(description="audio_query の中身を表示する")
    p.add_argument("text")
    p.add_argument("--no-dict", action="store_true", help="ユーザー辞書を外して問い合わせる")
    a = p.parse_args()
    query = asyncio.run(fetch(a.text, use_dict=not a.no_dict))
    print("\n".join(describe(query)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
