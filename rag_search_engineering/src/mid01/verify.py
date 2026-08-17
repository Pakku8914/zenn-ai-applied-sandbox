#!/usr/bin/env python3
"""中間プロジェクト01（社内FAQ検索）の自己検証。

  1. 基準線（bm25 / fixed）が記録どおりの値になること
  2. 失敗の分解が恒等式を満たし、型ごとに主因が反転していること
  3. チャンク方式は単独最良（parent_window）が存在するのに fixed を固定すること
  4. 検索方式の切り替えが Recall を上げ、同時に nDCG を下げること（副作用）
  5. 素朴なハイブリッドが単体に負け、候補数と重みで回復すること
  6. 順路 bm25 → dense → hybrid が単調に上がること
  7. 複数条件クエリはどの条件でも動かないこと（成果物④の根拠）
  8. 評価が決定的であること（同じ条件を2回走らせて同じ順位）
  9. 提出物テンプレートに必須項目がそろっていること

SKIP_DENSE=1 を付けると 4〜8（埋め込みモデルと Qdrant を使う検証）を飛ばす。
期待値と一致しなければ非0で終了する（人が出力を読んで判断しない）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))

from diagnose import main_cause, split_failures  # noqa: E402
from faq_search import (  # noqa: E402
    ADOPTED, BASE_METHOD, BASELINE, DENSE, build_chunks, build_dense, build_lexical,
    chunk_conditions, fusion_conditions,
)
from run_eval import measure, route_table  # noqa: E402

from ragkit.corpus import load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402

SKIP_DENSE = os.environ.get("SKIP_DENSE") == "1"
N_ANSWERABLE = 110
failures: list[str] = []

REQUIRED_DOCS = {
    "search_design.md": ["## 2. 決定事項", "棄却した選択肢", "## 3. 固定した条件", "## 5. 再現手順"],
    "tuning_log.md": ["## 1. 施策台帳", "## 2. 各施策の寄与", "## 3. 却下・保留の台帳",
                      "## 4. 動かなかったもの"],
    "next_actions.md": ["## 1. 残っている失敗の内訳", "## 2. 提案（優先度順）",
                        "## 3. やらないと決めたこと"],
}


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


queries, qrels = load_queries(), load_qrels()
chunks = build_chunks(BASE_METHOD)
lex = build_lexical(chunks)
reps: dict = {}

# ---------------------------------------------------------------------------
# 1. 基準線 — S02 × S05
# ---------------------------------------------------------------------------
print("--- 1. 基準線 ---")

measure(chunk_conditions(), reps, queries, qrels, 10,
        "段階1：チャンク方式を選ぶ（検索方式は BM25 に固定）")
base = reps[BASELINE].macro
check("基準線の評価対象クエリ数", int(base["n_queries"]), N_ANSWERABLE)
check("基準線の Recall@10", base["recall"], 0.763, 0.02)
check("基準線の nDCG@10", base["ndcg"], 0.713, 0.02)
check("基準線の MRR", base["mrr"], 0.765, 0.02)
check("基準線の P@10", base["precision"], 0.538, 0.02)

# ---------------------------------------------------------------------------
# 2. 失敗の分解 — Review01 の道具
# ---------------------------------------------------------------------------
print("\n--- 2. 失敗の分解 ---")

rep_deep = evaluate(lex, queries, qrels, k=100, label=f"{BASELINE} (k=100)")
rows = split_failures(reps[BASELINE], rep_deep)
for name, r in rows.items():
    print(f"  {name:<16} Recall@10={r['recall_k']:.3f} 順位不足={r['rank_gap']:.3f} "
          f"到達不足={r['reach_gap']:.3f} 主因={main_cause(r)}")

for name, r in rows.items():
    total = r["recall_k"] + r["rank_gap"] + r["reach_gap"]
    check_true(f"{name}: Recall@10 ＋ 順位不足 ＋ 到達不足 = 1", abs(total - 1.0) < 1e-9,
               f"{total:.9f}")
check("abbrev の到達不足", rows["abbrev"]["reach_gap"], 0.592, 0.03)
check("multi_condition の順位不足", rows["multi_condition"]["rank_gap"], 0.495, 0.03)
check("全体の Recall@100", rows["ALL"]["recall_deep"], 0.885, 0.02)
check("全体の到達不足", rows["ALL"]["reach_gap"], 0.115, 0.02)
check_true("abbrev の主因は到達側", main_cause(rows["abbrev"]).startswith("到達側"))
check_true("multi_condition の主因は順位側", main_cause(rows["multi_condition"]).startswith("順位側"))
check_true("全体では両者が打ち消し合って主因が決まらない（型別に降りる必要がある）",
           main_cause(rows["ALL"]).startswith("拮抗"),
           f"順位不足 {rows['ALL']['rank_gap']:.3f} / 到達不足 {rows['ALL']['reach_gap']:.3f}")

# ---------------------------------------------------------------------------
# 3. チャンク方式（統制変数の決め方） — S04
# ---------------------------------------------------------------------------
print("\n--- 3. チャンク方式 ---")

recalls = {m: reps[f"bm25 / {m}"].macro["recall"] for m in ("fixed", "sentence", "heading",
                                                            "parent_window")}
precisions = {m: reps[f"bm25 / {m}"].macro["precision"] for m in recalls}
check("bm25 / parent_window の Recall@10", recalls["parent_window"], 0.781, 0.02)
check("bm25 / heading の Recall@10", recalls["heading"], 0.668, 0.03)
check("bm25 / heading の P@10", precisions["heading"], 0.629, 0.03)
check_true("Recall だけを見れば parent_window が単独最良（それでも fixed に固定する）",
           max(recalls, key=recalls.get) == "parent_window",
           f"parent_window {recalls['parent_window']:.3f} > fixed {recalls['fixed']:.3f}")
check_true("heading は Recall 最低だが P@10 は最高（指標で結論が反転する）",
           min(recalls, key=recalls.get) == "heading"
           and max(precisions, key=precisions.get) == "heading")

# ---------------------------------------------------------------------------
# 9. 提出物テンプレート（密ベクトルが要らないのでここで確認する）
# ---------------------------------------------------------------------------
print("\n--- 9. 提出物テンプレート ---")

for filename, markers in REQUIRED_DOCS.items():
    path = HERE / "docs" / filename
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    check_true(f"{filename} が存在する", bool(text))
    for marker in markers:
        check_true(f"{filename} に「{marker}」がある", marker in text)

if SKIP_DENSE:
    print("\nSKIP_DENSE=1 のため 4〜8 の検証を飛ばします。")
    if failures:
        print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
        sys.exit(1)
    print("\n中間プロジェクト01（密ベクトルを除く）の検証はすべて成功しました。")
    sys.exit(0)

dense = build_dense(chunks)

# ---------------------------------------------------------------------------
# 4. 検索方式の切り替えと副作用 — S06 × S02
# ---------------------------------------------------------------------------
print("\n--- 4. 検索方式 ---")

measure({DENSE: dense}, reps, queries, qrels, 10,
        "段階2：検索方式を選ぶ（チャンク方式は fixed に固定）")
dn = reps[DENSE].macro
check("dense / fixed の Recall@10", dn["recall"], 0.783, 0.02)
check("dense / fixed の nDCG@10", dn["ndcg"], 0.661, 0.02)
check_true("検索方式の切り替えで Recall@10 は上がる", dn["recall"] > base["recall"],
           f"{dn['recall']:.3f} > {base['recall']:.3f}")
check_true("同じ切り替えで nDCG@10 は下がる（副作用）", dn["ndcg"] < base["ndcg"],
           f"{dn['ndcg']:.3f} < {base['ndcg']:.3f}")
check_true("略語クエリは密ベクトルが勝つ（到達不足に効いている）",
           reps[DENSE].by_type["abbrev"]["recall"] > reps[BASELINE].by_type["abbrev"]["recall"],
           f"{reps[DENSE].by_type['abbrev']['recall']:.3f} > "
           f"{reps[BASELINE].by_type['abbrev']['recall']:.3f}")
check_true("自然文クエリは BM25 が勝つ（片方に寄せると必ず何かを失う）",
           reps[BASELINE].by_type["natural"]["recall"] > reps[DENSE].by_type["natural"]["recall"],
           f"{reps[BASELINE].by_type['natural']['recall']:.3f} > "
           f"{reps[DENSE].by_type['natural']['recall']:.3f}")

# ---------------------------------------------------------------------------
# 5〜7. 統合方式・順路・動かないもの — S08
# ---------------------------------------------------------------------------
print("\n--- 5. 統合方式 ---")

measure(fusion_conditions(lex, dense), reps, queries, qrels, 10,
        "段階3：統合方式を選ぶ（束ねる検索器は段階2と同一）")
naive = reps["hybrid rrf(候補50, rrf_k=60)"].macro["recall"]
narrow = reps["hybrid rrf(候補10, rrf_k=60)"].macro["recall"]
even = reps["hybrid minmax(候補50, 1.0:1.0)"].macro["recall"]
adopted = reps[ADOPTED].macro

reverse = reps["hybrid minmax(候補50, 1.0:0.3)"].macro["recall"]

check("素朴なハイブリッド（候補50・rrf_k=60）の Recall@10", naive, 0.762, 0.02)
check("候補を10に絞った RRF の Recall@10", narrow, 0.795, 0.02)
check("min-max(1.0:1.0) の Recall@10", even, 0.796, 0.02)
check("min-max(1.0:0.3) の Recall@10（重みの向きを逆にした対照）", reverse, 0.778, 0.02)
check("採用条件 min-max(0.3:1.0) の Recall@10", adopted["recall"], 0.797, 0.02)
check("採用条件の nDCG@10", adopted["ndcg"], 0.680, 0.02)
check("採用条件の略語クエリ Recall@10", reps[ADOPTED].by_type["abbrev"]["recall"], 0.303, 0.03)
check_true("素朴に混ぜると密ベクトル単体に負ける", naive < dn["recall"],
           f"{naive:.3f} < {dn['recall']:.3f}")
check_true("候補数を絞ると単体を上回る", narrow > dn["recall"], f"{narrow:.3f} > {dn['recall']:.3f}")
best = max(reps.values(), key=lambda r: r.macro["recall"])
print(f"  全条件の最良は [{best.label}] {best.macro['recall']:.3f}")
check_true("採用条件は単体の最良（dense）を上回る", adopted["recall"] > dn["recall"],
           f"{adopted['recall']:.3f} > {dn['recall']:.3f}")
check_true("採用条件は素朴な統合を上回る", adopted["recall"] > naive,
           f"{adopted['recall']:.3f} > {naive:.3f}")
# 上位3条件（0.795 / 0.796 / 0.797）の差は 1クエリ（1/110 = 0.009）より小さい。
# 「どれが最良か」を競わせず、「この帯に入ったら差は無い」と読むための検査。
spread = max(narrow, even, adopted["recall"]) - min(narrow, even, adopted["recall"])
check_true("上位3条件の差は1クエリ分より小さい（順位を競っても意味がない）",
           spread < 1 / N_ANSWERABLE, f"広がり {spread:.3f} < {1 / N_ANSWERABLE:.3f}")

print("\n--- 6. 順路 ---")
route_table(reps)
check_true("順路が単調に上がる（0.763 → 0.783 → 0.797）",
           base["recall"] < dn["recall"] < adopted["recall"])
check_true("採用条件の nDCG@10 は基準線より低い（Recall と引き換え）",
           adopted["ndcg"] < base["ndcg"], f"{adopted['ndcg']:.3f} < {base['ndcg']:.3f}")
gain = adopted["recall"] - base["recall"]
check_true("基準線からの改善が「2クエリ分」より大きい（誤差と区別できる）",
           gain > 2 / N_ANSWERABLE, f"{gain:+.3f} > {2 / N_ANSWERABLE:.3f}")

print("\n--- 7. 動かないもの ---")
multi = {name: rep.by_type["multi_condition"]["recall"] for name, rep in reps.items()}
for name, v in multi.items():
    print(f"  {name:<32} multi_condition Recall@10 = {v:.3f}")
check_true("複数条件クエリはどの条件でも 0.40〜0.52 の帯から出ない（設定選択では動かない）",
           all(0.40 <= v <= 0.52 for v in multi.values()),
           f"最小 {min(multi.values()):.3f} / 最大 {max(multi.values()):.3f}")
check_true("複数条件クエリの主因は順位側なので、統合方式では解けない",
           main_cause(rows["multi_condition"]).startswith("順位側"))

# ---------------------------------------------------------------------------
# 8. 決定性 — 成果物③の前提
# ---------------------------------------------------------------------------
print("\n--- 8. 決定性 ---")

sample = [q for q in queries if q.type != "unanswerable"][:5]
conds = fusion_conditions(lex, dense)
same = all(
    [h.chunk_id for h in conds[ADOPTED].search(q.text, k=10)]
    == [h.chunk_id for h in conds[ADOPTED].search(q.text, k=10)]
    for q in sample
)
check_true("同じクエリを2回検索すると同じ順位になる", same, f"{len(sample)} クエリで確認")
rerun = evaluate(conds[ADOPTED], queries, qrels, k=10, label=ADOPTED)
check_true("同じ条件を2回評価すると同じ Recall@10 になる",
           abs(rerun.macro["recall"] - adopted["recall"]) < 1e-12,
           f"{rerun.macro['recall']:.6f} vs {adopted['recall']:.6f}")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\n中間プロジェクト01の検証はすべて成功しました。")
