#!/usr/bin/env python3
"""セマンティックキャッシュ（セッション6）。

「意味が近い質問なら同じ答えを返す」キャッシュ。ヒット率は上がるが、
**近いが違う質問**に古い答えを返す事故が起きる。

本書のサンドボックスには埋め込みモデルを入れない（読者に追加のモデル取得を
求めないため）。代わりに、人が判定した**類似度と正解ラベルの表**を用意して
閾値の振る舞いだけを再現する。実務ではこの表の代わりに埋め込みモデルの
コサイン類似度が入るが、**閾値を検証せずに決められない**という結論は同じ。

    python src/session06/semantic_cache.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.session06.cache_keys import CacheScope  # noqa: E402


@dataclass(frozen=True)
class Pair:
    """質問のペアと、人が付けた判定。

    similarity  : 埋め込みモデルが出すであろう類似度（ここでは固定値）
    same_answer : 同じ答えを返してよいか（人が資料を見て判断した正解ラベル）
    """

    a: str
    b: str
    similarity: float
    same_answer: bool
    note: str


PAIRS: list[Pair] = [
    Pair("有給休暇の申請はいつまでに出せばよいですか。",
         "有給休暇の申請期限を教えてください。",
         0.96, True, "言い換え。同じ答えでよい"),
    Pair("会議室は連続で何時間まで使えますか。",
         "会議室の連続利用は何時間までですか。",
         0.95, True, "言い換え。同じ答えでよい"),
    Pair("USBメモリは業務で使ってよいですか。",
         "USBメモリは業務で使ってはいけないのですか。",
         0.93, False, "肯定と否定。同じ答えを返すと意味が反転する"),
    Pair("残業の事前申請の上限時間は何時間ですか。",
         "残業の事後申請はできますか。",
         0.88, False, "事前申請と事後申請で別の規程"),
    Pair("交通費の精算の締切を教えてください。",
         "出張旅費はいつまでに精算しますか。",
         0.86, False, "通勤と出張で別の規程・別の締切"),
]


def similarity(a: str, b: str) -> float:
    """あらかじめ用意した類似度を引く。表に無いペアは 0.0（似ていない）とする。"""
    if a == b:
        return 1.0
    for pair in PAIRS:
        if {a, b} == {pair.a, pair.b}:
            return pair.similarity
    return 0.0


@dataclass
class SweepRow:
    threshold: float
    hits: int = 0          # 同じ答えでよいペアを拾えた（うれしいヒット）
    false_hits: int = 0    # 違う答えのペアを同じとみなした（事故）
    misses: int = 0        # 同じ答えでよいのに拾えなかった（もったいない）

    @property
    def false_hit_rate(self) -> float:
        total = self.hits + self.false_hits
        return self.false_hits / total if total else 0.0


def sweep(thresholds: list[float], pairs: list[Pair] | None = None) -> list[SweepRow]:
    """閾値を振って、うれしいヒットと事故の数を数える。"""
    target = pairs if pairs is not None else PAIRS
    rows: list[SweepRow] = []
    for th in thresholds:
        row = SweepRow(threshold=th)
        for pair in target:
            if pair.similarity >= th:
                if pair.same_answer:
                    row.hits += 1
                else:
                    row.false_hits += 1
            elif pair.same_answer:
                row.misses += 1
        rows.append(row)
    return rows


def markdown_table(rows: list[SweepRow]) -> str:
    lines = ["| 閾値 | 同義を拾えた | 誤ヒット | 取りこぼし | 誤ヒット率 |",
             "| --: | --: | --: | --: | --: |"]
    for row in rows:
        lines.append(f"| {row.threshold:.2f} | {row.hits} | {row.false_hits} | "
                     f"{row.misses} | {row.false_hit_rate:.3f} |")
    return "\n".join(lines)


@dataclass
class SemanticCache:
    """意味が近ければ同じ答えを返すキャッシュ。

    スコープ（テナント・可視範囲）が違う相手とは**比較すらしない**。
    完全一致キャッシュと同じ理由で、境界を跨がせてはいけない。
    """

    threshold: float = 0.95
    entries: list[tuple[str, str, str]] = field(default_factory=list)
    hits: int = 0
    misses: int = 0

    def get(self, scope: CacheScope, prompt: str) -> str | None:
        if not scope.cacheable:
            return None
        fingerprint = scope.fingerprint()
        best_text: str | None = None
        best_sim = 0.0
        for stored_fp, stored_prompt, text in self.entries:
            if stored_fp != fingerprint:
                continue
            sim = similarity(prompt, stored_prompt)
            if sim >= self.threshold and sim > best_sim:
                best_text, best_sim = text, sim
        if best_text is None:
            self.misses += 1
            return None
        self.hits += 1
        return best_text

    def put(self, scope: CacheScope, prompt: str, text: str) -> None:
        if not scope.cacheable:
            return
        self.entries.append((scope.fingerprint(), prompt, text))


def main() -> None:
    thresholds = [0.99, 0.96, 0.95, 0.90, 0.85]
    print("=== 閾値を振って誤ヒットを数える（人が判定した 5 ペア）===")
    print(markdown_table(sweep(thresholds)))
    print()
    for pair in PAIRS:
        mark = "同じ答えでよい" if pair.same_answer else "違う答えが必要"
        print(f"類似度 {pair.similarity:.2f} / {mark} / {pair.note}")


if __name__ == "__main__":
    main()
