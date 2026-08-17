#!/usr/bin/env python3
"""セッション17の自己検証：クエリログの集計・マスキング・還流・ドリフト検知。

  1. 合成クエリログ（429行）の集計値が固定シードから決まる値になること
  2. v1 スキーマ（9フィールド）では計算できない指標が特定できること
  3. マスキングが期待どおりに効き、**冪等**であること
  4. 本文を残さないモードにしても、規模と失敗シグナルの指標が1つも変わらないこと
  5. 層化サンプリングの配分と選ばれるケースが決定的であること
  6. 評価セットの重み付けを変えると数字が動くこと（0.968 / 0.948 / 0.914 / 0.763）
  7. 結果を残していないログからは還流できないこと（MissingFieldError）
  8. 判定データ（qrels）のマージが冪等で、既存の判定を上書きしないこと
  9. 合成した劣化シナリオをドリフト指標が捉えること
 10. 少数サンプルでは悪化を検知できないこと
 11. 打ち手の順位が「並べ方」で変わること

埋め込みモデルもリランカも Qdrant も使わない（CPU だけで数秒で終わる）。
期待値と一致しなければ非0で終了する。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from drift import (  # noqa: E402
    binom_tail_ge,
    compare,
    l1_distance,
    min_detectable_rate,
    simulate_regression,
    type_distribution,
)
from log_schema import (  # noqa: E402
    METRIC_REQUIREMENTS,
    V1_FIELDS,
    dropped_fields,
    stored_fields,
    unmeasurable,
)
from masking import (  # noqa: E402
    DIRTY_SAMPLE,
    hash_value,
    mask_text,
    pii_hits,
    sanitize,
    sanitize_log,
)
from metrics import cumulative_share, load_log, rows_by_type, summarize  # noqa: E402
from priority import (  # noqa: E402
    ACTIONS,
    answerable_rows,
    check_baselines,
    comparable,
    expected_gain,
    rank,
    traffic_rows,
)
from ragkit.corpus import load_qrels, load_queries  # noqa: E402
from reflow import (  # noqa: E402
    SAMPLE_LABELS,
    MissingFieldError,
    allocate_min_then_traffic,
    allocate_proportional,
    apply_labels,
    initial_eval_ids,
    label_tasks,
    merge_qrels,
    select_cases,
    select_head,
    type_counts,
    weighted_recall,
)
from sessions import load_sample, reformulation_rate, split_sessions, zero_hit_followup  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


log = load_log()
queries = load_queries()
s = summarize(log)

# --- 1. ログの実体 -----------------------------------------------------------
check("ログが 429 行・120 クエリ",
      s["rows"] == 429 and s["distinct_queries"] == 120,
      f"{s['rows']} 行 / {s['distinct_queries']} クエリ")
check("どの行も v1 の 9 フィールドだけを持つ",
      all(set(r) == set(V1_FIELDS) for r in log),
      f"{sorted(set(log[0]))}")

expected_types = {"natural": 345, "keyword": 30, "abbrev": 20,
                  "multi_condition": 12, "temporal": 12, "unanswerable": 10}
check("型別の行数が natural 345 / keyword 30 / abbrev 20 / multi 12 / temporal 12 / unans 10",
      rows_by_type(log) == expected_types, f"{rows_by_type(log)}")

zero = [r for r in log if r["n_results"] == 0]
check("ゼロヒットは 10 行（2.3%）",
      s["zero_hits"] == 10 and round(s["zero_hit_rate"] * 100, 1) == 2.3,
      f"{s['zero_hits']} 行 / {s['zero_hit_rate'] * 100:.1f}%")
check("ゼロヒットはすべて回答不能クエリで、スコアもクリックも無い",
      all(r["query_type"] == "unanswerable" and r["top_score"] == 0.0
          and r["clicked_rank"] is None for r in zero))
check("クリックは 266 行（62.0%）",
      s["clicked"] == 266 and round(s["click_rate"] * 100, 1) == 62.0,
      f"{s['clicked']} 行 / {s['click_rate'] * 100:.1f}%")
check("結果はあったがクリック無しは 153 行（419 行の 36.5%）",
      s["no_click"] == 153 and s["rows_with_results"] == 419
      and round(s["no_click_rate"] * 100, 1) == 36.5,
      f"{s['no_click']} / {s['rows_with_results']} = {s['no_click_rate'] * 100:.1f}%")

check("1回しか出ていないクエリが 84 件（ロングテール）",
      s["singleton_queries"] == 84, f"{s['singleton_queries']}")
cumulative = [cumulative_share(log, k) for k in (5, 10, 20, 36)]
check("上位 5/10/20/36 クエリの行数が 152/204/271/345",
      cumulative == [152, 204, 271, 345], f"{cumulative}")
check("上位10クエリで全体の 47.6% を占める",
      round(s["top10_share"] * 100, 1) == 47.6, f"{s['top10_share'] * 100:.1f}%")
check("管理職ロールの行が 93 行（21.7%）",
      s["manager_rows"] == 93 and round(s["manager_share"] * 100, 1) == 21.7,
      f"{s['manager_rows']} 行 / {s['manager_share'] * 100:.1f}%")
check("値の範囲が壊れていない（件数 3〜20・スコア 0.4〜0.9・レイテンシ 30〜480ms）",
      all((r["n_results"] == 0 or 3 <= r["n_results"] <= 20)
          and (r["top_score"] == 0.0 or 0.4 <= r["top_score"] <= 0.9)
          and 30 <= r["latency_ms"] <= 480 for r in log))

# --- 2. スキーマ -------------------------------------------------------------
check("落とすフィールドは raw_ip / user_agent / answer_text の3つ",
      dropped_fields() == ("raw_ip", "user_agent", "answer_text"), f"{dropped_fields()}")
check("保存するフィールドは 18 個", len(stored_fields()) == 18, f"{len(stored_fields())}")

expected_missing = {
    "言い換え率": ["session_id"],
    "権限起因のゼロヒット": ["filters"],
    "結果の再現": ["retriever", "index_version", "filters"],
    "回答判定の内訳": ["answer_verdict"],
}
check("v1 の 9 フィールドでは 4 つの指標が計算できない",
      unmeasurable(V1_FIELDS) == expected_missing, f"{unmeasurable(V1_FIELDS)}")
check("ゼロヒット率と上位無クリック率は v1 でも計算できる",
      "ゼロヒット率" not in unmeasurable(V1_FIELDS)
      and "上位無クリック率" not in unmeasurable(V1_FIELDS)
      and len(METRIC_REQUIREMENTS) == 8)

# --- 3. マスキング -----------------------------------------------------------
check("生のクエリから email / phone / employee_id を検出する",
      pii_hits(DIRTY_SAMPLE["query_text"]) == ["email", "phone", "employee_id"],
      f"{pii_hits(DIRTY_SAMPLE['query_text'])}")
masked = mask_text(DIRTY_SAMPLE["query_text"])
check("マスク結果が期待どおり",
      masked == "<EMAIL> の立替金 <PHONE> <EMPLOYEE_ID>", masked)
check("マスク済みの本文には PII パターンが残らない", pii_hits(masked) == [])
check("mask_text は冪等（2回かけても変わらない）", mask_text(masked) == masked)

cleaned = sanitize(DIRTY_SAMPLE, salt="2026-08-15")
check("sanitize が raw_ip / user_agent / answer_text を落とす",
      all(k not in cleaned for k in ("raw_ip", "user_agent", "answer_text")))
check("sanitize が権限コンテキスト（user_role）は残す",
      cleaned["user_role"] == "member" and cleaned["user_dept"] == "経理部")
check("sanitize が session_id / user_id を 16 桁のハッシュにする",
      len(cleaned["session_id"]) == 16 and len(cleaned["user_id"]) == 16
      and cleaned["user_id"] != DIRTY_SAMPLE["user_id"],
      f"{cleaned['user_id']}")
check("sanitize は冪等", sanitize(cleaned, salt="2026-08-15") == cleaned)
check("sanitize は入力を壊さない", "raw_ip" in DIRTY_SAMPLE)
check("同じ値は同じハッシュ・ソルトが違えば別のハッシュ",
      hash_value("u-1043", "2026-08-15") == hash_value("u-1043", "2026-08-15")
      and hash_value("u-1043", "2026-08-15") != hash_value("u-1043", "2026-08-16"))

hashed_log = sanitize_log(log, salt="2026-08-15", text_policy="hash")
check("本文を残さないモードでも規模と失敗シグナルの指標は1つも変わらない",
      summarize(hashed_log) == s)
check("本文を残さないモードでは本文が読めない",
      all(r["text"].startswith("qhash:") for r in hashed_log))
check("本番ログ 429 行の本文には PII パターンが1件も当たらない（合成コーパスのため）",
      sum(1 for r in log if pii_hits(r["text"])) == 0)

# --- 4. セッションと言い換え -------------------------------------------------
sample = load_sample()
check("v2 サンプルは 8 行・21 フィールド",
      len(sample) == 8 and all(len(r) == 21 for r in sample),
      f"{len(sample)} 行 / {len(sample[0])} フィールド")
check("30分で切ると 5 セッション", len(split_sessions(sample)) == 5,
      f"{len(split_sessions(sample))}")
check("言い換え率は 0.375", abs(reformulation_rate(sample) - 0.375) < 1e-9,
      f"{reformulation_rate(sample):.3f}")
check("ゼロヒット 2 件はどちらも言い換えが続いている",
      zero_hit_followup(sample) == (2, 2), f"{zero_hit_followup(sample)}")
sanitized_sample = sanitize_log(sample, salt="2026-08-15")
check("ハッシュ化しても言い換え率は変わらない",
      abs(reformulation_rate(sanitized_sample) - 0.375) < 1e-9)
check("サニタイズ後のフィールドは 19 個（3つ落として pii_state を足す）",
      all(len(r) == 19 for r in sanitized_sample), f"{len(sanitized_sample[0])}")

# --- 5. 層化サンプリング -----------------------------------------------------
rows = rows_by_type(log)
check("比例配分（n=20）は natural 16 / keyword 1 / abbrev 1 / multi 1 / temporal 1 / unans 0",
      allocate_proportional(20, rows) == {"natural": 16, "keyword": 1, "abbrev": 1,
                                          "multi_condition": 1, "temporal": 1,
                                          "unanswerable": 0},
      f"{allocate_proportional(20, rows)}")
check("最低2件保証（n=20）は natural 4 / keyword 4 / abbrev 3 / multi 3 / temporal 3 / unans 3",
      allocate_min_then_traffic(20, rows) == {"natural": 4, "keyword": 4, "abbrev": 3,
                                              "multi_condition": 3, "temporal": 3,
                                              "unanswerable": 3},
      f"{allocate_min_then_traffic(20, rows)}")

head = select_head(log, 20)
check("頻度上位20件はすべて自然文クエリ（層化しないと型が偏る）",
      set(type_counts(head, queries)) == {"natural"}, f"{type_counts(head, queries)}")

picked_prop = select_cases(log, 20, allocator="proportional")
expected_prop = [f"Q-{i:03d}" for i in range(1, 17)] + ["Q-037", "Q-067", "Q-087", "Q-099"]
check("比例配分で選ばれるケースが決定的", picked_prop == sorted(expected_prop),
      f"{picked_prop}")

picked_mt = select_cases(log, 20, allocator="min_then_traffic")
expected_mt = ["Q-001", "Q-002", "Q-003", "Q-004",
               "Q-037", "Q-038", "Q-039", "Q-040",
               "Q-067", "Q-068", "Q-069",
               "Q-087", "Q-088", "Q-089",
               "Q-099", "Q-100", "Q-101",
               "Q-111", "Q-112", "Q-113"]
check("最低2件保証で選ばれるケースが決定的", picked_mt == sorted(expected_mt), f"{picked_mt}")
check("ゼロヒットのある回答不能クエリが先に選ばれる",
      picked_mt[-3:] == ["Q-111", "Q-112", "Q-113"])

# --- 6. 評価セットの重み付け -------------------------------------------------
base_ids = initial_eval_ids(queries)
after_prop = sorted(set(base_ids) | set(picked_prop))
after_mt = sorted(set(base_ids) | set(picked_mt))
all_ids = [q.query_id for q in queries]
check("最初の評価セットは自然文とキーワードだけの 66 件", len(base_ids) == 66, f"{len(base_ids)}")
check("還流で 66 -> 69 件（比例配分）／66 -> 78 件（最低2件保証）",
      len(after_prop) == 69 and len(after_mt) == 78,
      f"{len(after_prop)} / {len(after_mt)}")

values = {
    "v1(66)": weighted_recall(type_counts(base_ids, queries)),
    "prop(69)": weighted_recall(type_counts(after_prop, queries)),
    "mt(78)": weighted_recall(type_counts(after_mt, queries)),
    "macro(120)": weighted_recall(type_counts(all_ids, queries)),
    "traffic(429)": weighted_recall(rows),
}
expected_values = {"v1(66)": 0.968, "prop(69)": 0.948, "mt(78)": 0.914,
                   "macro(120)": 0.763, "traffic(429)": 0.914}
check("同じ検索器でも重み付けで 0.968 / 0.948 / 0.914 / 0.763 / 0.914 に見える",
      all(abs(values[k] - expected_values[k]) < 0.0005 for k in expected_values),
      ", ".join(f"{k}={v:.3f}" for k, v in values.items()))
check("型を均等に見る 0.763 が最も厳しく、偏った評価セット 0.968 が最も甘い",
      values["macro(120)"] < values["mt(78)"] < values["prop(69)"] < values["v1(66)"])

# --- 7. 還流の配管 -----------------------------------------------------------
missing_raised = False
try:
    label_tasks(log[:3])
except MissingFieldError:
    missing_raised = True
check("結果を残していない v1 ログからは還流できない（MissingFieldError）", missing_raised)

tasks, ids, empty = label_tasks(sample)
check("v2 サンプルから 7 クエリを採番し、10 件の判定タスクを作る",
      len(ids) == 7 and len(tasks) == 10, f"{len(ids)} クエリ / {len(tasks)} タスク")
check("候補が1件も無いクエリは QL-001 と QL-004（ゼロヒットだった2件）",
      empty == ["QL-001", "QL-004"], f"{empty}")
check("採番はマスク後の本文で行う（評価セットに PII を持ち込まない）",
      any("<EMAIL>" in t["text"] for t in tasks)
      and all("@" not in t["text"] for t in tasks))

base_qrels = load_qrels()
labeled = apply_labels(tasks, SAMPLE_LABELS)
merged, conflicts = merge_qrels(base_qrels, labeled)
check("更新前の判定データは 110 クエリ / 622 判定",
      len(base_qrels) == 110 and sum(len(v) for v in base_qrels.values()) == 622,
      f"{len(base_qrels)} / {sum(len(v) for v in base_qrels.values())}")
check("還流後は 115 クエリ / 632 判定・衝突 0 件",
      len(merged) == 115 and sum(len(v) for v in merged.values()) == 632
      and not conflicts,
      f"{len(merged)} / {sum(len(v) for v in merged.values())} / 衝突 {len(conflicts)}")
check("同じ還流を2回流しても結果が変わらない（冪等）",
      merge_qrels(merged, labeled)[0] == merged)
check("不適合（grade 0）も判定として残す",
      merged["QL-002"] == {"DOC-0007": 2, "DOC-0004": 1, "DOC-0008": 0},
      f"{merged['QL-002']}")

qid0 = sorted(base_qrels)[0]
doc0 = sorted(base_qrels[qid0])[0]
current_grade = base_qrels[qid0][doc0]
bogus = [{"query_id": qid0, "doc_id": doc0, "grade": 0 if current_grade > 0 else 2}]
merged_bogus, conflicts_bogus = merge_qrels(base_qrels, bogus)
check("既存の判定と食い違う還流は上書きせず衝突として報告する",
      len(conflicts_bogus) == 1 and merged_bogus[qid0][doc0] == current_grade,
      f"{conflicts_bogus}")

# --- 8. ドリフト検知 ---------------------------------------------------------
after_log = simulate_regression(log)
diff = compare(log, after_log)
b = diff["after"]
check("劣化シナリオは 509 行・abbrev 100 行",
      b["rows"] == 509 and rows_by_type(after_log)["abbrev"] == 100,
      f"{b['rows']} 行 / abbrev {rows_by_type(after_log)['abbrev']} 行")
check("ゼロヒット率が 2.3% -> 9.8%",
      round(b["zero_hit_rate"] * 100, 1) == 9.8, f"{b['zero_hit_rate'] * 100:.1f}%")
check("クリック率は 62.0% -> 52.3% だが、クリック数は 266 のまま（分母が増えただけ）",
      round(b["click_rate"] * 100, 1) == 52.3 and diff["clicked_delta"] == 0,
      f"{b['click_rate'] * 100:.1f}% / クリック数の差 {diff['clicked_delta']}")
check("クエリ型分布の L1 距離が 0.2997",
      abs(diff["l1"] - 0.2997) < 0.0005, f"{diff['l1']:.4f}")
check("同じ分布どうしの距離は 0",
      l1_distance(type_distribution(log), type_distribution(log)) == 0.0)

# --- 9. 少数サンプルとアラート閾値 -------------------------------------------
check("互角でも 10 回中 7 勝以上する確率は 0.171875",
      abs(binom_tail_ge(10, 7, 0.5) - 0.171875) < 1e-9, f"{binom_tail_ge(10, 7, 0.5):.6f}")
check("20 回中 15 勝以上なら 0.020695 まで下がる",
      abs(binom_tail_ge(20, 15, 0.5) - 0.020695) < 1e-6, f"{binom_tail_ge(20, 15, 0.5):.6f}")

p0 = s["zero_hit_rate"]
rates = [min_detectable_rate(n, p0) for n in (20, 50, 100, 500, 1000)]
check("窓が大きいほど、検知できる悪化幅は小さくなる",
      all(a >= b2 for a, b2 in zip(rates, rates[1:])),
      ", ".join(f"{r * 100:.1f}%" for r in rates))
check("20 件の窓ではゼロヒット率が 10% 以上にならないと有意にならない",
      rates[0] >= 0.10, f"{rates[0] * 100:.1f}%")
check("1000 件の窓なら 6% 未満の悪化でも有意にできる",
      rates[-1] <= 0.06, f"{rates[-1] * 100:.1f}%")

# --- 10. 優先度マトリクス ----------------------------------------------------
actions = comparable()
check("土俵違いの打ち手（dense 基準）を検出できる",
      check_baselines() == ["rerank_only"], f"{check_baselines()}")
mixed_raised = False
try:
    rank(log, ACTIONS)
except ValueError:
    mixed_raised = True
check("基準の違う数字を混ぜて並べようとすると止まる", mixed_raised)

check("回答可能な行は 419 行・abbrev は 20 行（4.8%）",
      answerable_rows(log) == 419 and traffic_rows(log, ("abbrev",)) == 20,
      f"{traffic_rows(log, ('abbrev',))} / {answerable_rows(log)}")

by_gain = [a.action_id for a in rank(log, actions, key="gain")]
by_score = [a.action_id for a in rank(log, actions, key="score")]
safe = [a.action_id for a in rank(log, actions, key="score", exclude_side_effects=("高",))]
check("期待改善量で並べるとリランクが1位",
      by_gain == ["dense_rerank50", "hybrid_minmax", "syn_query", "syn_index",
                  "zero_hit_guide"], f"{by_gain}")
check("コストで割ると同義語展開が1位に入れ替わる",
      by_score == ["syn_query", "dense_rerank50", "syn_index", "hybrid_minmax",
                   "zero_hit_guide"], f"{by_score}")
check("副作用「高」を外すとリランクが消える",
      safe == ["syn_query", "syn_index", "hybrid_minmax", "zero_hit_guide"], f"{safe}")

gains = {a.action_id: expected_gain(log, a) for a in actions}
check("期待改善量が syn_query 0.0330 / syn_index 0.0278 / hybrid 0.0340 / rerank 0.0550",
      abs(gains["syn_query"] - 0.0330) < 0.0005
      and abs(gains["syn_index"] - 0.0278) < 0.0005
      and abs(gains["hybrid_minmax"] - 0.0340) < 0.0005
      and abs(gains["dense_rerank50"] - 0.0550) < 0.0005,
      ", ".join(f"{k}={v:.4f}" for k, v in gains.items()))
check("Recall では測れない打ち手の期待改善量は 0（別の指標で測る）",
      gains["zero_hit_guide"] == 0.0)

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション17の検証はすべて成功しました。")
