"""問題5：DELETE /api/me/data（S13）に、応答キャッシュの forget と帳簿の横の合計（S14）を足す。

    docker compose exec api python -m src.review04.solutions.q5_delete_all

問題1の窓口（Desk）と出来事（EVENTS）をそのまま使う。LLM は mockllm。
"""

from __future__ import annotations

import asyncio

from anthropic import AsyncAnthropic

from kondate.clock import FixedClock
from kondate.llm import AnthropicProvider
from kondate.media import media_path
from src.review04.kit import Counting, UsageBook, forget_usage
from src.review04.solutions.q1_same_photo import Desk, run_events, usage_line


class ForgettingBook(UsageBook):
    """利用者の記録と、横に持つ合計（キャッシュの2項目・命中と外れの数）を一緒に消せる帳簿。"""

    def forget(self, user_id: str) -> int:
        removed = forget_usage(self.log, user_id)
        self._cache_tokens.pop(user_id, None)
        self._lookups.pop(user_id, None)
        return removed


def delete_s13(desk: Desk, user: str) -> dict[str, int]:
    """セッション13のままの削除：台帳と利用記録（UsageLog の行）だけを消す。"""
    deleted = desk.store.delete_user(user)
    deleted["usage"] = forget_usage(desk.book.log, user)
    return deleted


def delete_all(desk: Desk, user: str) -> tuple[dict[str, int], int]:
    """本問の削除：応答の形（API契約）は変えず、応答キャッシュから消した件数は別に返す（ログに残す用）。"""
    deleted = desk.store.delete_user(user)
    deleted["usage"] = desk.book.forget(user)
    return deleted, desk.cache.forget(user)


def counts(deleted: dict[str, int]) -> str:
    return "・".join(f"{k} {v}" for k, v in deleted.items())


async def resend(desk: Desk, llm: Counting, raw: bytes) -> str:
    before = llm.calls
    r = await desk.scan("u001", raw)
    return f"{r.x_cache}・LLM {llm.calls - before} 回"


async def scenario() -> list[str]:
    raw = media_path("fridge.jpg").read_bytes()
    lines: list[str] = []
    client = AsyncAnthropic()
    try:
        llm = Counting(AnthropicProvider(client))

        clock = FixedClock()
        desk = Desk(clock, llm)
        await run_events(desk, clock, raw, llm)                      # 問題1と同じ4件（いまは t+24時間）
        lines.append(f"(1) セッション13のままの削除 → {counts(delete_s13(desk, 'u001'))}")
        lines.append(f"(1) 削除の直後の {usage_line(desk, 'u001')}")
        lines.append(f"(1) 同じ写真をもう一度 → {await resend(desk, llm, raw)}")

        clock = FixedClock()
        desk = Desk(clock, llm)
        desk.book = ForgettingBook(desk.book.log)
        await run_events(desk, clock, raw, llm)
        deleted, forgotten = delete_all(desk, "u001")
        lines.append(f"(2) 応答キャッシュと帳簿まで消す削除 → {counts(deleted)} ／ 応答キャッシュから {forgotten} 件")
        deleted, forgotten = delete_all(desk, "u001")
        lines.append(f"(2) もう一度削除 → {counts(deleted)} ／ 応答キャッシュから {forgotten} 件")
        lines.append(f"(2) 削除の直後の {usage_line(desk, 'u001')}")
        lines.append(f"(2) 同じ写真をもう一度 → {await resend(desk, llm, raw)}")
        kept = desk.cache.get(desk.key("u002", raw)) is not None
        lines.append(f"(2) u002 の結果 → 応答キャッシュ {'残っている' if kept else '消えた'}・{usage_line(desk, 'u002')}")
    finally:
        await client.close()
    return lines


def main() -> None:
    print("\n".join(asyncio.run(scenario())))


if __name__ == "__main__":
    main()
