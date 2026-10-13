"""問題1：同じ冷蔵庫の写真を2回送ったとき、応答キャッシュ・利用量・原本の保持期限・EXIF がそれぞれどう効くか。

    docker compose exec api python -m src.review04.solutions.q1_same_photo
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import anthropic
import anyio
from anthropic import AsyncAnthropic
from ulid import ULID

from kondate.clock import Clock, FixedClock
from kondate.llm import AnthropicProvider, LLMProvider, Usage
from kondate.media import media_path
from kondate.settings import get_settings
from kondate.usage import UsageLog
from src.review04.kit import (
    FRIDGE_PROMPT, FRIDGE_SCHEMA, Counting, PersonalStore, Rejected, ResponseCache, UsageBook,
    accept_image, cache_key, image_findings, scan_fridge, sha256_hex, sum_usage,
)

settings = get_settings()
PREPROCESS = {"max_long_edge": settings.image_max_long_edge, "jpeg_quality": 90}
NO_USAGE = Usage(0, 0)

# (表示, 前の行から進める秒数, 利用者)
EVENTS = [
    ("t+0分", 0, "u001"),
    ("t+10分", 600, "u001"),
    ("t+10分", 0, "u002"),
    ("t+24時間", 24 * 3600 - 600, "u001"),
]


@dataclass(frozen=True)
class ScanResult:
    status: int
    x_cache: str
    usage: Usage
    upload_id: str | None     # 台帳に預けた原本の ID（受け付けなかったら None）
    sent: bytes | None        # LLM に送った画像（送っていなければ None）


class Desk:
    """本問の窓口：原本を台帳に預け（S13）、応答キャッシュを調べ（S14）、外れたら前処理（S3）→ 読み取り（S4）。"""

    def __init__(self, clock: Clock, llm: LLMProvider) -> None:
        self.llm = llm
        self.store = PersonalStore(clock)
        self.cache = ResponseCache(clock)              # 256件・24時間（セッション14と同じ）
        self.book = UsageBook(UsageLog(clock))

    def key(self, user: str, raw: bytes) -> str:
        return cache_key(scope=user, kind="fridge_scan", content_sha256=sha256_hex(raw), preprocess=PREPROCESS,
                         prompt=FRIDGE_PROMPT, system=None, model=settings.llm_model, schema=FRIDGE_SCHEMA)

    def keep_original(self, user: str, raw: bytes) -> str:
        return self.store.add("upload", f"up_{ULID()}", user, data=raw).item_id   # 24時間で期限切れ

    async def scan(self, user: str, raw: bytes) -> ScanResult:
        key = self.key(user, raw)
        if self.cache.get(key) is not None:
            # 同じバイト列が前に受付と読み取りを通っているので、Pillow を通さずに預けてよい
            self.book.count_lookup(user, hit=True)
            return ScanResult(200, "hit", NO_USAGE, self.keep_original(user, raw), None)
        self.book.count_lookup(user, hit=False)
        try:
            prepared = await anyio.to_thread.run_sync(accept_image, raw, PREPROCESS["max_long_edge"],
                                                      PREPROCESS["jpeg_quality"])
        except Rejected as e:
            return ScanResult(e.status, "miss", NO_USAGE, None, None)   # 受け付けないものは預からない
        upload_id = self.keep_original(user, raw)
        used: list[Usage] = []
        try:
            scan = await scan_fridge(self.llm, prepared.data, used)
        except anthropic.APIError:
            return ScanResult(503, "miss", sum_usage(used), upload_id, prepared.data)
        finally:
            if used:                                   # 失敗した試行のトークンも記録する（S14）
                self.book.add_llm(user, settings.llm_model, sum_usage(used))
        if scan is None:
            return ScanResult(502, "miss", sum_usage(used), upload_id, prepared.data)   # 失敗はキャッシュしない
        value = {"ingredients": [i.model_dump() for i in scan.ingredients], "image": prepared.info()}
        self.cache.put(key, user, value, sum_usage(used))
        return ScanResult(200, "miss", sum_usage(used), upload_id, prepared.data)


def describe(desk: Desk, user: str, r: ScanResult) -> str:
    sent = "送っていない" if r.sent is None else ("EXIF あり" if image_findings(r.sent)["exif"] else "EXIF なし")
    held = desk.store.get(user, r.upload_id)
    gps = "GPS あり" if image_findings(held.data)["gps"] else "GPS なし"
    return f"{r.x_cache}・usage {r.usage.input_tokens}/{r.usage.output_tokens}・送った画像 {sent}・預けた原本 {gps}"


async def run_events(desk: Desk, clock: FixedClock, raw: bytes, llm: Counting) -> list[str]:
    lines = []
    for label, advance, user in EVENTS:
        clock.advance(advance)
        r = await desk.scan(user, raw)
        lines.append(f"{label} {user} → {describe(desk, user, r)}・LLM 累計 {llm.calls} 回")
    return lines


def usage_line(desk: Desk, user: str) -> str:
    s = desk.book.summary(user)
    return (f"GET /api/usage（{user}） → llm {s['llm']['input_tokens']}/{s['llm']['output_tokens']}"
            f"・応答キャッシュ 命中 {s['response_cache']['hits']}／外れ {s['response_cache']['misses']}")


async def scenario() -> list[str]:
    raw = media_path("fridge.jpg").read_bytes()
    clock = FixedClock()
    client = AsyncAnthropic()   # 接続先は ANTHROPIC_BASE_URL（既定は mockllm）
    try:
        llm = Counting(AnthropicProvider(client))
        desk = Desk(clock, llm)
        lines = await run_events(desk, clock, raw, llm)
    finally:
        await client.close()
    originals = [h for h in desk.store.of_user("u001") if h.kind == "upload"]
    alive = [h for h in originals if desk.store.get("u001", h.item_id) is not None]
    swept = desk.store.sweep()
    lines.append(f"u001 の原本：預けた {len(originals)} 件・取り出せる {len(alive)} 件 → 掃除で {swept['uploads']} 件を削除")
    lines += [usage_line(desk, "u001"), usage_line(desk, "u002")]
    lines.append(f"応答キャッシュの件数：{len(desk.cache)}")
    return lines


def main() -> None:
    print("\n".join(asyncio.run(scenario())))


if __name__ == "__main__":
    main()
