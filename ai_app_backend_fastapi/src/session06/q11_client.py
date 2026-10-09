"""後半の練習問題5：末尾を取りこぼしたクライアントが、Last-Event-ID で再送を受けて回答を完成させる。

サーバは done まで送り切ったが、回線の途中で keep 件目より後ろが失われた、という状況を作る
（ASGITransport は応答を最後まで受け取ってから返すので、受け取った列を先頭 keep 件に切り詰めて再現する）。
"""

from __future__ import annotations

import httpx2

from kondate.verifykit import sse_events

from .harness import PROMPT


def merge(received: list[dict], replayed: list[dict]) -> list[dict]:
    """受け取り済みの列に、再送された列をつなぐ。id が受け取り済みの最後以下のものは捨てる（二重に描かない）。"""
    last = int(received[-1]["id"]) if received else 0
    return received + [e for e in replayed if int(e["id"]) > last]


async def read_with_resume(client: httpx2.AsyncClient, keep: int) -> tuple[str, list[str], str]:
    """(つないだ delta の文, 受け取った id の列, 最後のイベント名) を返す。"""
    r = await client.post("/api/chat/stream", json={"message": PROMPT})
    received = [e for e in sse_events(r.text.split("\n")) if e["event"] is not None][:keep]
    message_id = received[0]["data"]["message_id"]
    again = await client.get(f"/api/chat/stream/{message_id}", headers={"Last-Event-ID": received[-1]["id"]})
    replayed = sse_events(again.text.split("\n")) if again.status_code == 200 else []
    events = merge(received, replayed)
    text = "".join(e["data"]["text"] for e in events if e["event"] == "delta")
    return text, [e["id"] for e in events], events[-1]["event"]
