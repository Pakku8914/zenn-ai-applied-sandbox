"""問題6：DELETE /api/me/data を、2人の利用者・HTTP と WebSocket の両方で作ったデータで確かめる。

    docker compose exec api python -m src.session13.solutions.q6_delete_check
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import httpx2

from kondate.media import media_path
from src.session13.app import app
from src.session13.logmask import masked_handler
from src.session13.testkit import TEXT, Collect, count_files, sandboxed, voice_turn

OUT = Path("out/s13/q6")
START = {"type": "start", "sample_rate": 16000, "store_audio": True}


def counts(d: dict) -> str:
    return " ".join(f"{k}={v}" for k, v in d.items())


async def run() -> list[str]:
    collect = Collect()
    logging.getLogger("src.session13").handlers[:] = [masked_handler(collect)]
    fridge = media_path("fridge.jpg").read_bytes()
    book = media_path("recipe_book.pdf").read_bytes()
    async with app.router.lifespan_context(app):
        with sandboxed(app, OUT) as state:
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
                # 準備：u001 は写真・PDF・音声1回、u002 は写真・音声1回
                for user in ("u001", "u002"):
                    r = await client.post("/api/uploads", files={"file": ("山田家の冷蔵庫.jpg", fridge)},
                                          headers={"x-user-id": user})
                    assert r.status_code == 201, r.text
                    await voice_turn(app, START, user_id=user)
                r = await client.post("/api/documents", files={"file": ("recipe_book.pdf", book)},
                                      headers={"x-user-id": "u001"})
                assert r.status_code == 201, r.text
                # 確かめる：1回目・2回目
                first = (await client.delete("/api/me/data", headers={"x-user-id": "u001"})).json()["deleted"]
                second = (await client.delete("/api/me/data", headers={"x-user-id": "u001"})).json()["deleted"]
            rest = state.data.count("u002")
            rest_usage = sum(1 for r in state.usage.records if r.user_id == "u002")
            files = count_files(state.upload_dir) + count_files(state.voice_dir)
    logs = "\n".join(collect.lines)
    clean = "山田" not in logs and TEXT not in logs
    return [
        f"1回目 u001: {counts(first)}",
        f"2回目 u001: {counts(second)}",
        f"u002 の残り: {counts(rest)} usage={rest_usage}／ファイル {files} 件",
        f"ログにファイル名・文字起こし: {'なし' if clean else 'あり'}",
    ]


if __name__ == "__main__":
    print("\n".join(asyncio.run(run())))
