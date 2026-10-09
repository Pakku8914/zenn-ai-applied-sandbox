"""練習問題3の解答：進捗の SSE を読みながら結果を待つクライアント。接続が切れたら Last-Event-ID で続きから読む。"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx2

from kondate.verifykit import sse_events

from .store import TERMINAL_EVENTS


@dataclass
class FollowResult:
    progress: list[tuple[int, int]] = field(default_factory=list)  # (done, total) を届いた順に
    final: str | None = None  # done / cancelled / error。最後まで届かなければ None
    data: dict | None = None  # 終わりのイベントの中身
    connections: int = 0


async def follow_job(client: httpx2.AsyncClient, job_id: str, headers: dict[str, str], *,
                     max_connections: int = 3) -> FollowResult:
    got = FollowResult()
    last_id: str | None = None
    while got.final is None and got.connections < max_connections:
        got.connections += 1
        h = {**headers, "Last-Event-ID": last_id} if last_id else headers
        try:
            async with client.stream("GET", f"/api/jobs/{job_id}/events", headers=h) as r:
                if r.status_code == 404:
                    return got  # ジョブが無い（他人のジョブ・保存期限切れ）。何度つないでも同じ
                if r.status_code != 200:
                    raise RuntimeError(f"SSE を始められません：{r.status_code}")
                lines: list[str] = []
                async for line in r.aiter_lines():
                    if line != "":
                        lines.append(line)
                        continue
                    for ev in sse_events([*lines, ""]):  # 空行で1件が終わる
                        last_id = ev["id"] or last_id
                        if ev["event"] == "progress":
                            got.progress.append((ev["data"]["done"], ev["data"]["total"]))
                        elif ev["event"] in TERMINAL_EVENTS:
                            got.final, got.data = ev["event"], ev["data"]
                    lines = []
        except httpx2.TransportError:
            continue  # 途中で切れた：last_id の続きからつなぎ直す
    return got
