#!/usr/bin/env python3
"""セッション9の自己検証：リランク（クロスエンコーダ）。

検証すること
  1. レイテンシ予算からの逆算（モデル不要・数値だけの検算）
  2. バイエンコーダの性質：スコアは -1〜1 / 文書ベクトルは索引時に計算して使い回せる
  3. クロスエンコーダの性質：適合文書に高いスコアを付ける / スコアの開きが大きい
  4. リランクの不変条件：候補プールの部分集合・降順・Recall は上限を超えない
  5. 到達不足のクエリではリランクしても Recall@10 が1件も増えないこと
  6. 候補数を増やすとレイテンシが増えること（ただし線形より緩やかであること）

全 110 クエリのリランク評価はここでは回さない（3分近くかかる）。
集計値は tools/bench_rerank.py で取る。

密ベクトルのコレクション minato_docs_fixed は作り直さない（既存を再利用する）。
SKIP_DENSE=1 を付けるとモデルを使う検証を飛ばし、予算の計算だけを検証する。
"""

from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from budget import MEASURED, fit_least_squares, fit_two_point, max_candidates  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def near(a: float, b: float, tol: float = 0.01) -> bool:
    return abs(a - b) <= tol


def ids(hits) -> list[str]:
    return [h.chunk_id for h in hits]


def finish() -> None:
    if failures:
        print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
        sys.exit(1)
    print("\nセッション9の検証はすべて成功しました。")
    sys.exit(0)


# --- 1. レイテンシ予算の逆算 -------------------------------------------------
two, ls = fit_two_point(), fit_least_squares()
check("局所2点（候補10と20）の傾きが 30.4 ms/件になる", near(two[0], 30.4, 0.05),
      f"{two[0]:.1f} ms/件")
check("最小二乗の傾きは局所2点より緩い（1件あたりのコストが下がるため）",
      ls[0] < two[0], f"{ls[0]:.1f} < {two[0]:.1f}")
check("予算500ms・1段目に20msを引き当てると上限は12件（局所2点）",
      int(max_candidates(two, 480.0)) == 12, f"n <= {max_candidates(two, 480.0):.1f}")
check("予算500msをすべてリランクに使っても上限は13件（局所2点）",
      int(max_candidates(two, 500.0)) == 13, f"n <= {max_candidates(two, 500.0):.1f}")
check("最小二乗で当てると10件・11件になる（モデルの取り方で答えが振れる）",
      int(max_candidates(ls, 480.0)) == 10 and int(max_candidates(ls, 500.0)) == 11,
      f"{max_candidates(ls, 480.0):.1f} / {max_candidates(ls, 500.0):.1f}")
answers = [int(max_candidates(m, b)) for m in (two, ls) for b in (480.0, 500.0)]
check("どのモデルでも答えは 10〜13 件に収まる（桁で決めれば揺れない）",
      min(answers) >= 10 and max(answers) <= 13, f"{min(answers)}〜{max(answers)}")
check("候補100件は 500ms の予算にまったく収まらない（実測 2,710ms）",
      MEASURED[100][0] > 5 * 500.0, f"{MEASURED[100][0]:.0f} ms")

if os.environ.get("SKIP_DENSE") == "1":
    print("\nSKIP_DENSE=1 のためモデルを使う検証を飛ばします。")
    finish()

# --- 2. バイエンコーダ（クエリと文書を別々に符号化する）----------------------
import numpy as np  # noqa: E402

from common import answerable, ceiling_recall, dense_index, first_of_type, load_all  # noqa: E402
from pair_score import pick_passages  # noqa: E402

from ragkit.dense import Embedder  # noqa: E402
from ragkit.eval import evaluate, ndcg_at_k, recall_at_k  # noqa: E402
from ragkit.rerank import CrossEncoderReranker  # noqa: E402

K = 10
docs, queries, qrels, chunks = load_all()
dense = dense_index(chunks)

query = first_of_type(queries, qrels, "natural")[0]
qr = qrels[query.query_id]
pool20 = dense.search(query.text, k=20)
check("密ベクトル検索のスコア（コサイン類似度）は -1〜1 に収まる",
      all(-1.0001 <= h.score <= 1.0001 for h in pool20),
      f"最大 {max(h.score for h in pool20):.4f}")

q_vec = Embedder.encode_query(query.text)
doc_vecs = Embedder.encode_passages([h.text for h in pool20[:3]])
diffs = [abs(float(np.dot(q_vec, v)) - h.score) for h, v in zip(pool20[:3], doc_vecs)]
check("文書ベクトルは索引時に1度計算すれば足りる（再計算しても同じスコアになる）",
      max(diffs) < 2e-3, f"最大差 {max(diffs):.6f}")

# --- 3. クロスエンコーダ（クエリと文書を一緒に読む）--------------------------
t0 = time.perf_counter()
model = CrossEncoderReranker.get()
load_first = time.perf_counter() - t0
t0 = time.perf_counter()
CrossEncoderReranker.get()
load_second = time.perf_counter() - t0
print(f"    （リランカのロード: 初回 {load_first:.1f}s / 2回目 {load_second:.3f}s）")
check("リランカはプロセス内で1度しかロードされない（2回目は即座に返る）",
      load_second < 0.5, f"{load_second:.3f}s")

labeled = pick_passages(docs, chunks, qrels, query)
positive = next(c for label, c in labeled if label.startswith(("完全適合", "部分適合")))
negative = next(c for label, c in labeled if label.startswith("無関係"))
pair_scores = [float(s) for s in model.predict(
    [(query.text, positive.text), (query.text, negative.text)], show_progress_bar=False)]
check("クロスエンコーダは適合文書に高いスコアを付ける",
      pair_scores[0] > pair_scores[1],
      f"適合 {pair_scores[0]:.4f} > 無関係 {pair_scores[1]:.4f}")

ce20 = [float(s) for s in model.predict(
    [(query.text, h.text) for h in pool20], show_progress_bar=False)]
cos_spread = max(h.score for h in pool20) - min(h.score for h in pool20)
ce_spread = max(ce20) - min(ce20)
check("同じ候補20件でも、クロスエンコーダのほうがスコアの開きが大きい",
      ce_spread > cos_spread, f"CE {ce_spread:.4f} > コサイン {cos_spread:.4f}")

# --- 4. リランクの不変条件 ---------------------------------------------------
sample = first_of_type(queries, qrels, "natural", n=3) + \
    first_of_type(queries, qrels, "multi_condition", n=2)
subset_ok, desc_ok, ceiling_ok, changed = True, True, True, 0
ndcg_moves: list[tuple[float, float]] = []
for q in sample:
    q_qr = qrels[q.query_id]
    pool = dense.search(q.text, k=20)
    after = CrossEncoderReranker.rerank(q.text, pool, top_k=K)
    subset_ok &= set(ids(after)) <= set(ids(pool)) and len(after) == K
    desc_ok &= all(after[i].score >= after[i + 1].score for i in range(len(after) - 1))
    ceiling_ok &= recall_at_k(after, q_qr, K) <= ceiling_recall(pool, q_qr, K) + 1e-9
    changed += 1 if ids(after) != ids(pool[:K]) else 0
    ndcg_moves.append((ndcg_at_k(pool[:K], q_qr, K), ndcg_at_k(after, q_qr, K)))

check("リランクは候補プールの外から文書を持ってこない（部分集合になる）", subset_ok)
check("リランクの結果はクロスエンコーダのスコアの降順に並ぶ", desc_ok)
check("リランクで上位10件の並びが変わるクエリがある", changed >= 1, f"{changed}/{len(sample)} 件")
check("リランク後の Recall@10 は候補プールの上限を超えない（並べ替えしかできない）",
      ceiling_ok)
up = sum(1 for b, a in ndcg_moves if a > b + 1e-9)
down = sum(1 for b, a in ndcg_moves if a < b - 1e-9)
print(f"    （参考：この5件では nDCG@10 が改善 {up} 件 / 悪化 {down} 件。"
      "全体の集計は tools/bench_rerank.py で取る）")

# --- 5. 到達不足のクエリではリランクが効かない -------------------------------
abbrev = [q for q in answerable(queries, qrels) if q.type == "abbrev"]
hopeless = []
for q in abbrev:
    q_qr = qrels[q.query_id]
    base = dense.search(q.text, k=K)
    pool = dense.search(q.text, k=50)
    before_r = recall_at_k(base, q_qr, K)
    # 「まだ取れていない適合文書があるのに、候補50件を見ても増やせない」＝到達不足で頭打ち
    if before_r < 1.0 - 1e-9 and ceiling_recall(pool, q_qr, K) <= before_r + 1e-9:
        hopeless.append((q, before_r, pool))
check("略語クエリには「候補を50件に広げても Recall が伸びない」クエリが存在する",
      len(hopeless) >= 1, f"{len(hopeless)}/{len(abbrev)} 件が到達不足で頭打ち")

no_gain = True
for q, before_r, pool in hopeless[:3]:
    after = CrossEncoderReranker.rerank(q.text, pool, top_k=K)
    no_gain &= recall_at_k(after, qrels[q.query_id], K) <= before_r + 1e-9
check("到達不足のクエリはリランクしても Recall@10 が1件も増えない",
      no_gain, f"{min(3, len(hopeless))} 件で確認")

# --- 6. 候補数とレイテンシ ---------------------------------------------------
bench_pool = dense.search(query.text, k=20)
CrossEncoderReranker.rerank(query.text, bench_pool[:5], top_k=K)  # 計測前の空回し
lat: dict[int, float] = {}
for c in (5, 10, 20):
    runs = []
    for _ in range(3):
        t0 = time.perf_counter()
        CrossEncoderReranker.rerank(query.text, bench_pool[:c], top_k=K)
        runs.append((time.perf_counter() - t0) * 1000)
    lat[c] = statistics.median(runs)
print("    （候補数ごとの中央値: " + " / ".join(f"{c}件 {v:.0f}ms" for c, v in lat.items()) + "）")
check("候補数を増やすとリランクの所要時間が増える（5 < 10 < 20）",
      lat[5] < lat[10] < lat[20])
check("候補数を2倍にしても所要時間は2倍未満（1件あたりのコストは下がる）",
      lat[20] < 2 * lat[10], f"{lat[20]:.0f} < {2 * lat[10]:.0f} ms")

# --- 7. 1段目の基準線（本文の表と同じ値が出るか）-----------------------------
rep = evaluate(dense, queries, qrels, k=K, label="dense のみ")
print("   " + rep.summary())
check("1段目（dense のみ）の Recall@10 が 0.783", near(rep.macro["recall"], 0.783),
      f"{rep.macro['recall']:.3f}")
check("1段目（dense のみ）の nDCG@10 が 0.661", near(rep.macro["ndcg"], 0.661),
      f"{rep.macro['ndcg']:.3f}")
check("評価対象は回答可能な 110 クエリ", int(rep.macro["n_queries"]) == 110,
      f"{int(rep.macro['n_queries'])} 件")

finish()
