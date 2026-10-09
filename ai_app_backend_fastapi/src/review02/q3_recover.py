"""問題3の解答：再接続したクライアントが、取りこぼしを Redis の控えから埋め、だめなら DB の履歴を読む。

控え（Redis・TTL 300 秒）は「つなぎ直しのための写し」、DB は「会話の正」。両方を見るのはクライアント側の仕事。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx2

from kondate.verifykit import sse_events


@dataclass(frozen=True)
class Recovered:
    source: str  # replay（控えから続きを受け取った）/ history（DB の発言を読んだ）/ lost（どちらにも無い）
    events: list[dict] = field(default_factory=list)  # replay のとき、Last-Event-ID より後ろのイベント
    message: dict | None = None  # history のとき、保存済みの assistant 発言（id は start の message_id）


async def recover(client: httpx2.AsyncClient, conversation_id: str, message_id: str,
                  last_event_id: int) -> Recovered:
    r = await client.get(f"/api/chat/stream/{message_id}", headers={"Last-Event-ID": str(last_event_id)})
    if r.status_code == 200:  # 控えが done か error まで残っている：続きだけを受け取れば足りる
        return Recovered("replay", [e for e in sse_events(r.text.splitlines()) if e["event"]])
    r.raise_for_status()  # 204 以外の失敗（不正な Last-Event-ID の 422 など）は呼び出し側の誤り
    # 204：控えが無い（期限切れ・途中で切れた・Redis が使えなかった）。保存されていれば DB にある
    h = await client.get(f"/api/conversations/{conversation_id}")
    if h.status_code == 200:
        for m in h.json()["messages"]:
            if m["id"] == message_id:
                return Recovered("history", message=m)
    return Recovered("lost")  # 保存されていない＝この往復は失敗か中断で捨てられた。送り直してもらう
