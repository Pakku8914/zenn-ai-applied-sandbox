"""答えを知っている Fake（セッション6の fakes.py から、本プロジェクトで使う機能だけを写したもの。検証用）。

mockllm は PDF の中身を読まないので、取り込みの中身（件数・ID・ページ）は mockllm では確かめられない。
RecipeReaderFake は、送られてきた PDF を pypdf で読み、各ページの見出しの行から正しい JSON を作って返す。
セッションのコードは他のセッションを import しない決まりなので、見出しの読み方（pages.py）もここに写してある。
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import re
import unicodedata
from collections.abc import AsyncIterator, Iterable

from pypdf import PdfReader

from kondate.llm import ChatRequest, ChatResult, StreamEvent, Usage

PDF_TOKENS_PER_PAGE = 1600
HEADING = re.compile(r"(R\d{3})調理時間(\d+)分(\d+)人分1人分(\d+)kcal")


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def extract_pages(raw: bytes) -> list[str]:
    return [page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages]


def parse_heading(text: str) -> tuple[str, str, int, int, int] | None:
    """(ID, 料理名, 調理時間, 人数, kcal)。読めなければ None。"""
    t = normalize(text)
    m = HEADING.search(t)
    if m is None:
        return None
    return m[1], t[: m.start()], int(m[2]), int(m[3]), int(m[4])


class RecipeReaderFake:
    name = "recipe-reader-fake"

    def __init__(self, *, broken_calls: Iterable[int] = (), gate_at: int | None = None,
                 gate: asyncio.Event | None = None) -> None:
        self.calls = 0
        self.requests: list[ChatRequest] = []
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
            h = parse_heading(text)
            if h is not None:
                recipe_id, name, minutes, servings, kcal = h
                recipes.append({"id": recipe_id, "name": name, "page": page,
                                "minutes": minutes, "servings": servings, "kcal": kcal})
        text = json.dumps({"recipes": recipes}, ensure_ascii=False)
        return ChatResult(text, [], "end_turn", Usage(usage_in, math.ceil(len(text.encode("utf-8")) / 3)))

    async def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        raise NotImplementedError("取り込みは complete だけを使います")
        yield  # async ジェネレータにするための行（到達しない）
