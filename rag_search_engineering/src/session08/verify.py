#!/usr/bin/env python3
"""セッション8の自己検証：スコア融合（RRF / 正規化和）とハイブリッドが負ける条件。

  - 読者が書く融合関数が ragkit/hybrid.py の参照実装と1件も違わないこと
  - 単純加算・min-max・RRF が外れ値に対してどう振る舞うか（手計算できる例で固定）
  - 実データで「素朴なハイブリッドは単体に負ける」「候補を絞ると回復する」こと

密ベクトルのコレクション minato_docs_fixed は作り直さない（既存を再利用する）。
SKIP_DENSE=1 を付けると実データの検証を飛ばし、手計算の例だけを検証する。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ragkit.hybrid import HybridRetriever, minmax_fuse, rrf_fuse  # noqa: E402
from ragkit.models import Hit  # noqa: E402

from fuse import (  # noqa: E402
    TOY_DENSE,
    TOY_LEXICAL,
    TOY_LEXICAL_OUTLIER,
    CachedLists,
    FusionRetriever,
    dedup_by_doc,
    my_minmax_fuse,
    my_rrf_fuse,
    naive_sum_fuse,
    zscore_fuse,
)

COLLECTION = "minato_docs_fixed"
K = 10
failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def ids(hits: list[Hit]) -> list[str]:
    return [h.chunk_id for h in hits]


def near(a: float, b: float, tol: float = 0.01) -> bool:
    return abs(a - b) <= tol


# --- 1. スコアの尺度が違う ---------------------------------------------------
check("BM25 のスコアは 1 を超える（非有界）",
      max(h.score for h in TOY_LEXICAL) > 1.0,
      f"最大 {max(h.score for h in TOY_LEXICAL):.1f}")
check("コサイン類似度は 1 を超えない",
      max(h.score for h in TOY_DENSE) <= 1.0,
      f"最大 {max(h.score for h in TOY_DENSE):.2f}")

naive = naive_sum_fuse([TOY_LEXICAL, TOY_DENSE], k=10)
check("単純加算の上位3件は BM25 単体の順位と同じ",
      ids(naive)[:3] == ids(TOY_LEXICAL), " / ".join(ids(naive)[:3]))
check("単純加算では dense の1位が最下位に落ちる",
      ids(naive)[-1] == "DOC-0450#001", ids(naive)[-1])

# --- 2. 自作の融合関数が参照実装と一致する -----------------------------------
for label, mine, ref in [
    ("rrf", my_rrf_fuse([TOY_LEXICAL, TOY_DENSE], k=10, rrf_k=60),
     rrf_fuse([TOY_LEXICAL, TOY_DENSE], k=10, rrf_k=60)),
    ("minmax", my_minmax_fuse([TOY_LEXICAL, TOY_DENSE], weights=[0.3, 1.0], k=10),
     minmax_fuse([TOY_LEXICAL, TOY_DENSE], weights=[0.3, 1.0], k=10)),
]:
    same = ids(mine) == ids(ref) and all(
        abs(a.score - b.score) < 1e-12 for a, b in zip(mine, ref))
    check(f"自作の {label} が ragkit の参照実装と一致する", same, " / ".join(ids(mine)[:3]))

# --- 3. RRF の値と rrf_k の意味 ----------------------------------------------
rrf = my_rrf_fuse([TOY_LEXICAL, TOY_DENSE], k=10, rrf_k=60)
expected = 1.0 / 61 + 1.0 / 63  # BM25 で1位・dense で3位
check("RRF のスコアが 1/(rrf_k+順位) の和になっている",
      ids(rrf)[0] == "DOC-0101#001" and abs(rrf[0].score - expected) < 1e-12,
      f"{rrf[0].score:.6f} == {expected:.6f}")
check("両方のリストに出たチャンクが順位を上げる",
      ids(rrf)[1] == "DOC-0331#001", " / ".join(ids(rrf)[:3]))

# 片方のリストで1位のもの vs 両方のリストで4位のもの。rrf_k はここで効く
only_top = [Hit("A-0001#001", "A-0001", 9.9, "", {}), Hit("B-0002#001", "B-0002", 8.0, "", {}),
            Hit("B-0003#001", "B-0003", 7.0, "", {}), Hit("C-0009#001", "C-0009", 6.0, "", {})]
both_low = [Hit("B-0002#001", "B-0002", 0.90, "", {}), Hit("B-0003#001", "B-0003", 0.88, "", {}),
            Hit("D-0004#001", "D-0004", 0.80, "", {}), Hit("C-0009#001", "C-0009", 0.70, "", {})]
small = ids(my_rrf_fuse([only_top, both_low], k=10, rrf_k=1))
large = ids(my_rrf_fuse([only_top, both_low], k=10, rrf_k=10))
check("rrf_k を小さくすると「片方で1位」が勝つ",
      small.index("A-0001#001") < small.index("C-0009#001"), " / ".join(small[:3]))
check("rrf_k を大きくすると「両方で上位」が勝つ",
      large.index("A-0001#001") > large.index("C-0009#001"), " / ".join(large[:3]))

# --- 4. 外れ値に対する強さ ---------------------------------------------------
mm_before = ids(my_minmax_fuse([TOY_LEXICAL, TOY_DENSE], k=10))
mm_after = ids(my_minmax_fuse([TOY_LEXICAL_OUTLIER, TOY_DENSE], k=10))
rrf_after = ids(my_rrf_fuse([TOY_LEXICAL_OUTLIER, TOY_DENSE], k=10, rrf_k=60))
check("min-max は外れ値1件で順位が崩れる（1位 -> 4位）",
      mm_before.index("DOC-0101#001") == 0 and mm_after.index("DOC-0101#001") == 3,
      f"{mm_before.index('DOC-0101#001') + 1}位 -> {mm_after.index('DOC-0101#001') + 1}位")
check("RRF は外れ値1件では順位が動かない",
      rrf_after.index("DOC-0101#001") == 0, " / ".join(rrf_after[:3]))

# --- 5. 重み・同点・重複排除 -------------------------------------------------
w_zero = ids(my_minmax_fuse([TOY_LEXICAL, TOY_DENSE], weights=[1.0, 0.0], k=10))
check("重み0でも候補は残る（無効化ではない）",
      w_zero[:3] == ids(TOY_LEXICAL) and "DOC-0450#001" in w_zero,
      " / ".join(w_zero))
check("同点は chunk_id の昇順で決まる（実行のたびに変わらない）",
      ids(my_minmax_fuse([TOY_LEXICAL, TOY_DENSE], k=10))
      == ids(my_minmax_fuse([TOY_LEXICAL, TOY_DENSE], k=10)) == mm_before,
      " / ".join(mm_before[:2]))

dup = [Hit("DOC-0101#001", "DOC-0101", 3.0, "", {}), Hit("DOC-0101#002", "DOC-0101", 2.0, "", {}),
       Hit("DOC-0207#002", "DOC-0207", 1.0, "", {})]
check("dedup_by_doc は同じ文書から1件だけ残す",
      ids(dedup_by_doc(dup, k=2)) == ["DOC-0101#001", "DOC-0207#002"],
      " / ".join(ids(dedup_by_doc(dup, k=2))))

zs = zscore_fuse([TOY_LEXICAL, TOY_DENSE], weights=[1.0, 1.0], k=10)
check("z-score 融合が4件すべてを順位付けできる",
      len(zs) == 4 and len({h.chunk_id for h in zs}) == 4, " / ".join(ids(zs)))

if os.environ.get("SKIP_DENSE") == "1":
    print("\nSKIP_DENSE=1 のため実データの検証を飛ばします。")
    if failures:
        print(f"{len(failures)} 件の検証に失敗しました: {failures}")
        sys.exit(1)
    sys.exit(0)

# --- 6. 実データ：素朴なハイブリッドは単体に負ける ---------------------------
from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.dense import DenseIndex  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402

docs, queries, qrels = load_docs(), load_queries(), load_qrels()
chunks = chunk_all(docs, "fixed", size=400, overlap=80)
lex = LexicalIndex().build(chunks)
dense = DenseIndex(COLLECTION)
if not dense.client.collection_exists(COLLECTION):
    print("コレクションを作成します（1分程度かかります）")
    dense.build(chunks)


def rrf_retriever(candidates: int, rrf_k: int):
    return FusionRetriever([lex, dense], candidates=candidates, fuse=my_rrf_fuse, rrf_k=rrf_k)


rep_lex = evaluate(lex, queries, qrels, k=K, label="bm25")
rep_dense = evaluate(dense, queries, qrels, k=K, label="dense")
rep_50_60 = evaluate(rrf_retriever(50, 60), queries, qrels, k=K, label="rrf(50,60)")
rep_20_60 = evaluate(rrf_retriever(20, 60), queries, qrels, k=K, label="rrf(20,60)")
rep_10_60 = evaluate(rrf_retriever(10, 60), queries, qrels, k=K, label="rrf(10,60)")
rep_10_10 = evaluate(rrf_retriever(10, 10), queries, qrels, k=K, label="rrf(10,10)")
mm_03 = FusionRetriever([lex, dense], candidates=50, fuse=my_minmax_fuse, weights=[0.3, 1.0])
rep_mm03 = evaluate(mm_03, queries, qrels, k=K, label="minmax(0.3:1.0)")

print()
for rep in (rep_lex, rep_dense, rep_50_60, rep_10_10, rep_mm03):
    print("   " + rep.summary())
print()

check("bm25 単体の Recall@10 が 0.763", near(rep_lex.macro["recall"], 0.763),
      f"{rep_lex.macro['recall']:.3f}")
check("dense 単体の Recall@10 が 0.783", near(rep_dense.macro["recall"], 0.783),
      f"{rep_dense.macro['recall']:.3f}")
check("素朴なハイブリッド rrf(候補50, rrf_k=60) の Recall@10 が 0.762",
      near(rep_50_60.macro["recall"], 0.762), f"{rep_50_60.macro['recall']:.3f}")
check("素朴なハイブリッドは密ベクトル単体に負ける",
      rep_50_60.macro["recall"] < rep_dense.macro["recall"],
      f"{rep_50_60.macro['recall']:.3f} < {rep_dense.macro['recall']:.3f}")
check("素朴なハイブリッドは BM25 単体にも勝てていない",
      rep_50_60.macro["recall"] <= rep_lex.macro["recall"] + 0.005,
      f"{rep_50_60.macro['recall']:.3f} <= {rep_lex.macro['recall']:.3f}")

# --- 7. 候補数を絞ると回復する -----------------------------------------------
check("候補数を増やすほど悪化する（10 > 20 > 50）",
      rep_10_60.macro["recall"] > rep_20_60.macro["recall"] > rep_50_60.macro["recall"],
      f"{rep_10_60.macro['recall']:.3f} > {rep_20_60.macro['recall']:.3f} > "
      f"{rep_50_60.macro['recall']:.3f}")
check("候補10 の RRF は両方の単体を上回る（0.795）",
      near(rep_10_10.macro["recall"], 0.795)
      and rep_10_10.macro["recall"] > rep_dense.macro["recall"],
      f"{rep_10_10.macro['recall']:.3f} > {rep_dense.macro['recall']:.3f}")
check("rrf_k の影響は候補数の影響より小さい",
      abs(rep_10_10.macro["recall"] - rep_10_60.macro["recall"])
      < rep_10_60.macro["recall"] - rep_50_60.macro["recall"],
      f"rrf_k 差={abs(rep_10_10.macro['recall'] - rep_10_60.macro['recall']):.3f} / "
      f"候補数 差={rep_10_60.macro['recall'] - rep_50_60.macro['recall']:.3f}")

# --- 8. 略語クエリ：弱い側の順位はノイズになる -------------------------------
ab_lex = rep_lex.by_type["abbrev"]["recall"]
ab_dense = rep_dense.by_type["abbrev"]["recall"]
ab_50_60 = rep_50_60.by_type["abbrev"]["recall"]
ab_mm03 = rep_mm03.by_type["abbrev"]["recall"]
check("略語クエリでは素朴なハイブリッドが BM25 単体より悪化する",
      ab_50_60 < ab_lex, f"{ab_50_60:.3f} < {ab_lex:.3f}")
check("弱い側の重みを下げると略語クエリが密ベクトル単体を上回る",
      ab_mm03 > ab_dense, f"{ab_mm03:.3f} > {ab_dense:.3f}")
check("minmax(0.3:1.0) の Recall@10 が 0.797", near(rep_mm03.macro["recall"], 0.797),
      f"{rep_mm03.macro['recall']:.3f}")

# --- 9. 参照実装との一致（実データ）-----------------------------------------
ref = HybridRetriever([lex, dense], 50, "rrf")
mine = rrf_retriever(50, 60)
same = all(ids(mine.search(q.text, k=K)) == ids(ref.search(q.text, k=K))
           for q in queries[:5])
check("自作の FusionRetriever が ragkit の HybridRetriever と一致する（実データ5件）", same)

# --- 10. 重複排除は k の意味を変える -----------------------------------------
plain = FusionRetriever([lex, dense], candidates=10, fuse=my_rrf_fuse, rrf_k=10)
deduped = FusionRetriever([lex, dense], candidates=10, fuse=my_rrf_fuse, rrf_k=10,
                          dedup_docs=True)
rep_plain = evaluate(plain, queries, qrels, k=K)
rep_dedup = evaluate(deduped, queries, qrels, k=K)
check("文書単位の重複排除は Recall@10 を下げない（k の単位が文書に変わる）",
      rep_dedup.macro["recall"] >= rep_plain.macro["recall"] - 1e-9,
      f"{rep_dedup.macro['recall']:.3f} >= {rep_plain.macro['recall']:.3f}")

# --- 11. 型別ルーティングの上限 ----------------------------------------------
mm_11 = FusionRetriever([lex, dense], candidates=50, fuse=my_minmax_fuse, weights=[1.0, 1.0])
rep_mm11 = evaluate(mm_11, queries, qrels, k=K)
reports = [rep_lex, rep_dense, rep_50_60, rep_mm11]
total = 0.0
n_all = 0
for t in sorted(rep_lex.by_type):
    n = int(rep_lex.by_type[t]["n_queries"])
    total += max(round(r.by_type[t]["recall"], 3) for r in reports) * n
    n_all += n
oracle = total / n_all
check("型ごとに最良を選べたとしても Recall@10 は 0.802 で頭打ち",
      near(oracle, 0.802, 0.005) and n_all == 110, f"{oracle:.3f}（n={n_all}）")

# --- 12. 重みの過学習 --------------------------------------------------------
answerable = [q for q in queries if any(g >= 1 for g in qrels.get(q.query_id, {}).values())]
tune = [q for i, q in enumerate(answerable) if i % 2 == 0]
holdout = [q for i, q in enumerate(answerable) if i % 2 == 1]
check("学習用と評価用が重ならず、合計が回答可能なクエリ数と一致する",
      len(tune) + len(holdout) == len(answerable) == 110
      and not ({q.query_id for q in tune} & {q.query_id for q in holdout}),
      f"{len(tune)} + {len(holdout)} = {len(answerable)}")

cache = CachedLists([lex, dense], queries, candidates=50)
rows = []
for w in ([1.0, 1.0], [0.3, 1.0], [0.5, 1.0], [1.0, 0.5], [1.0, 0.3]):
    r = cache.retriever(my_minmax_fuse, weights=w)
    rows.append((w,
                 evaluate(r, tune, qrels, k=K).macro["recall"],
                 evaluate(r, holdout, qrels, k=K).macro["recall"]))
spread = max(r[1] for r in rows) - min(r[1] for r in rows)
best_tune = max(rows, key=lambda r: r[1])
best_hold = max(rows, key=lambda r: r[2])
check("重み候補間の開きは小さい（詰めても得られる差はわずか）",
      spread < 0.12, f"開き {spread:.3f}")
check("学習用で選んだ重みの汎化ギャップが小さい",
      best_hold[2] - best_tune[2] < 0.10,
      f"評価用の最良 {best_hold[2]:.3f} - 選んだ重みの評価用 {best_tune[2]:.3f}")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション8の検証はすべて成功しました。")
