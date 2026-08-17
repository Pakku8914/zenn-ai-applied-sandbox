#!/usr/bin/env python3
"""セッション11：コンテキスト構成と後処理（引用検証・回答不能）の道具箱。

`ragkit.answer` の API 契約（build_context / parse_answer / verify_citations /
answer_with_citations）は変更しない。ここに置くのは、その周りに足す
「予算・並び順・後処理」の層である。

APIキーは不要。生成は StubClient / FixtureClient（合成カセット）で代用する。
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.answer import (  # noqa: E402
    Answer,
    answer_with_citations,
    build_context,
    verify_citations,
)
from ragkit.models import Hit, LLMResponse  # noqa: E402

# 後処理で落としたときに利用者へ返す文面。回答を作らないことを明言する
FALLBACK_TEXT = (
    "この質問に答えられる根拠が参考文書の中に見つかりませんでした。担当窓口へお問い合わせください。"
)

# 後処理の判定（verdict）。ok 以外はすべて「利用者にそのまま出さない」
OK = "ok"
ABSTAINED = "abstained"                  # モデル自身が回答不能と答えた（正しい棄却）
LOW_EVIDENCE = "low_evidence"            # 検索スコアが閾値未満（根拠が弱い）
UNPARSABLE = "unparsable"                # JSON として読めなかった
NO_CITATION = "no_citation"              # 引用が1件も無い
INVALID_CITATION = "invalid_citation"    # コンテキストに無い chunk_id を引用した
VERDICTS = (OK, ABSTAINED, LOW_EVIDENCE, UNPARSABLE, NO_CITATION, INVALID_CITATION)


# --- コンテキストの組み立て -------------------------------------------------


def block_of(hit: Hit, use_parent: bool = False) -> str:
    """ragkit.answer.build_context と同じ書式で1ブロックを作る。"""
    text = hit.meta.get("parent_text", hit.text) if use_parent else hit.text
    return f"[{hit.chunk_id}] {hit.meta.get('title', '')}\n{text}"


def pack_context(
    hits: list[Hit],
    budget: int = 2000,
    use_parent: bool = False,
    sep: str = "\n\n",
    stop_on_overflow: bool = True,
) -> tuple[str, list[str]]:
    """区切り文字も予算に数えてコンテキストを組む。

    戻り値は (コンテキスト文字列, 収録した chunk_id の一覧)。
    len(コンテキスト) は必ず budget 以下になる。

    stop_on_overflow=True  : 入らない候補が出たら打ち切る（順位に忠実）
    stop_on_overflow=False : 入らない候補を飛ばして下位を詰める（予算を使い切る）
    """
    parts: list[str] = []
    ids: list[str] = []
    used = 0
    for h in hits:
        block = block_of(h, use_parent)
        cost = len(block) + (len(sep) if parts else 0)
        if used + cost > budget:
            if stop_on_overflow:
                break
            continue
        parts.append(block)
        ids.append(h.chunk_id)
        used += cost
    return sep.join(parts), ids


def context_hits(hits: list[Hit], max_chars: int = 2000, use_parent: bool = False) -> list[Hit]:
    """実際にコンテキストへ入った Hit だけを返す（引用検証の母集合）。"""
    ctx = build_context(hits, max_chars=max_chars, use_parent=use_parent)
    return [h for h in hits if f"[{h.chunk_id}]" in ctx]


def dedupe_by_doc(hits: list[Hit], per_doc: int = 1) -> list[Hit]:
    """同じ文書から来たチャンクを上位 per_doc 件に畳み込む（順位は保つ）。"""
    seen: dict[str, int] = {}
    out: list[Hit] = []
    for h in hits:
        n = seen.get(h.doc_id, 0)
        if n >= per_doc:
            continue
        seen[h.doc_id] = n + 1
        out.append(h)
    return out


STRATEGIES = ("score", "reversed", "edges")


def reorder(hits: list[Hit], strategy: str = "score") -> list[Hit]:
    """コンテキストの並び順を変える。件数と集合は変えない（並びだけを変える）。

    score    : 検索スコア順（そのまま）
    reversed : 逆順（重要なものを末尾へ）
    edges    : 重要なものを両端へ（lost in the middle への素朴な対処）
    """
    ordered = list(hits)
    if strategy == "score":
        return ordered
    if strategy == "reversed":
        return list(reversed(ordered))
    if strategy == "edges":
        head = ordered[0::2]
        tail = ordered[1::2]
        return head + list(reversed(tail))
    raise ValueError(f"unknown strategy: {strategy} (available: {list(STRATEGIES)})")


# --- 後処理（引用の検証と回答不能の判定）------------------------------------


@dataclass(frozen=True)
class Review:
    """後処理の判定結果。落とした理由をログに残せるようにしている。"""

    verdict: str
    top_score: float
    invalid: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.verdict == OK


def review_answer(
    answer: Answer,
    hits: list[Hit],
    min_score: float | None = None,
    require_citation: bool = True,
) -> Review:
    """生成された回答を検査する。**判定の順序が結果を決める**ので順序も設計対象。

    1. モデルが自ら回答不能と言った → 正しい棄却（欠陥ではない）
       ただし本文が空なら JSON を読めなかった疑いとして unparsable に分ける
    2. 検索スコアが閾値未満 → 根拠が弱い（low_evidence）
    3. 引用が無い → no_citation
    4. 引用がコンテキストに無い → invalid_citation
    """
    top = hits[0].score if hits else float("-inf")
    if not answer.answerable:
        return Review(ABSTAINED if answer.text.strip() else UNPARSABLE, top)
    if min_score is not None and (not hits or top < min_score):
        return Review(LOW_EVIDENCE, top)
    if require_citation and not answer.citations:
        return Review(NO_CITATION, top)
    _, invalid = verify_citations(answer, hits)
    if invalid:
        return Review(INVALID_CITATION, top, tuple(invalid))
    return Review(OK, top)


def guarded_answer(
    client,
    query: str,
    hits: list[Hit],
    max_chars: int = 2000,
    use_parent: bool = False,
    min_score: float | None = None,
    strict_citations: bool = False,
    fallback: str = FALLBACK_TEXT,
) -> tuple[Answer, Review]:
    """生成 → 検査 → 落ちたら定型文に差し替える、までを1本にした関数。

    strict_citations=True にすると、引用の母集合を「実際にコンテキストへ入った候補」に
    絞る（渡した候補すべてではなく）。厳しくなる方向にしか動かない。
    """
    answer = answer_with_citations(client, query, hits, max_chars=max_chars, use_parent=use_parent)
    pool = context_hits(hits, max_chars=max_chars, use_parent=use_parent) if strict_citations else hits
    review = review_answer(answer, pool, min_score=min_score)
    if review.accepted:
        return answer, review
    return Answer(False, fallback, [], answer.raw), review


def abstain_sweep(rows: list[tuple[float, bool]], thresholds) -> list[dict]:
    """スコア閾値を振って、誤棄却と誤受容の件数を数える。

    rows: [(上位1件のスコア, 本当は回答可能か), ...]
    誤棄却 = 回答可能なのに棄却した件数 / 誤受容 = 回答不能なのに答えた件数
    閾値を上げると誤棄却は増え、誤受容は減る（この単調性は構造的に保証される）。
    """
    out: list[dict] = []
    for t in thresholds:
        abstained = [(s, gold) for s, gold in rows if s < t]
        out.append(
            {
                "threshold": t,
                "abstained": len(abstained),
                "false_abstain": sum(1 for _, gold in abstained if gold),
                "false_accept": sum(1 for s, gold in rows if not gold and not s < t),
            }
        )
    return out


def to_log(query: str, review: Review, answer: Answer, context_ids: list[str]) -> dict:
    """1リクエスト分の監査ログ。あとから「なぜこの回答になったか」を再現するための項目。"""
    return {
        "query": query,
        "verdict": review.verdict,
        "top_score": review.top_score if math.isfinite(review.top_score) else None,
        "context_ids": list(context_ids),
        "citations": list(answer.citations),
        "invalid_citations": list(review.invalid),
    }


# --- 章の説明を揺らさないための合成データ／スタブ ----------------------------


def demo_hits(sizes: list[int], title: str = "T") -> list[Hit]:
    """ブロック長を指定して合成 Hit を作る。

    本文の長さは、build_context が付ける前置き（`[chunk_id] title\\n`）の分を
    引いて逆算する。こうしておくと「1ブロック = 指定した文字数」がぴったり成立する。
    """
    out: list[Hit] = []
    for i, size in enumerate(sizes, start=1):
        chunk_id = f"DOC-{i:04d}#001"
        prefix = f"[{chunk_id}] {title}\n"
        if size < len(prefix):
            raise ValueError(f"ブロック長は {len(prefix)} 以上にしてください（指定: {size}）")
        out.append(
            Hit(chunk_id, f"DOC-{i:04d}", 1.0 / i, "あ" * (size - len(prefix)), {"title": title})
        )
    return out


class MiddleBlindClient:
    """コンテキストの中央を読み落とす決定的なスタブ。

    これは lost in the middle の**戯画**であって、実 LLM の挙動を測る道具ではない。
    プロンプトの先頭 head 文字と末尾 tail 文字だけを見て、その範囲に根拠の
    chunk_id があれば引用付きで答え、無ければ回答不能と答える。
    「並べ替えが何を変えるのか」という機構だけを、揺れなく観察するために使う。
    """

    def __init__(self, targets, head: int = 400, tail: int = 400) -> None:
        self.targets = set(targets)
        self.head = head
        self.tail = tail
        self.calls = 0

    def visible(self, user: str) -> str:
        if len(user) <= self.head + self.tail:
            return user
        return user[: self.head] + user[-self.tail :]

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResponse:
        self.calls += 1
        seen = self.visible(user)
        # set の反復順は実行ごとに変わりうるので必ずソートして決定的にする
        found = sorted(c for c in self.targets if f"[{c}]" in seen)
        if found:
            payload = {
                "answerable": True,
                "answer": "参考文書の該当箇所に基づいて回答します。",
                "citations": found,
            }
        else:
            payload = {
                "answerable": False,
                "answer": "参考文書には該当する記載が見つかりませんでした。",
                "citations": [],
            }
        text = json.dumps(payload, ensure_ascii=False)
        return LLMResponse(
            text=text, input_tokens=len(user) // 3, output_tokens=len(text) // 3, source="stub"
        )
