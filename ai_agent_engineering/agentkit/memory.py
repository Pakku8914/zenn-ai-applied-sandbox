"""メモリ（セッション7の参照実装）。

`ShortTermMemory` は既定で**何も圧縮しない**。コンテキストが溢れる現象に
読者が実際にぶつかることが学びの核なので、この「欠け」は直さない。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

MEMORY_DIR = Path(__file__).resolve().parent.parent / "traces" / "memory"

# 圧縮しても必ず残す情報の目印（選択的保持で使う）
CONSTRAINT_PATTERNS = (
    re.compile(r"必ず[^。]*。"),
    re.compile(r"[^。]*してはいけない[^。]*。"),
    re.compile(r"[^。]*以上[^。]*承認[^。]*。"),
    re.compile(r"上限[^。]*。"),
    re.compile(r"期限[^。]*。"),
)


def approx_tokens(text: str) -> int:
    """トークン数の決定的な近似（日本語は3文字で1トークン相当と見なす）。

    実測ではないので、本文で「実測値」と呼ばないこと。相対比較にのみ使う。
    """
    return max(len(text) // 3, 1)


@dataclass
class ShortTermMemory:
    """会話履歴に相当する短期メモリ。"""

    items: list[str] = field(default_factory=list)
    max_tokens: int = 8_000

    def add(self, text: str) -> None:
        self.items.append(text)

    def total_tokens(self) -> int:
        return sum(approx_tokens(t) for t in self.items)

    def overflowing(self) -> bool:
        return self.total_tokens() > self.max_tokens

    def render(self) -> str:
        return "\n".join(self.items)

    # --- 圧縮方式（セッション7で読者が比較する）--------------------------
    def truncate_oldest(self) -> "ShortTermMemory":
        """古いものから捨てる。最初の指示が消えるという致命的な弱点がある。"""
        kept = list(self.items)
        while kept and sum(approx_tokens(t) for t in kept) > self.max_tokens:
            kept.pop(0)
        return ShortTermMemory(items=kept, max_tokens=self.max_tokens)

    def keep_constraints(self) -> "ShortTermMemory":
        """制約らしい文だけを必ず残し、それ以外を古い順に捨てる（選択的保持）。"""
        constraints = [t for t in self.items if extract_constraints(t)]
        others = [t for t in self.items if t not in constraints]
        kept = list(others)
        budget = self.max_tokens - sum(approx_tokens(t) for t in constraints)
        while kept and sum(approx_tokens(t) for t in kept) > max(budget, 0):
            kept.pop(0)
        return ShortTermMemory(items=constraints + kept, max_tokens=self.max_tokens)


def extract_constraints(text: str) -> list[str]:
    """制約らしい文を取り出す。圧縮の保持率を測るのに使う。"""
    found: list[str] = []
    for pattern in CONSTRAINT_PATTERNS:
        found.extend(m.group(0) for m in pattern.finditer(text))
    return found


class LongTermMemory:
    """外部保存された長期メモリ。キーワード一致で引く最小実装。

    ベクトル検索で引く設計は `rag_search_engineering` の範囲なので、
    本書はインターフェースだけ揃えて中身は素朴に保つ。
    """

    def __init__(self, name: str = "default") -> None:
        self.path = MEMORY_DIR / f"{name}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def remember(self, key: str, value: str, importance: int = 1) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, "value": value, "importance": importance},
                               ensure_ascii=False) + "\n")

    def recall(self, query: str, limit: int = 3) -> list[dict]:
        if not self.path.exists():
            return []
        rows = [json.loads(line) for line in self.path.open(encoding="utf-8") if line.strip()]
        scored = [(sum(1 for w in set(query) if w in r["key"] + r["value"]), r) for r in rows]
        scored.sort(key=lambda t: (-t[0], -t[1]["importance"]))
        return [r for score, r in scored[:limit] if score > 0]

    def forget_all(self) -> None:
        self.path.unlink(missing_ok=True)
