"""検索結果から「引用付きの回答」を作る（セッション11・12の参照実装）。

プロンプトはここで凍結する。プロンプトを変えると合成カセットのキーが変わり
FixtureClient が KeyError になる（＝カセット管理のコストを体験する仕掛け）。
変更したら `python tools/make_fixtures.py` を再実行する。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .models import Hit

SYSTEM_PROMPT = (
    "あなたは社内ヘルプデスクの回答者です。与えられた参考文書だけを根拠に回答してください。\n"
    "制約:\n"
    "1. 参考文書に書かれていないことは答えず、answerable を false にしてください。\n"
    "2. 回答の根拠にした参考文書の chunk_id を citations に列挙してください。\n"
    "3. 出力は次の JSON のみとし、前後に説明を付けないでください。\n"
    '{"answerable": true/false, "answer": "回答本文", "citations": ["chunk_id", ...]}'
)


def build_context(hits: list[Hit], max_chars: int = 2000, use_parent: bool = False) -> str:
    """参考文書のブロックを組み立てる。chunk_id を明示して引用できる形にする。"""
    blocks: list[str] = []
    used = 0
    for h in hits:
        text = h.meta.get("parent_text", h.text) if use_parent else h.text
        block = f"[{h.chunk_id}] {h.meta.get('title', '')}\n{text}"
        if used + len(block) > max_chars:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def build_user_prompt(query: str, hits: list[Hit], max_chars: int = 2000,
                      use_parent: bool = False) -> str:
    return (f"# 質問\n{query}\n\n"
            f"# 参考文書\n{build_context(hits, max_chars=max_chars, use_parent=use_parent)}\n")


@dataclass
class Answer:
    answerable: bool
    text: str
    citations: list[str]
    raw: str


def parse_answer(raw: str) -> Answer:
    """JSON を取り出す。壊れた出力への耐性を持たせる（後処理の題材）。"""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return Answer(False, "", [], raw)
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return Answer(False, "", [], raw)
    return Answer(
        answerable=bool(data.get("answerable", False)),
        text=str(data.get("answer", "")),
        citations=[str(c) for c in data.get("citations", [])],
        raw=raw,
    )


def verify_citations(answer: Answer, hits: list[Hit]) -> tuple[bool, list[str]]:
    """引用された chunk_id が実際にコンテキストに含まれていたかを検証する。

    戻り値: (すべて有効か, 無効な chunk_id の一覧)
    """
    available = {h.chunk_id for h in hits}
    invalid = [c for c in answer.citations if c not in available]
    return (not invalid and bool(answer.citations)), invalid


def answer_with_citations(client, query: str, hits: list[Hit], max_chars: int = 2000,
                          use_parent: bool = False) -> Answer:
    user = build_user_prompt(query, hits, max_chars=max_chars, use_parent=use_parent)
    res = client.complete(SYSTEM_PROMPT, user)
    return parse_answer(res.text)
