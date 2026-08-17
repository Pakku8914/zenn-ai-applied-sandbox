#!/usr/bin/env python3
"""横断復習01（セッション2〜5）の小道具。

セッション2〜5でばらばらに作った道具を、1本の切り分けの流れに束ねる。
新しい検索方式は増やしていない。ここにあるのは「測る・切り分ける・直す」だけ。

  failure_split        失敗を「到達不足」と「順位不足」に分解する（S02 × S05）
  strip_heading_marks  「Markdown の記号はノイズ」という前処理（S03 の事故を再現する）
  expand_query         略語をクエリ側で吸収する（S03 の正規化 × S05 の同義語）
  SynonymRetriever     既存の検索器を包んで展開を挟む（索引は作り直さない）
  win_loss             クエリ単位の勝ち負けを数える（平均だけを見ない・S02）
  mean_folded_docs     上位k件が平均何文書に畳み込まれるか（P@k の分母・S02 × S04）
"""

from __future__ import annotations

import re
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.eval import hits_to_docs, recall_at_k  # noqa: E402
from ragkit.models import Doc  # noqa: E402
from ragkit.tokenize_ja import normalize, tokens_bigram  # noqa: E402

# ---------------------------------------------------------------------------
# 1. 失敗の分解（S02 の指標 × S05 の語彙）
# ---------------------------------------------------------------------------


def failure_split(retriever, queries, qrels, k: int = 10,
                  pool: int = 100) -> dict[str, dict[str, float]]:
    """「1 - Recall@k」を到達不足と順位不足に分けて、クエリ型別に集計する。

    到達不足 = 1 - Recall@pool    候補プールにすら入っていない
                                  → 語彙・前処理・チャンクの問題（k を増やしても直らない）
    順位不足 = Recall@pool - Recall@k
                                  → プールには居るのに上位に来ない
                                  → 採点・並べ替えの問題（候補を増やすか並べ替えると直る）

    回答不能クエリは Recall が常に 0 になるので除く（`ragkit.eval.evaluate` と同じ扱い）。
    """
    acc: dict[str, list[tuple[float, float]]] = {}
    for q in queries:
        qr = qrels.get(q.query_id, {})
        if not any(g >= 1 for g in qr.values()):
            continue
        # Recall@k は「上位k件のヒット」から測る。プールを取ってから上位k文書を数えると
        # 定義が変わってしまうので、必ず2回検索する
        r_k = recall_at_k(retriever.search(q.text, k=k), qr, k)
        r_pool = recall_at_k(retriever.search(q.text, k=pool), qr, pool)
        acc.setdefault(q.type, []).append((r_k, r_pool))
        acc.setdefault("ALL", []).append((r_k, r_pool))

    out: dict[str, dict[str, float]] = {}
    for qtype, rows in acc.items():
        n = len(rows)
        recall = sum(a for a, _ in rows) / n
        reach = sum(b for _, b in rows) / n
        out[qtype] = {
            "n": float(n),
            "recall": recall,
            "reach": reach,
            "rank_loss": reach - recall,
            "reach_loss": 1.0 - reach,
        }
    return out


def print_split(label: str, split: dict[str, dict[str, float]], k: int = 10,
                pool: int = 100) -> None:
    """failure_split の結果を表で出す。"""
    print(f"[{label}]")
    print(f"{'型':<16}{'n':>5}{f'  Recall@{k}':>12}{f'  到達@{pool}':>12}"
          f"{'  順位不足':>12}{'  到達不足':>12}")
    keys = [t for t in sorted(split) if t != "ALL"] + (["ALL"] if "ALL" in split else [])
    for qtype in keys:
        row = split[qtype]
        print(f"{qtype:<16}{int(row['n']):>5}{row['recall']:>12.3f}{row['reach']:>12.3f}"
              f"{row['rank_loss']:>12.3f}{row['reach_loss']:>12.3f}")


# ---------------------------------------------------------------------------
# 2. 前処理の事故（S03 の正規化 × S04 のチャンク方式）
# ---------------------------------------------------------------------------

HEADING_MARK = re.compile(r"^#{1,6}[ \t]*", re.MULTILINE)


def strip_heading_marks(text: str) -> str:
    """行頭の `#` を落とす。「Markdown の記号は検索に不要」という判断で入りがちな前処理。

    悪意も手抜きも無い1行だが、見出しを意味単位として使う分割方式の前提を壊す。
    """
    return HEADING_MARK.sub("", text)


def strip_docs(docs: list[Doc]) -> list[Doc]:
    """本文だけを差し替えた文書集合を返す（元の docs は変更しない）。"""
    return [replace(d, body=strip_heading_marks(d.body)) for d in docs]


# ---------------------------------------------------------------------------
# 3. 略語への対策（S03 の正規化 × S05 の同義語）
# ---------------------------------------------------------------------------

# 左が利用者の言い方、右がコーパス側の正式名称。文書には正式名称しか書かれていない。
SYNONYMS: dict[str, str] = {
    "年休": "有給休暇",
    "有休": "有給休暇",
    "残業": "時間外労働",
    "育休": "育児休業",
    "定期代": "通勤交通費",
    "パソコン": "貸与PC",
    "スマホ": "貸与スマートフォン",
    "携帯": "貸与スマートフォン",
    "パス": "パスワード",
    "PW": "パスワード",
    "MFA": "多要素認証",
    "二要素認証": "多要素認証",
    "2段階認証": "多要素認証",
    "社員証": "入退館カード",
    "フリーアドレス": "座席",
    "フィッシング": "標的型メール",
    "不審メール": "標的型メール",
    "SaaS": "外部サービス",
    "クラウドサービス": "外部サービス",
    "インシデント": "セキュリティ事故",
}


def expand_query(text: str, table: dict[str, str] | None = None) -> str:
    """クエリ側だけで同義語を足す。索引は作り直さない。

    設計上の約束を2つ置いている。

      1. 辞書のキーも、索引と同じ `normalize()` を通してから照合する（S03）
         こうしないと全角の「ＭＦＡ」が辞書に当たらない
      2. 正式名称がすでにクエリに入っているときは足さない
         同じ語を2回入れると tf が水増しされ、その語を含む文書が不当に上がる（S05）
    """
    table = SYNONYMS if table is None else table
    q = normalize(text)
    extra: list[str] = []
    added: set[str] = set()
    for key, canon in table.items():
        c = normalize(canon)
        if normalize(key) in q and c not in q and c not in added:
            added.add(c)
            extra.append(canon)
    return f"{text} {' '.join(extra)}" if extra else text


def expand_query_naive(text: str, table: dict[str, str] | None = None) -> str:
    """素朴版：辞書のキーをそのまま置換する。2つの理由で壊れる（教材用）。

      - 部分文字列に当たる：「パスワード」の中の「パス」まで置換してしまう
      - 表記ゆれに当たらない：全角の「ＭＦＡ」は素の `in` では見つからない
    """
    table = SYNONYMS if table is None else table
    out = text
    for key, canon in table.items():
        out = out.replace(key, canon)
    return out


class SynonymRetriever:
    """既存の検索器を包んで、クエリを展開してから渡すだけの検索器。

    `search(query, k, filters)` を持つので、そのまま `ragkit.eval.evaluate` に渡せる。
    索引を作り直さずに効果を測れるのが、この形にしている理由。
    """

    def __init__(self, index, table: dict[str, str] | None = None) -> None:
        self.index = index
        self.table = SYNONYMS if table is None else table

    def search(self, query: str, k: int = 10, filters: dict | None = None):
        return self.index.search(expand_query(query, self.table), k=k, filters=filters)


def shares_bigram(a: str, b: str) -> bool:
    """2つの語が文字 bi-gram を共有するか。

    文字N-gramのトークナイザに切り替えたとき、その略語が正式名称に当たるかどうかは
    ここで決まる。測る前に紙の上で予測できる（S05）。
    """
    return bool(set(tokens_bigram(a)) & set(tokens_bigram(b)))


# ---------------------------------------------------------------------------
# 4. 比較の道具（S02）
# ---------------------------------------------------------------------------


def win_loss(rep_a, rep_b, metric: str = "recall", eps: float = 1e-9) -> dict[str, int]:
    """クエリ単位で A が B に勝った件数・負けた件数を数える。

    平均が 0.01 動いたときに「1件が大きく勝った」のか「70件が少しずつ勝った」のかは、
    平均を見ているかぎり区別できない。
    """
    win = loss = tie = 0
    for qid, row in rep_a.per_query.items():
        diff = row[metric] - rep_b.per_query[qid][metric]
        if diff > eps:
            win += 1
        elif diff < -eps:
            loss += 1
        else:
            tie += 1
    return {"win": win, "loss": loss, "tie": tie}


def mean_folded_docs(retriever, queries, qrels, k: int = 10) -> float:
    """上位k件のヒットが平均して何文書に畳み込まれるか（＝ P@k の分母）。"""
    vals: list[int] = []
    for q in queries:
        qr = qrels.get(q.query_id, {})
        if not any(g >= 1 for g in qr.values()):
            continue
        vals.append(len(hits_to_docs(retriever.search(q.text, k=k))))
    return sum(vals) / len(vals) if vals else 0.0


def zero_term_docs(query_text: str, doc_ids: list[str], docs_by_id: dict[str, Doc],
                   mode: str = "morph") -> list[str]:
    """クエリの語を1つも含まない文書を返す（＝どんな k でも到達できない文書）。"""
    from ragkit.tokenize_ja import tokenize

    terms = set(tokenize(query_text, mode))
    out: list[str] = []
    for doc_id in doc_ids:
        doc = docs_by_id.get(doc_id)
        if doc is None:
            continue
        if not (terms & set(tokenize(doc.full_text, mode))):
            out.append(doc_id)
    return out
