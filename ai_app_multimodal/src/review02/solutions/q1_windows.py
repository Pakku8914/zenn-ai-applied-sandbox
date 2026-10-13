"""問題1：同じレシートを3つの窓口（uploads・documents・receipts）に送り、返り方の違いを確かめる。

    docker compose exec api python -m src.review02.solutions.q1_windows
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import date

import anyio
import httpx2
from anthropic import AsyncAnthropic
from ulid import ULID

from kondate.clock import FixedClock
from kondate.llm import AnthropicProvider, LLMProvider
from kondate.settings import get_settings
from src.review02 import samples
from src.review02.kit import (
    MSG_DUPLICATE, MSG_TOO_LARGE, RCP_MSG_INVALID_OUTPUT, RCP_MSG_UPSTREAM, UPLOAD_MAX_BYTES,
    InvalidOutput, Outcome, Rejected, UpstreamUnavailable, accept_receipt, check_receipt,
    compare_with_text, failure, inspect_pdf, inspect_upload, parse_receipt_text, read_receipt,
)

MOCK = get_settings().mockllm_url


def upload(raw: bytes) -> Outcome:
    """セッション2：中身を確かめるだけ。同じ内容でも、送られるたびに新しい ID を振る。"""
    if len(raw) > UPLOAD_MAX_BYTES:
        return failure(413, "too_large", MSG_TOO_LARGE)
    try:
        kind, _ = inspect_upload(raw)
    except Rejected as e:
        return failure(e.status, e.type, e.message)
    return Outcome(201, {"upload_id": f"up_{ULID()}", "kind": kind})


class Documents:
    """セッション5：同じ利用者×同じ SHA256 なら、調べ直さずに同じ document_id を 200 で返す。"""

    def __init__(self) -> None:
        self.ids: dict[tuple[str, str], tuple[str, int]] = {}  # (利用者, SHA256) → (document_id, ページ数)

    def register(self, user: str, raw: bytes) -> Outcome:
        if len(raw) > UPLOAD_MAX_BYTES:
            return failure(413, "too_large", MSG_TOO_LARGE)
        key = (user, hashlib.sha256(raw).hexdigest())
        if key not in self.ids:
            try:
                pages, _ = inspect_pdf(raw)
            except Rejected as e:
                return failure(e.status, e.type, e.message)
            self.ids[key] = (f"doc_{ULID()}", pages)
            status = 201
        else:
            status = 200
        doc_id, pages = self.ids[key]
        return Outcome(status, {"document_id": doc_id, "pages": pages})


class Receipts:
    """セッション7：同じ利用者×同じ SHA256 なら、LLM を呼ぶ前に 409 で断る。"""

    def __init__(self, today: date) -> None:
        self.today = today
        self.ids: dict[tuple[str, str], str] = {}  # (利用者, SHA256) → receipt_id

    async def import_(self, user: str, raw: bytes, llm: LLMProvider) -> Outcome:
        if len(raw) > UPLOAD_MAX_BYTES:
            return failure(413, "too_large", MSG_TOO_LARGE)
        key = (user, hashlib.sha256(raw).hexdigest())
        if key in self.ids:
            return failure(409, "duplicate", MSG_DUPLICATE)  # 料金がかかる前に断る
        try:
            accepted = await anyio.to_thread.run_sync(accept_receipt, raw)
        except Rejected as e:
            return failure(e.status, e.type, e.message)
        try:
            result = await read_receipt(llm, accepted.kind, accepted.data)
        except UpstreamUnavailable:
            return failure(503, "upstream_unavailable", RCP_MSG_UPSTREAM)
        except InvalidOutput as e:
            return failure(502, "invalid_output", RCP_MSG_INVALID_OUTPUT, e.usage)
        issues = check_receipt(result.receipt, self.today)
        if (text := parse_receipt_text(accepted.pdf_text)) is not None:
            issues += compare_with_text(result.receipt, text)
        if key in self.ids:  # 読み取っている間に、同じレシートが別の依頼で取り込まれた
            return failure(409, "duplicate", MSG_DUPLICATE)
        self.ids[key] = f"rcp_{ULID()}"  # 取り込めたときだけ覚える（失敗した取り込みは数えない）
        return Outcome(201, {
            "receipt_id": self.ids[key], "source": accepted.kind, **result.receipt.model_dump(),
            "needs_review": bool(issues), "issues": issues, "text_checked": text is not None,
        }, result.usage)


def error_text(o: Outcome) -> str:
    return f"{o.status} {o.body['error']['type']}「{o.body['error']['message']}」"


def show(window: str, o: Outcome) -> str:
    if o.status >= 400:
        return error_text(o) if window != "uploads" else f"{o.status} {o.body['error']['type']}"
    if window == "uploads":
        return f"{o.status} {o.body['kind']}"
    if window == "documents":
        return f"{o.status} {o.body['pages']}ページ"
    return f"{o.status} {o.body['source']}・要確認 {len(o.body['issues'])} 件・usage {o.usage.input_tokens}/{o.usage.output_tokens}"


async def run() -> None:
    async with httpx2.AsyncClient(base_url=MOCK) as c:
        await c.post("/_mock/reset")
    client = AsyncAnthropic()
    llm = AnthropicProvider(client)
    docs, receipts = Documents(), Receipts(FixedClock().now().date())  # 2026-10-02
    upload_ids: list[str] = []
    png, pdf = samples.receipt_png(), samples.receipt_pdf()
    cases = [("u001", "receipt.png", png), ("u001", "receipt.pdf", pdf), ("u001", "receipt.png（2回目）", png),
             ("u001", "receipt.pdf（2回目）", pdf), ("u002", "receipt.png", png)]
    try:
        for user, label, raw in cases:
            u = upload(raw)
            upload_ids.append(u.body.get("upload_id", ""))
            d = docs.register(user, raw)
            r = await receipts.import_(user, raw, llm)
            print(f"{user} {label} → uploads {show('uploads', u)} ／ documents {show('documents', d)} ／ receipts {show('receipts', r)}")
    finally:
        await client.close()
    print(f"upload_id: {len(upload_ids)} 件・{'すべて別' if len(set(upload_ids)) == len(upload_ids) else '重複あり'}")
    print(f"document_id: {len({doc_id for doc_id, _ in docs.ids.values()})} 種類")
    async with httpx2.AsyncClient(base_url=MOCK) as c:
        by_scenario = (await c.get("/_mock/stats")).json()["by_scenario"]
    print(f"mockllm のシナリオ: {'・'.join(f'{k}×{v}' for k, v in sorted(by_scenario.items()))}")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
