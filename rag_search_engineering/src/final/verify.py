#!/usr/bin/env python3
"""最終プロジェクト（検索基盤）の自己検証。

検証すること
  1. 再利用している部品がすべて読み込めること（新規実装を増やしていないこと）
  2. 設計が凍結されていること（コーパス・チャンク・公開範囲・採用構成）
  3. 権限が fail-closed で、全クエリ × 全役割の混入が 0 であること
  4. 同義語展開が略語クエリだけを動かし、他の型を壊していないこと
  5. 構成を変えたら合成カセットの鍵が変わること（＝作り直しが要ること）
  6. 判定が6つのうち想定した2つに収まり、失敗が3層に分かれること
  7. レイテンシ予算・コスト試算・検知できる悪化幅の算術が合うこと
  8. ログが取り込み口でマスクされ、冪等であること
  9. 提出物のテンプレートがそろっていること
 10. 切り替えの手順が実際に回ること（使い捨てコレクション・最後に削除）
 11. リランク段を足しても権限が漏れないこと（少数クエリのみ）

APIキーは不要。10・11 は `SKIP_DENSE=1` で飛ばせる（Qdrant とリランカを使うため）。
期待値と一致しなければ非0で終了する（人が出力を読んで判断しない）。

  docker compose exec app python src/final/verify.py
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import evaluate as ev  # noqa: E402
import final_cassette as mc  # noqa: E402
from reuse import ROOT, SOURCES, access, cost, lab, mask, ops, plan, sess  # noqa: E402
from search_platform import (  # noqa: E402
    ADOPTED,
    BASELINE,
    LOG_SALT,
    MEMBER,
    SearchPlatform,
    budget_candidates,
)

from ragkit.corpus import load_queries  # noqa: E402
from ragkit.llm import FixtureClient, StubClient  # noqa: E402

SKIP_DENSE = os.environ.get("SKIP_DENSE") == "1"
failures: list[str] = []

REQUIRED_DOCS = {
    "search_design.md": ["## 2. 決定事項", "## 3. 凍結した条件", "## 4. 権限モデル",
                         "## 6. 再現手順"],
    "evaluation_report.md": ["## 1. 測定した条件", "## 3. 権限の検査",
                             "## 4. 失敗の3層分類", "## 6. 測っていないこと"],
    "runbook.md": ["## 2. 再索引", "## 3. 切り替えと切り戻し", "## 4. 障害時",
                   "## 5. 監視と閾値"],
    "cost_estimate.md": ["## 2. 保存", "## 3. 計算", "## 4. 運用の選択肢と費用"],
    "review_checklist.md": ["## 2. 権限", "## 3. 評価", "## 5. 引き継ぎ"],
}


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'OK' if cond else 'NG'}] {label}" + (f" — {detail}" if detail else ""))
    if not cond:
        failures.append(label)


def near(a: float, b: float, tol: float = 0.02) -> bool:
    return abs(a - b) <= tol


def finish() -> None:
    if failures:
        print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
        sys.exit(1)
    print("\n最終プロジェクトの検証はすべて成功しました。")
    sys.exit(0)


# ---------------------------------------------------------------------------
# 1. 再利用の棚卸し
# ---------------------------------------------------------------------------
print("--- 1. 再利用している部品 ---")
check("借りている部品が 12 件そろっている", len(SOURCES) == 12, f"{len(SOURCES)} 件")
missing = [path for path, _why in SOURCES.values() if not (ROOT / path).exists()]
check("参照先のファイルがすべて存在する", not missing, f"{missing}")
check("権限・同義語・後処理・運用の実装を新規に書いていない",
      hasattr(access, "AccessAwareRetriever") and hasattr(lab, "SynonymRetriever")
      and hasattr(ops, "switch_alias"))

# ---------------------------------------------------------------------------
# 2〜7. 測定（レポートを1回作って、その中身を検査する）
# ---------------------------------------------------------------------------
data = ev.build_report()
corpus, ret, perm, ans, ope = (data["corpus"], data["retrieval"], data["permission"],
                               data["answers"], data["operations"])

print("\n--- 2. 設計の凍結 ---")
check("コーパスは 301 文書・120 クエリ・回答可能 110 件・判定データ 622 件",
      (corpus["docs"], corpus["queries"], corpus["answerable"], corpus["qrels"])
      == (301, 120, 110, 622), f"{corpus}")
check("公開範囲は all 297 / manager 4",
      corpus["visibility"] == {"all": 297, "manager": 4}, f"{corpus['visibility']}")
check("採用構成は fixed(400/80) / 上位5件 / コンテキスト2000字",
      (ADOPTED.chunk_method, ADOPTED.chunk_size, ADOPTED.chunk_overlap,
       ADOPTED.top_k, ADOPTED.max_chars) == ("fixed", 400, 80, 5, 2000))
check("基準線は同義語展開だけを外した構成（他は1つも変えない）",
      BASELINE.synonyms is False and ADOPTED.synonyms is True
      and replace(BASELINE, name=ADOPTED.name, synonyms=True) == ADOPTED)
check("引用の母集合はコンテキスト内に絞ってある（厳しい方に倒す）",
      ADOPTED.strict_citations is True)

print("\n--- 3. 権限 ---")
raised = False
try:
    access.allowed_visibility("intern")
except PermissionError:
    raised = True
check("未知の役割は検索せずに止まる（fail-closed）", raised)
check("member の許可リストは all だけ", access.visibility_filter(MEMBER) == {"visibility": ["all"]})

platform = SearchPlatform(ADOPTED, client=StubClient())
probe = access.probe_queries()[0]
plain = platform.base.search(probe.text, k=10)
empty_dict = platform.base.search(probe.text, k=10, filters={})
check("空の辞書はフィルタ無しと同じ（善意の実装が fail-open になる）",
      [h.chunk_id for h in plain] == [h.chunk_id for h in empty_dict])
check("フィルタ無しでは制限文書が混入する（プローブで再現できる）",
      len(access.leaked_hits(plain, MEMBER)) >= 1,
      f"{len(access.leaked_hits(plain, MEMBER))} 件")

rows = perm["rows"]
check(f"全 {perm['n_queries']} クエリ × 役割で、事前フィルタの混入は 0 件",
      rows["事前フィルタ（member）"]["leaked_hits"] == 0
      and rows["事前フィルタ（manager）"]["leaked_hits"] == 0, f"{rows}")
check("事後フィルタも混入は 0（ただし取りこぼす）",
      rows["事後フィルタ（member）"]["leaked_hits"] == 0)
check("事後フィルタは事前フィルタより結果が痩せる（k未満のクエリが増える）",
      rows["事後フィルタ（member）"]["short"] >= rows["事前フィルタ（member）"]["short"],
      f"事後 {rows['事後フィルタ（member）']['short']} 件 / "
      f"事前 {rows['事前フィルタ（member）']['short']} 件")
check("フィルタ無しは混入する（比較用の条件が実際に危ないことを確認する）",
      rows["フィルタ無し（member 相当）"]["leaked_hits"] >= 1)

print("\n--- 4. 検索（同義語展開は略語だけを動かす）---")
base_m, final_m = ret[BASELINE.name]["macro"], ret[ADOPTED.name]["macro"]
base_t, final_t = ret[BASELINE.name]["by_type"], ret[ADOPTED.name]["by_type"]
no_filter = ret["final-v1（権限フィルタ無し・比較用）"]["macro"]
check("基準線の Recall@10 が 0.763", near(base_m["recall"], 0.763), f"{base_m['recall']:.3f}")
check("基準線の略語クエリ Recall@10 が 0.182", near(base_t["abbrev"], 0.182, 0.03),
      f"{base_t['abbrev']:.3f}")
check("評価対象は回答可能な 110 クエリ", base_m["n"] == 110 and final_m["n"] == 110)
check("同義語展開で略語クエリが大きく上がる（0.182 → 0.873 の実測に整合）",
      final_t["abbrev"] > base_t["abbrev"] and final_t["abbrev"] >= 0.40,
      f"{base_t['abbrev']:.3f} → {final_t['abbrev']:.3f}")
worse = [t for t in base_t if final_t[t] < base_t[t] - 1e-9]
check("他のクエリ型を1つも壊していない", not worse, f"下がった型: {worse}")
fired = [q for q in load_queries() if lab.expand_query(q.text) != q.text]
check("展開が発火するのは略語クエリだけ", sorted({q.type for q in fired}) == ["abbrev"],
      f"{len(fired)} 件が発火")
check("権限フィルタを入れても Recall@10 は下がらない（適合文書は制限文書に無い）",
      final_m["recall"] >= no_filter["recall"] - 1e-9,
      f"フィルタあり {final_m['recall']:.3f} / 無し {no_filter['recall']:.3f}")

print("\n--- 5. 合成カセット（条件を変えたら作り直す）---")
stats = mc.build()
check("1本のカセットに 4 条件ぶんの鍵が入る（120 本以上・480 本以下）",
      120 <= stats["keys"] <= 480, f"{stats['keys']} 本 / 条件 {stats['conditions']} 通り")
check("同義語展開で鍵が変わったクエリがある", stats["changed_by_synonyms"] >= 1,
      f"{stats['changed_by_synonyms']} 件")
misses, probed = mc.miss_count(platform)
check("新構成のプロンプトは古いカセット（answers_v1）に当たらないものがある",
      misses >= 1, f"{misses}/{probed} 件が KeyError")
keyerror = False
try:
    FixtureClient("answers_v1").complete("system", "登録していないプロンプト")
except KeyError:
    keyerror = True
check("登録外の入力は既定応答で埋めずに例外になる", keyerror)

print("\n--- 6. 回答と失敗の3層分類 ---")
for name, row in ans.items():
    v, y = row["verdicts"], row["layers"]
    print(f"    {name:<12} ok={v['ok']} abstained={v['abstained']} / "
          f"層 成功{y['ok']} コーパス{y['corpus']} 検索{y['retrieval']} 生成{y['generation']}")
base_v, final_v = ans[BASELINE.name]["verdicts"], ans[ADOPTED.name]["verdicts"]
base_y, final_y = ans[BASELINE.name]["layers"], ans[ADOPTED.name]["layers"]
check("判定は ok と abstained だけになる（欠陥を仕込んでいないカセットのため）",
      all(v == 0 for k, v in final_v.items() if k not in ("ok", "abstained")), f"{final_v}")
check("判定の合計はクエリ数と一致する", sum(final_v.values()) == 120)
check("コーパス起因は回答不能の 10 件", final_y["corpus"] == 10, f"{final_y['corpus']} 件")
check("層の合計はクエリ数と一致する", sum(final_y.values()) == 120)
improved = final_v["ok"] > base_v["ok"] or final_y["retrieval"] < base_y["retrieval"]
check("同義語展開で成功が増えるか、検索起因の失敗が減る", improved,
      f"ok {base_v['ok']} → {final_v['ok']} / 検索起因 {base_y['retrieval']} → "
      f"{final_y['retrieval']}")
check("成功件数は回答可能な 110 件を超えない", final_v["ok"] <= 110)

print("\n--- 7. 予算・コスト・検知できる幅 ---")
budget = ope["budget"]
check("予算 500ms・1段目 20ms からの逆算は候補 12 件", budget_candidates() == 12,
      f"{budget_candidates()} 件")
check("予算をすべてリランクに使えば 13 件（引き当て方で答えが動く）",
      plan.candidates_for_budget(500) == 13)
check("最小の測定点に届かない予算では候補 0（リランクを入れる余地が無い）",
      plan.candidates_for_budget(300) == 0)
check("測定範囲より広い予算は外挿しない（頭打ちにする）",
      plan.candidates_for_budget(9999) == 100)
check("採用構成の候補数は予算の上限を超えていない",
      ADOPTED.rerank_candidates <= budget_candidates())

c = ope["cost"]
check("10万チャンクの全再索引は 94.6 分", c["full_minutes"] == 94.6, f"{c['full_minutes']}")
check("日次1%の増分は 56.8 秒（全再索引の 100.0 分の1）",
      (c["daily_seconds"], c["ratio"]) == (56.8, 100.0), f"{c['daily_seconds']} / {c['ratio']}")
check("本文はベクトルの 0.54 倍（容量の主役はベクトル）", c["text_ratio"] == 0.54,
      f"{c['text_ratio']}")
check("Qdrant の indexing_threshold は既定 10000 KB", cost.INDEXING_THRESHOLD_KB == 10_000)

o = ope["observability"]
check("クエリログは 429 件・ゼロヒット率 2.3%・上位無クリック率 36.5%",
      (o["rows"], o["zero_hit_rate"], o["no_click_rate"]) == (429, 2.3, 36.5), f"{o}")
check("言い換え率は 0.375（v2 スキーマのサンプル）",
      abs(sess.reformulation_rate(sess.load_sample()) - 0.375) < 1e-9)
check("窓の大きさと検知できる最小の悪化幅（20→20.0% / 100→7.0% / 1000→3.6%）",
      (o["min_detectable"][20], o["min_detectable"][100], o["min_detectable"][1000])
      == (20.0, 7.0, 3.6), f"{o['min_detectable']}")
check("互角でも 10 回中 7 勝以上する確率は 0.171875（少数サンプルで勝敗を語らない）",
      abs(ops.tail_prob(10, 7) - 0.171875) < 1e-9)
check("20 回中 15 勝以上なら 0.020695 まで下がる",
      abs(ops.tail_prob(20, 15) - 0.020695) < 1e-6)

print("\n--- 8. ログ（取り込み口でのマスキング）---")
dirty = "yamada.taro@minato.example.co.jp の立替金 090-1234-5678 について"
result = platform.answer(MEMBER, dirty, "Q-LOG")  # クライアントはスタブ（判定は unparsable）
record = platform.log_record(MEMBER, dirty, result, latency_ms=31, request_id="req-0001",
                             ts="2026-08-15T09:12:00+09:00")
check("クエリ本文の PII は保存前に落ちる",
      "<EMAIL>" in record["query_text"] and "<PHONE>" in record["query_text"]
      and "@" not in record["query_text"], record["query_text"])
check("落とすと決めたフィールドは1つも残っていない",
      not ({"raw_ip", "user_agent", "answer_text"} & set(record)), f"{sorted(record)}")
check("利用者IDはハッシュ化されて保存される", record["user_id"] != MEMBER.user_id)
check("マスキングは冪等（再処理しても結果が変わらない）",
      mask.sanitize(record, salt=LOG_SALT) == record)
check("判定と権限は残す（後から集計し直すために要る）",
      record["verdict"] == result.verdict and record["user_role"] == MEMBER.role)

print("\n--- 9. 提出物のテンプレート ---")
for filename, markers in REQUIRED_DOCS.items():
    path = HERE / "docs" / filename
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    check(f"{filename} が存在する", bool(text))
    for marker in markers:
        check(f"{filename} に「{marker}」がある", marker in text)

report_md = ROOT / "reports" / "final_platform.md"
ev.OUT.mkdir(parents=True, exist_ok=True)
report_md.write_text(ev.to_markdown(data), encoding="utf-8")
check("評価レポートに権限の節がある", "## 2. 権限" in report_md.read_text(encoding="utf-8"))

if SKIP_DENSE:
    print("\nSKIP_DENSE=1 のため 10・11（Qdrant とリランカを使う検証）を飛ばします。")
    finish()

# ---------------------------------------------------------------------------
# 10. 切り替えの手順（使い捨てコレクション）
# ---------------------------------------------------------------------------
print("\n--- 10. 切り替えのリハーサル ---")
import runbook  # noqa: E402

drill = runbook.rehearse()
check("初回構築で 9 チャンクが入る", drill["first"]["upserted"] == 9, f"{drill['first']}")
check("同じ入力をもう一度流しても1点も書き換えない（冪等）",
      (drill["again"]["upserted"], drill["again"]["unchanged"]) == (0, 9), f"{drill['again']}")
check("改訂1件で書き換わるのは1チャンクだけ（増分更新）",
      (drill["incremental"]["upserted"], drill["incremental"]["unchanged"]) == (1, 8),
      f"{drill['incremental']}")
check("エイリアスが 旧 → 新 → 旧（切り戻し）と動く",
      (drill["alias"]["before"], drill["alias"]["after"], drill["alias"]["rolled_back"])
      == (runbook.BLUE, runbook.GREEN, runbook.BLUE), f"{drill['alias']}")
check("廃止した文書のチャンクが孤児として消える",
      (drill["pruned"]["orphans"], drill["pruned"]["deleted"], drill["pruned"]["remaining"])
      == (1, 1, 8), f"{drill['pruned']}")
check("使い捨てコレクションを後片付けした（本番名には触れていない）", drill["cleaned"])

# ---------------------------------------------------------------------------
# 11. リランク段（少数クエリのみ・全体評価は tools/bench_rerank.py で取る）
# ---------------------------------------------------------------------------
print("\n--- 11. リランク段（候補12・5クエリだけ）---")
staged_config = replace(ADOPTED, name="final-v1+rerank", rerank_candidates=12)
staged = SearchPlatform(staged_config, client=StubClient())
sample = [q for q in load_queries() if q.type in ("natural", "multi_condition")][:5]
subset_ok, desc_ok, leak_ok, changed = True, True, True, 0
for q in sample:
    pool = platform.retriever(MEMBER).search(q.text, k=12)
    after = staged.retrieve(MEMBER, q.text)
    subset_ok &= {h.chunk_id for h in after} <= {h.chunk_id for h in pool} and len(after) == 5
    desc_ok &= all(after[i].score >= after[i + 1].score for i in range(len(after) - 1))
    leak_ok &= not access.leaked_hits(after, MEMBER)
    changed += 1 if [h.chunk_id for h in after] != [h.chunk_id for h in pool[:5]] else 0
check("リランクは候補プールの外から持ってこない（部分集合・上位5件）", subset_ok)
check("リランク後はクロスエンコーダのスコアの降順に並ぶ", desc_ok)
check("リランク段を足しても混入は 0（権限フィルタが内側にあるため）", leak_ok)
check("リランクで上位5件の並びが変わるクエリがある", changed >= 1, f"{changed}/{len(sample)} 件")

finish()
