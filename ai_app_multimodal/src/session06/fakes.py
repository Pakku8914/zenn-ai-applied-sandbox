"""答えを知っている Fake（セッション6・検証用）。

mockllm は PDF の中身を読まないので、「分割 → 統合 → 件数が合うか」は mockllm では確かめられない。
RecipeReaderFake は、送られてきた PDF を pypdf で読み、各ページの見出しの行から正しい JSON を作って返す。
LLM の役を「中身が正しい」側だけ担う差し替え部品で、トークン数とキャッシュは mockllm で測る（役割を分ける）。
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
from collections.abc import AsyncIterator, Iterable

from kondate.llm import ChatRequest, ChatResult, StreamEvent, Usage
from src.session06.documents import PDF_TOKENS_PER_PAGE, extract_pages
from src.session06.pages import parse_heading


class RecipeReaderFake:
    name = "recipe-reader-fake"

    def __init__(
        self,
        *,
        skip_once: Iterable[str] = (),        # 最初に見たときだけ読み落とす ID
        misread_once: dict[str, int] | None = None,  # 最初に見たときだけ調理時間をずらす ID → ずらす分
        broken_calls: Iterable[int] = (),     # 壊れた JSON を返す呼び出しの番号（1始まり）
        gate_at: int | None = None,           # この番号の呼び出しで gate が開くまで待つ（gate が無ければ待ち続ける）
        gate: asyncio.Event | None = None,
    ) -> None:
        self.calls = 0
        self.requests: list[ChatRequest] = []
        self._skip_once = set(skip_once)
        self._misread_once = dict(misread_once or {})
        self._broken = set(broken_calls)
        self._gate_at, self._gate = gate_at, gate

    async def complete(self, req: ChatRequest) -> ChatResult:
        self.calls += 1
        n = self.calls
        self.requests.append(req)
        if n == self._gate_at:
            await (self._gate or asyncio.Event()).wait()
        texts = extract_pages(base64.b64decode(req.messages[0]["content"][0]["source"]["data"]))
        usage_in = len(texts) * PDF_TOKENS_PER_PAGE  # Fake の usage は PDF の分だけの概算
        if n in self._broken:
            return ChatResult('{"recipes": [{"id": "R0', [], "end_turn", Usage(usage_in, 6))
        recipes = []
        for page, text in enumerate(texts, 1):
            h = parse_heading(text, page)
            if h is None:
                continue
            if h.recipe_id in self._skip_once:
                self._skip_once.discard(h.recipe_id)
                continue
            minutes = h.minutes + self._misread_once.pop(h.recipe_id, 0)
            recipes.append({"id": h.recipe_id, "name": h.name, "page": page,
                            "minutes": minutes, "servings": h.servings, "kcal": h.kcal})
        text = json.dumps({"recipes": recipes}, ensure_ascii=False)
        return ChatResult(text, [], "end_turn", Usage(usage_in, math.ceil(len(text.encode("utf-8")) / 3)))

    async def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        raise NotImplementedError("取り込みは complete だけを使います")
        yield  # async ジェネレータにするための行（到達しない）
