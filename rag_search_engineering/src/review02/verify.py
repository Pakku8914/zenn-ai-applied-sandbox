#!/usr/bin/env python3
"""横断復習02（セッション3〜8）の自己検証。

  1. 尺度の違うスコアを足すと片方が消えること／RRF と min-max で順位が変わること（S05×S06×S08）
  2. 索引作成の見積もりが「件数モデル」でも「文字数モデル」でも実測を外すこと（S06×S04）
  3. 「正規化」が指す4つの別物のうち、文字の正規化が期待どおり動くこと（S03×S05）
  4. 上位k件を取ってから絞ると候補が枯れること（S07×S03×S04）
  5. L2正規化されたベクトルでは内積・コサイン・ユークリッドの順位が一致すること（S06×S07）
  6. 673チャンクでは `ef` を振っても何も起きないこと（S07）
  7. 素朴なハイブリッドが単体に負け、候補数と重みで回復すること（S08）
  8. 型別ルーティングのオラクルが固定設定を必ず上回ること（S08×S02）

SKIP_DENSE=1 を付けると 5〜8（埋め込みモデルと Qdrant を使う検証）を飛ばす。
期待値と一致しなければ非0で終了する（人が出力を読んで判断しない）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fusion_lab import (  # noqa: E402
    EfIndex, ann_recall_sweep, build_indexes, filter_run, index_seconds, load_vectors,
    query_vector, simple_sum_fuse, subset_mean, TypeRoutedRetriever,
)
from index_budget import BATCH, CHUNKS, MEASURED, MS_PER_CHUNK  # noqa: E402
from score_scale import BM25, DENSE, to_hits  # noqa: E402

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.hybrid import minmax_fuse, rrf_fuse  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402
from ragkit.tokenize_ja import normalize  # noqa: E402

SKIP_DENSE = os.environ.get("SKIP_DENSE") == "1"
failures: list[str] = []


def check(label: str, got, want, tol: float = 0.0) -> None:
    ok = abs(got - want) <= tol if isinstance(want, float) else got == want
    shown = f"{got:.3f}" if isinstance(want, float) else got
    print(f"[{'OK' if ok else 'NG'}] {label}: got={shown} want={want}")
    if not ok:
        failures.append(label)


def check_true(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'OK' if cond else 'NG'}] {label}" + (f" — {detail}" if detail else ""))
    if not cond:
        failures.append(label)


def order(hits) -> list[str]:
    return [h.doc_id for h in hits]


# ---------------------------------------------------------------------------
# 1. スコアの尺度と統合 — S05 × S06 × S08
# ---------------------------------------------------------------------------
print("--- 1. スコアの尺度と統合 ---")

lex_hits, dense_hits = to_hits(BM25), to_hits(DENSE)

fused_sum = simple_sum_fuse([lex_hits, dense_hits], k=8)
check("単純加算の順位", order(fused_sum), ["A", "B", "C", "D", "E", "F", "G", "H"])
check("単純加算の1位のスコア（18.42 + 0.881）", fused_sum[0].score, 19.301, 1e-6)
check_true("密ベクトル側の1位（F）が下位に沈む（コサインの 0.912 は BM25 の 11.50 に勝てない）",
           order(fused_sum).index("F") >= 5)

fused_rrf = rrf_fuse([lex_hits, dense_hits], k=8, rrf_k=60)
check("RRF の順位", order(fused_rrf), ["A", "C", "F", "B", "G", "D", "E", "H"])
check("RRF の1位のスコア（1/61 + 1/64）", fused_rrf[0].score, 1 / 61 + 1 / 64, 1e-9)
check_true("RRF では片方だけの1位（F）が、もう片方の2位（B）より上に来る",
           order(fused_rrf).index("F") < order(fused_rrf).index("B"))

fused_mm = minmax_fuse([lex_hits, dense_hits], weights=[1.0, 1.0], k=8)
check("min-max の順位", order(fused_mm), ["A", "F", "C", "G", "B", "D", "E", "H"])
check("min-max の1位のスコア（1.000 + 0.004/0.035）", fused_mm[0].score, 1.0 + 0.004 / 0.035, 1e-6)
check_true("min-max は各リストの最下位を必ず 0 にする（E と H が同点で最下位）",
           abs(fused_mm[-1].score) < 1e-12 and abs(fused_mm[-2].score) < 1e-12)
check_true("3つの統合方法はすべて違う順位を出す",
           len({tuple(order(fused_sum)), tuple(order(fused_rrf)), tuple(order(fused_mm))}) == 3)

# ---------------------------------------------------------------------------
# 2. 索引作成の見積もり — S06 × S04
# ---------------------------------------------------------------------------
print("\n--- 2. 索引作成の見積もり ---")

check("673チャンクの見積もり（秒）", index_seconds(673, MS_PER_CHUNK), 38.2, 0.1)
check("10万チャンクの見積もり（分）", index_seconds(100_000, MS_PER_CHUNK) / 60, 94.6, 0.2)

n_fixed, avg_fixed = CHUNKS["fixed(400/80)"]
n_head, avg_head = CHUNKS["heading(600)"]
est_ratio = index_seconds(n_head) / index_seconds(n_fixed)
actual_ratio = MEASURED["heading(600)"] / MEASURED["fixed(400/80)"]
char_ratio = (n_head * avg_head) / (n_fixed * avg_fixed)
check_true("件数モデルは heading を 2.9倍以上遅いと見積もる", est_ratio > 2.9, f"{est_ratio:.3f} 倍")
check_true("実測は逆に heading の方が速い", actual_ratio < 1.0, f"{actual_ratio:.3f} 倍")
check_true("総文字数はほぼ同じなので、文字数モデルは『同じくらい』と見積もる",
           abs(char_ratio - 1.0) < 0.01, f"{char_ratio:.3f} 倍")
check_true("文字数モデルも実測（0.650倍）を当てられない", abs(char_ratio - actual_ratio) > 0.3)

throughput = [200 / sec for _, sec in BATCH]
check_true("バッチサイズを大きくするほどスループットが落ちる（CPU では GPU の常識が反転する）",
           throughput[0] > throughput[1] > throughput[2],
           " > ".join(f"{t:.1f}件/秒" for t in throughput))

# ---------------------------------------------------------------------------
# 3. 「正規化」の1つめ：文字の正規化 — S03 × S05
# ---------------------------------------------------------------------------
print("\n--- 3. 文字の正規化 ---")

check("全角の略語が半角小文字になる", normalize("ＭＦＡ"), "mfa")
check("全角のハイフンも NFKC でそろう", normalize("Ｗｉ－Ｆｉ"), "wi-fi")
check("全角空白を含む連続空白が1つに畳まれる", normalize("有給休暇 　の　申請"), "有給休暇 の 申請")
check("大文字は小文字になる", normalize("PASSWORD"), "password")

# ---------------------------------------------------------------------------
# 4. 事後フィルタで候補が枯れる — S07 × S03 × S04
# ---------------------------------------------------------------------------
print("\n--- 4. 絞り込みの位置 ---")

docs = load_docs()
queries, qrels = load_queries(), load_qrels()
docs_by_id = {d.doc_id: d for d in docs}
chunks_fixed = chunk_all(docs, "fixed", size=400, overlap=80)
lex_fixed = LexicalIndex().build(chunks_fixed)
lex_heading = LexicalIndex().build(chunk_all(docs, "heading", max_chars=600))

for label, idx in (("fixed(400/80)", lex_fixed), ("heading(600)", lex_heading)):
    pre = filter_run(idx, queries, qrels, docs_by_id, k=10, post=False)
    post = filter_run(idx, queries, qrels, docs_by_id, k=10, post=True)
    print(f"  bm25 / {label}: 事前 平均{pre['mean_hits']:.2f}件・ゼロ{int(pre['zero_hits'])}件"
          f"・Recall@10 {pre['recall']:.3f} / "
          f"事後 平均{post['mean_hits']:.2f}件・ゼロ{int(post['zero_hits'])}件"
          f"・Recall@10 {post['recall']:.3f}")
    check_true(f"{label}: 事後フィルタは返却件数が減る",
               pre["mean_hits"] > post["mean_hits"] + 1.0)
    check_true(f"{label}: 事後フィルタは Recall@10 が下がる",
               pre["recall"] > post["recall"])
    check_true(f"{label}: 事後フィルタはゼロヒットを増やす",
               post["zero_hits"] > pre["zero_hits"])

if SKIP_DENSE:
    print("\nSKIP_DENSE=1 のため 5〜8 の検証を飛ばします。")
    if failures:
        print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
        sys.exit(1)
    print("\n横断復習02（密ベクトルを除く）の検証はすべて成功しました。")
    sys.exit(0)

import numpy as np  # noqa: E402

from fusion_lab import COLLECTION  # noqa: E402
from hybrid_recover import build_conditions, run_all  # noqa: E402
from ragkit.dense import Embedder  # noqa: E402
from type_router import CANDIDATES, FALLBACK, TYPES, best_by_type, qids_by_type, routed_mean  # noqa: E402

_, _, lex, dense = build_indexes()

# ---------------------------------------------------------------------------
# 5. 「正規化」の2つめ：ベクトルの L2正規化と距離尺度 — S06 × S07
# ---------------------------------------------------------------------------
print("\n--- 5. ベクトルの正規化と距離尺度 ---")

vec = Embedder.encode_query("有給休暇の申請期限")
check_true("encode_query の出力は L2正規化されている",
           abs(float(np.linalg.norm(vec)) - 1.0) < 1e-4)
flagged = Embedder.get().encode("query: 有給休暇の申請期限", normalize_embeddings=False,
                                show_progress_bar=False)
check_true("normalize_embeddings=False でもノルムは 1 のまま（Normalize がモデルに内蔵）",
           abs(float(np.linalg.norm(flagged)) - 1.0) < 1e-4,
           f"||a||={float(np.linalg.norm(flagged)):.6f}")

ids, mat = load_vectors(dense)
mat = mat.astype("float64")
check("コレクションから読めたベクトル数", len(ids), len(chunks_fixed))
q = np.asarray(query_vector("有給休暇の申請期限"), dtype="float64")
dot = mat @ q
cos = dot / (np.linalg.norm(mat, axis=1) * float(np.linalg.norm(q)))
euc2 = np.sum((mat - q) ** 2, axis=1)
check_true("正規化済みなので 内積 == コサイン", float(np.max(np.abs(dot - cos))) < 1e-5)
check_true("正規化済みなので ユークリッド距離^2 == 2 - 2×内積",
           float(np.max(np.abs(euc2 - (2 - 2 * dot)))) < 1e-5)
top_dot = [ids[i] for i in np.argsort(-dot)[:10]]
check("コサインの上位10件は内積と一致", [ids[i] for i in np.argsort(-cos)[:10]], top_dot)
check("ユークリッドの上位10件も内積と一致", [ids[i] for i in np.argsort(euc2)[:10]], top_dot)

scale = 1.0 + (np.arange(len(mat)) % 5) * 0.5
skewed = mat * scale[:, None]
dot_s = skewed @ q
cos_s = dot_s / (np.linalg.norm(skewed, axis=1) * float(np.linalg.norm(q)))
check_true("長さがそろっていないベクトルに内積を使うと上位が変わる",
           [ids[i] for i in np.argsort(-dot_s)[:10]] != top_dot)
check("コサインは長さの影響を受けない", [ids[i] for i in np.argsort(-cos_s)[:10]], top_dot)

# ---------------------------------------------------------------------------
# 6. 673チャンクでは ef が効かない — S07
# ---------------------------------------------------------------------------
print("\n--- 6. ef を振っても何も起きない ---")

info = dense.client.get_collection(COLLECTION)
indexed = int(info.indexed_vectors_count or 0)
check("コレクションの点数", int(info.points_count), len(chunks_fixed))
check_true("HNSW グラフに載っていない（既定の indexing_threshold に届かない）",
           indexed < int(info.points_count), f"indexed={indexed} / points={info.points_count}")

answerable = [q for q in queries if q.type != "unanswerable"]
sweep = ann_recall_sweep(dense, answerable, k=10, efs=(4, 16, 128))
for ef, recall in sweep.items():
    check(f"ef={ef} の近似検索のリコール", recall, 1.0, 1e-9)

rep_ef4 = evaluate(EfIndex(dense, 4), queries, qrels, k=10, label="dense (ef=4)")
rep_ef128 = evaluate(EfIndex(dense, 128), queries, qrels, k=10, label="dense (ef=128)")
check_true("検索の Recall@10 も ef で変わらない",
           abs(rep_ef4.macro["recall"] - rep_ef128.macro["recall"]) < 1e-12,
           f"ef=4 {rep_ef4.macro['recall']:.3f} / ef=128 {rep_ef128.macro['recall']:.3f}")

# ---------------------------------------------------------------------------
# 7. 素朴なハイブリッドは単体に負ける — S08
# ---------------------------------------------------------------------------
print("\n--- 7. ハイブリッドの設定 ---")

reps = run_all(lex, dense, queries, qrels)
for name, rep in reps.items():
    print("  " + rep.summary())

r_bm25 = reps["bm25 単体"].macro["recall"]
r_dense = reps["dense 単体"].macro["recall"]
r_rrf50 = reps["rrf(候補50, rrf_k=60)"].macro["recall"]
r_rrf10 = reps["rrf(候補10, rrf_k=60)"].macro["recall"]
r_mm11 = reps["minmax(候補50, 1.0:1.0)"].macro["recall"]
r_mm31 = reps["minmax(候補50, 0.3:1.0)"].macro["recall"]
r_sum = reps["単純加算(候補50)"].macro["recall"]

check("bm25 単体の Recall@10", r_bm25, 0.763, 0.02)
check("dense 単体の Recall@10", r_dense, 0.783, 0.02)
check("rrf(候補50, rrf_k=60) の Recall@10", r_rrf50, 0.762, 0.02)
check("rrf(候補10, rrf_k=60) の Recall@10", r_rrf10, 0.795, 0.02)
check("minmax(1.0:1.0) の Recall@10", r_mm11, 0.796, 0.02)
check("minmax(0.3:1.0) の Recall@10", r_mm31, 0.797, 0.02)
check_true("素朴なハイブリッド（候補50・rrf_k=60）は密ベクトル単体に負ける",
           r_rrf50 < r_dense, f"{r_rrf50:.3f} < {r_dense:.3f}")
check_true("候補数を10に絞ると単体を上回る", r_rrf10 > r_dense, f"{r_rrf10:.3f} > {r_dense:.3f}")
check_true("弱い側の重みを下げても単体を上回る", r_mm31 > r_dense, f"{r_mm31:.3f} > {r_dense:.3f}")

a_bm25 = reps["bm25 単体"].by_type["abbrev"]["recall"]
a_rrf50 = reps["rrf(候補50, rrf_k=60)"].by_type["abbrev"]["recall"]
a_mm31 = reps["minmax(候補50, 0.3:1.0)"].by_type["abbrev"]["recall"]
check("rrf(候補50) の略語クエリ Recall@10", a_rrf50, 0.143, 0.03)
check("minmax(0.3:1.0) の略語クエリ Recall@10", a_mm31, 0.303, 0.03)
check_true("素朴なハイブリッドは略語クエリで BM25 単体より悪化する（混ぜて悪くなる実例）",
           a_rrf50 < a_bm25, f"{a_rrf50:.3f} < {a_bm25:.3f}")

conditions = build_conditions(lex, dense)
overlap: list[float] = []
for qq in answerable[:30]:
    top_sum = [h.chunk_id for h in conditions["単純加算(候補50)"].search(qq.text, k=10)]
    top_lex = [h.chunk_id for h in lex.search(qq.text, k=10)]
    overlap.append(len(set(top_sum) & set(top_lex)) / max(len(top_lex), 1))
mean_overlap = sum(overlap) / len(overlap)
check_true("単純加算の上位10件は BM25 単体とほぼ同じ（密ベクトル側が効いていない）",
           mean_overlap > 0.75, f"平均一致率 {mean_overlap:.3f}")
check_true("単純加算の Recall@10 も BM25 単体とほぼ同じ",
           abs(r_sum - r_bm25) < 0.03, f"{r_sum:.3f} vs {r_bm25:.3f}")

# ---------------------------------------------------------------------------
# 8. 型別ルーティングのオラクル — S08 × S02
# ---------------------------------------------------------------------------
print("\n--- 8. 型別ルーティング ---")

groups = qids_by_type(reps, queries)
check("略語クエリの件数", len(groups["abbrev"]), 20)
check("複数条件クエリの件数", len(groups["multi_condition"]), 12)

choice = best_by_type(reps, groups)
expected = routed_mean(reps, groups, choice)
routed = TypeRoutedRetriever({t: conditions[n] for t, n in choice.items()},
                             default=conditions[FALLBACK],
                             type_of={q.text: q.type for q in queries})
rep_routed = evaluate(routed, queries, qrels, k=10, label="型別ルーティング")
best_fixed = max(CANDIDATES, key=lambda n: reps[n].macro["recall"])
print(f"  型別の選択: { {t: choice[t] for t in TYPES} }")
print(f"  期待値 {expected:.3f} / 実測 {rep_routed.macro['recall']:.3f} / "
      f"固定設定の最良 [{best_fixed}] {reps[best_fixed].macro['recall']:.3f}")
check_true("per_query から計算した期待値と、実際に検索して測った値が一致する",
           abs(expected - rep_routed.macro["recall"]) < 1e-9)
check_true("型ごとに最良を選べば、固定設定の最良を下回らない",
           rep_routed.macro["recall"] >= reps[best_fixed].macro["recall"] - 1e-9)
check_true("型によって選ばれる条件が違う（1つの設定が全型で最良にはならない）",
           len(set(choice.values())) >= 2, str(sorted(set(choice.values()))))

train = {t: qids[0::2] for t, qids in groups.items()}
test = {t: qids[1::2] for t, qids in groups.items()}
check("学習側に回る複数条件クエリの件数", len(train["multi_condition"]), 6)
choice_train = best_by_type(reps, train)
train_ids = [qid for qs in train.values() for qid in qs]
test_ids = [qid for qs in test.values() for qid in qs]
fixed_train = max(CANDIDATES, key=lambda n: subset_mean(reps[n], train_ids))
gain_train = routed_mean(reps, train, choice_train) - subset_mean(reps[fixed_train], train_ids)
gain_test = routed_mean(reps, test, choice_train) - subset_mean(reps[fixed_train], test_ids)
print(f"  学習側の改善 {gain_train:+.3f} / 検証側の改善 {gain_test:+.3f}")
check_true("学習側では必ず改善して見える（そこで選んだのだから当然）", gain_train >= -1e-9,
           f"学習側 {gain_train:+.3f} / 検証側 {gain_test:+.3f}"
           "（検証側の数字が、実際に期待してよい改善幅です）")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\n横断復習02の検証はすべて成功しました。")
