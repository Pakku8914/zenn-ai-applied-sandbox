"""問題4：指示文を変えたあとの回帰テスト（S12）を、どの経路で回すかで結果が変わる（S14 の応答キャッシュ・S7 の 409）。

    docker compose exec api python -m src.review04.solutions.q4_eval_cache

LLM は「指示文で答えが変わるモデル」の代わり（PromptAwareModel）。課金なしで決定的に動く。
"""

from __future__ import annotations

import asyncio
import base64
import copy
import json
from collections.abc import AsyncIterator, Awaitable, Callable

from kondate.clock import FixedClock
from kondate.llm import ChatRequest, ChatResult, LLMProvider, StreamEvent, Usage
from kondate.media import media_path
from kondate.settings import get_settings
from src.review04.kit import (
    MSG_DUPLICATE, RECEIPT_PROMPT, RECEIPT_SCHEMA, RULES, Gold, ReceiptRead, ResponseCache,
    cache_key, find_regressions, score_case, sha256_hex, summarize,
)

settings = get_settings()
PROMPT_V1 = RECEIPT_PROMPT
PROMPT_V2 = RECEIPT_PROMPT + "金額は税込みで書いてください。"
PREPROCESS = {"max_long_edge": settings.image_max_long_edge, "jpeg_quality": 90}
EXTRACTION_RULES = {k: r for k, r in RULES.items() if k.startswith("extraction.")}
METRICS = ("precision", "recall", "field_accuracy", "exact_match_rate")
EVAL_USER = "u001"

# receipt.png に描いた内容（セッション12の正解データと同じ中身）
GOOD = {
    "store": "こんだてマート", "purchased_at": "2026-10-01", "total": 1072,
    "items": [
        {"name": "鶏むね肉", "quantity": 1, "price": 398},
        {"name": "キャベツ", "quantity": 1, "price": 198},
        {"name": "卵（10個入り）", "quantity": 1, "price": 248},
        {"name": "牛乳", "quantity": 1, "price": 228},
    ],
}
MISREAD = copy.deepcopy(GOOD)
MISREAD["items"][3]["price"] = 282   # v2 の指示文では、牛乳の 228 を 282 と読み違える
GOLD = Gold("receipt.png", tuple(GOOD["items"]),
            {"store": GOOD["store"], "purchased_at": GOOD["purchased_at"], "total": GOOD["total"]})


class PromptAwareModel:
    """指示文で答えが変わる「モデル」の代わり。v1 には正しく、それ以外には牛乳を読み違えて答える。"""

    name = "prompt-aware-fake"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, req: ChatRequest) -> ChatResult:
        self.calls += 1
        prompt = req.messages[0]["content"][-1]["text"]
        answer = GOOD if prompt == PROMPT_V1 else MISREAD
        return ChatResult(json.dumps(answer, ensure_ascii=False), [], "end_turn", Usage(778, 104))

    async def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        raise NotImplementedError("この問題は complete だけを使います")
        yield


async def read(llm: LLMProvider, raw: bytes, prompt: str) -> dict:
    """読み取りのパイプライン（S7 の read_receipt を1回だけにしたもの）→ 採点できる形 {items, header}。"""
    block = {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": base64.standard_b64encode(raw).decode("ascii")}}
    req = ChatRequest(messages=[{"role": "user", "content": [block, {"type": "text", "text": prompt}]}],
                      output_schema=RECEIPT_SCHEMA, max_tokens=settings.llm_max_tokens)
    r = ReceiptRead.model_validate_json((await llm.complete(req)).text)
    return {"items": [{"name": i.name, "quantity": i.quantity, "price": i.price} for i in r.items],
            "header": {"store": r.store, "purchased_at": r.purchased_at, "total": r.total}}


class CachedReader:
    """応答キャッシュ（S14）を前に置いた読み取り。キーの作り方だけを差し替えられる。"""

    def __init__(self, key_of: Callable[[bytes, str], str]) -> None:
        self.key_of = key_of
        self.cache = ResponseCache(FixedClock())

    async def read(self, llm: LLMProvider, raw: bytes, prompt: str) -> tuple[dict, str]:
        key = self.key_of(raw, prompt)
        if (hit := self.cache.get(key)) is not None:
            return hit.value, "hit"
        value = await read(llm, raw, prompt)
        self.cache.put(key, EVAL_USER, value, Usage(778, 104))
        return value, "miss"


def scoped_key(raw: bytes, prompt: str) -> str:
    """セッション14のキー：結果を変えうる材料をすべて入れる。"""
    return cache_key(scope=EVAL_USER, kind="receipt_import", content_sha256=sha256_hex(raw), preprocess=PREPROCESS,
                     prompt=prompt, system=None, model=settings.llm_model, schema=RECEIPT_SCHEMA)


def content_only_key(raw: bytes, prompt: str) -> str:
    """悪い例：中身の SHA256 だけ（指示文を変えても同じキー）。"""
    return sha256_hex(raw)


class ReceiptWindow:
    """取り込みの窓口（S7）。同じ利用者×同じ SHA256 は、LLM の前に 409 で断る。"""

    def __init__(self) -> None:
        self.seen: set[tuple[str, str]] = set()

    async def import_(self, llm: LLMProvider, raw: bytes, prompt: str) -> tuple[dict, str]:
        key = (EVAL_USER, sha256_hex(raw))
        if key in self.seen:
            return {"items": [], "header": {}}, f"409 duplicate「{MSG_DUPLICATE}」"   # 予測0件として採点する
        value = await read(llm, raw, prompt)
        self.seen.add(key)
        return value, "201"


def report(summary: dict) -> dict:
    return {"deterministic": {f"extraction.{k}": summary[k] for k in METRICS}}


def metrics_text(summary: dict) -> str:
    return (f"適合率 {summary['precision']}・再現率 {summary['recall']}"
            f"・項目一致率 {summary['field_accuracy']}・完全一致率 {summary['exact_match_rate']}")


async def evaluate() -> list[str]:
    model = PromptAwareModel()
    raw = media_path("receipt.png").read_bytes()
    base = summarize([score_case("基準", GOLD, await read(model, raw, PROMPT_V1))])
    baseline = report(base)
    lines = [f"基準（指示文 v1・直接） → {metrics_text(base)}"]

    # 変更の前に、いつもどおり v1 を各経路へ1回ずつ流しておく（キャッシュが温まり、窓口は取り込み済みになる）
    scoped, content, window = CachedReader(scoped_key), CachedReader(content_only_key), ReceiptWindow()
    for path in (scoped.read, content.read, window.import_):
        await path(model, raw, PROMPT_V1)

    async def direct(llm: LLMProvider, raw: bytes, prompt: str) -> tuple[dict, str]:
        return await read(llm, raw, prompt), "読み取り"

    paths: list[tuple[str, Callable[..., Awaitable[tuple[dict, str]]]]] = [
        ("(a) 直接（キャッシュを通さない）", direct),
        ("(b) 応答キャッシュ（S14 のキー）", scoped.read),
        ("(c) 応答キャッシュ（中身の SHA256 だけのキー）", content.read),
        ("(d) 取り込みの窓口（S7）", window.import_),
    ]
    details: list[str] = []
    for label, path in paths:
        before = model.calls
        pred, how = await path(model, raw, PROMPT_V2)       # 指示文を v2 に変えたあとの評価
        score = score_case(label, GOLD, pred)
        summary = summarize([score])
        found = find_regressions(report(summary), baseline, EXTRACTION_RULES)
        verdict = f"回帰 {len(found)} 件" if found else "回帰なし"
        lines.append(f"{label} → {how}・LLM {model.calls - before} 回 → {metrics_text(summary)} → {verdict}")
        if label.startswith("(a)"):
            details += [f"(a) の回帰：{f}" for f in found] + [f"(a) の誤り：{e}" for e in score.errors]
    return lines + details


def main() -> None:
    print("\n".join(asyncio.run(evaluate())))


if __name__ == "__main__":
    main()
