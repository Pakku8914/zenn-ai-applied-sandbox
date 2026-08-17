#!/usr/bin/env python3
"""セッション6の自己検証：埋め込みの前提（prefix・正規化・入力長）と密ベクトル検索の基準線。

モデルのダウンロードが必要なため、SKIP_DENSE=1 を付けると飛ばせる。
埋め込みの再計算を増やさないよう、一度作ったコレクションは再利用する。
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

if os.environ.get("SKIP_DENSE") == "1":
    print("SKIP_DENSE=1 のため密ベクトル検索の検証を飛ばします。")
    sys.exit(0)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logging.getLogger("transformers").setLevel(logging.ERROR)  # 長文入力の警告を抑える

import numpy as np  # noqa: E402

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.dense import VECTOR_SIZE, DenseIndex, Embedder  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402

COLLECTION = "minato_docs_fixed"
failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


# --- 埋め込みの基本性質 -----------------------------------------------------
vec = Embedder.encode_query("有給休暇の申請期限")
check("次元が固定値と一致", vec.shape[0] == VECTOR_SIZE, f"{vec.shape[0]} == {VECTOR_SIZE}")
check("L2正規化されている", abs(float(np.linalg.norm(vec)) - 1.0) < 1e-4,
      f"norm={float(np.linalg.norm(vec)):.6f}")

# 略語と正式名称が近いこと（これが密ベクトル検索が略語に強い理由）
v_formal = Embedder.encode_passages(["有給休暇の申請手続き"])[0]
v_abbrev = Embedder.encode_query("年休の手続き")
v_unrelated = Embedder.encode_passages(["駐車場の月額利用料"])[0]
sim_abbrev = float(np.dot(v_abbrev, v_formal))
sim_unrelated = float(np.dot(v_abbrev, v_unrelated))
check("略語と正式名称の類似度 > 無関係な文書との類似度",
      sim_abbrev > sim_unrelated, f"{sim_abbrev:.3f} > {sim_unrelated:.3f}")

# prefix の効果は「1組の類似度」では測れない（類似度は prefix 無しの方が高く出ることもある）。
# 検索全体の順位で測る必要がある。実測は tools/bench_prefix.py を参照。
model = Embedder.get()
raw_q = model.encode("年休の手続き", normalize_embeddings=True)
raw_p = model.encode("有給休暇の申請手続き", normalize_embeddings=True)
check("prefix の有無で埋め込みが変わる（同一ではない）",
      float(np.dot(raw_q, v_abbrev)) < 0.999,
      f"prefix なし同士の内積={float(np.dot(raw_q, raw_p)):.3f} / prefix あり={sim_abbrev:.3f}")

# 単一ペアでは prefix なしの方が「高く出る」。この逆転がセッション6の演習の入口。
# 数字が大きい方が良い、と読んではいけないことを固定しておく。
check("単一ペアの類似度では prefix なしの方が高く出る（絶対値で判断してはいけない）",
      float(np.dot(raw_q, raw_p)) > sim_abbrev,
      f"prefix なし={float(np.dot(raw_q, raw_p)):.3f} > prefix あり={sim_abbrev:.3f}")

# --- 正規化と距離尺度の対応 -------------------------------------------------
# 正規化済みなら 内積 = コサイン、ユークリッド距離^2 = 2 - 2×内積。
# 壊れるのは「正規化していないのに内積を使う」組み合わせだけ。
#
# 罠：このモデルは Normalize を最終段に内蔵しているため、
# normalize_embeddings=False を渡しても正規化は外れない（フラグが素通りする）。
modules = [type(m).__name__ for m in model]
check("モデルの最終段が Normalize である（正規化はモデルに内蔵されている）",
      modules[-1] == "Normalize", " → ".join(modules))
flagged = model.encode("query: 年休の手続き", normalize_embeddings=False,
                       show_progress_bar=False)
check("normalize_embeddings=False を渡しても正規化は外れない",
      abs(float(np.linalg.norm(flagged)) - 1.0) < 1e-4,
      f"||a||={float(np.linalg.norm(flagged)):.6f}")

# 生のプーリング出力を見るには Normalize を外したモデルを組み直すしかない。
from sentence_transformers import SentenceTransformer  # noqa: E402

pooled = SentenceTransformer(modules=list(model)[:2]).encode(
    ["query: 年休の手続き", "passage: 有給休暇の申請手続き"], show_progress_bar=False)
n0 = float(np.linalg.norm(pooled[0]))
n1 = float(np.linalg.norm(pooled[1]))
dot_unnorm = float(np.dot(pooled[0], pooled[1]))
cos_unnorm = dot_unnorm / (n0 * n1)
check("Normalize を外すとノルムは 1 ではない",
      n0 > 2.0 and n1 > 2.0, f"||a||={n0:.3f} / ||b||={n1:.3f}")
check("正規化前の内積はコサインと一致しない（1 を大きく超える）",
      dot_unnorm > 1.0, f"内積={dot_unnorm:.3f} / コサイン={cos_unnorm:.3f}")
check("正規化前のコサイン == 正規化後の内積",
      abs(cos_unnorm - sim_abbrev) < 1e-3, f"{cos_unnorm:.6f} ≈ {sim_abbrev:.6f}")
euclid2 = float(np.sum((v_abbrev - v_formal) ** 2))
check("正規化済みなら ユークリッド距離^2 == 2 - 2×内積",
      abs(euclid2 - (2 - 2 * sim_abbrev)) < 1e-4,
      f"{euclid2:.6f} ≈ {2 - 2 * sim_abbrev:.6f}")

# --- 最大入力長を超えた入力は黙って切り捨てられる ---------------------------
limit = int(model.max_seq_length)
check("モデルの最大入力長は 512 トークン", limit == 512, f"max_seq_length={limit}")

long_prefix = "みなと商事の社内規程について説明します。" * 200  # 20字 × 200 = 4,000字
n_tokens = len(model.tokenizer(f"passage: {long_prefix}")["input_ids"])
check("4,000字の入力は最大入力長を超える", n_tokens > limit, f"{n_tokens} > {limit}")

v_tail_a, v_tail_b = Embedder.encode_passages([
    long_prefix + "最後に、駐車場の月額利用料は経費精算の対象外です。",
    long_prefix + "最後に、有給休暇の申請は3営業日前までに行ってください。",
])
check("入力長を超えた末尾は無視される（末尾違いの長文が同じベクトルになる）",
      float(np.dot(v_tail_a, v_tail_b)) > 0.9999,
      f"内積={float(np.dot(v_tail_a, v_tail_b)):.6f}")

# --- バッチサイズは速度のつまみであって精度のつまみではない -----------------
sample = ["有給休暇の申請手続き", "駐車場の月額利用料",
          "貸与PCが故障したときの連絡先", "多要素認証の設定方法"]
v_b1 = Embedder.encode_passages(sample, batch_size=1)
v_b8 = Embedder.encode_passages(sample, batch_size=8)
worst = min(float(np.dot(a, b)) for a, b in zip(v_b1, v_b8))
check("バッチサイズを変えてもベクトルは変わらない（変わるのは速度だけ）",
      worst > 0.999, f"最小内積={worst:.6f}")

# --- 密ベクトル検索の基準線 -------------------------------------------------
docs, queries, qrels = load_docs(), load_queries(), load_qrels()
chunks = chunk_all(docs, "fixed", size=400, overlap=80)
idx = DenseIndex(COLLECTION)
if not idx.client.collection_exists(COLLECTION):
    print("コレクションを作成します（1分程度かかります）")
    idx.build(chunks)
info = idx.client.get_collection(COLLECTION)
check("コレクションの点数がチャンク数と一致", info.points_count == len(chunks),
      f"{info.points_count} == {len(chunks)}")

# 索引の設定が埋め込みと食い違っていないか（次元違いは投入時にエラーになるが、
# 距離尺度の取り違えはエラーにならず順位だけが変わるので明示的に検査する）
vectors_cfg = info.config.params.vectors
if not hasattr(vectors_cfg, "size"):  # 名前付きベクトルの場合
    vectors_cfg = next(iter(vectors_cfg.values()))
cfg_distance = getattr(vectors_cfg.distance, "value", vectors_cfg.distance)
check("コレクションの設定が 384次元・COSINE",
      int(vectors_cfg.size) == VECTOR_SIZE and cfg_distance == "Cosine",
      f"size={vectors_cfg.size} / distance={cfg_distance}")

rep_dense = evaluate(idx, queries, qrels, k=10, label="dense / fixed")
rep_lex = evaluate(LexicalIndex().build(chunks), queries, qrels, k=10, label="bm25 / fixed")
print(f"\n{rep_lex.summary()}\n{rep_dense.summary()}")

check("密ベクトル検索の Recall@10 が 0.70 以上",
      rep_dense.macro["recall"] >= 0.70, f"{rep_dense.macro['recall']:.3f}")
check("略語クエリでは密ベクトル検索が BM25 に勝つ",
      rep_dense.by_type["abbrev"]["recall"] > rep_lex.by_type["abbrev"]["recall"],
      f"dense={rep_dense.by_type['abbrev']['recall']:.3f} > "
      f"bm25={rep_lex.by_type['abbrev']['recall']:.3f}")
# 逆に自然文クエリでは BM25 が勝つ。密ベクトル検索は BM25 の上位互換ではない
# （この非対称がセッション8のハイブリッド検索の存在理由になる）。
check("自然文クエリでは BM25 が密ベクトル検索に勝つ（万能ではない）",
      rep_lex.by_type["natural"]["recall"] > rep_dense.by_type["natural"]["recall"],
      f"bm25={rep_lex.by_type['natural']['recall']:.3f} > "
      f"dense={rep_dense.by_type['natural']['recall']:.3f}")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション6の検証はすべて成功しました。")
