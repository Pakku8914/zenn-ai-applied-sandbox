#!/usr/bin/env python3
"""セッション8の自己検証：単体構成と複数体構成の比較が主張どおりになること。

本文（body / practice / solutions）に載せた出力・数値はここで検証している。
数値が変わる変更をしたときは、NG 行に出る実測値に合わせて本文を直すこと。
検証の前後で `tools/make_data.py` を走らせるので、データは初期状態に戻る。

    python src/session08/verify.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.models import Trajectory  # noqa: E402
from compare import (render_hops, render_missing, render_table,  # noqa: E402
                     render_tokens, row_of, run_all)
from conflict import STRATEGIES, lost_update, race  # noqa: E402
from conflict import render as render_conflict  # noqa: E402
from debug import audit_hops, first_loss, render_audit, save_traces  # noqa: E402
from ex_merge import render as render_merge  # noqa: E402
from ex_merge import rows as merge_rows  # noqa: E402
from ex_recover import render as render_recover  # noqa: E402
from ex_recover import rows as recover_rows  # noqa: E402
from ex_reviewer import render as render_reviewer  # noqa: E402
from ex_reviewer import rows as reviewer_rows  # noqa: E402
from privilege import SOLO_ALLOW, SPLIT_ALLOW, run_injected  # noqa: E402
from privilege import render as render_privilege  # noqa: E402
from report import expected_facts, render_expected  # noqa: E402
from runners import run_orchestrator  # noqa: E402
from sideeffects import reset_data  # noqa: E402

EXPECTED_TABLE = """方式 | 体数 | 手数 | 段数 | 定義 | 再送 | 項目 | 採点
単体 | 1 | 5 | 5 | 20 | 10 | 0 | 4/4
オーケストレータ（構造化） | 4 | 8 | 8 | 10 | 5 | 10 | 4/4
オーケストレータ（自由文） | 4 | 8 | 8 | 10 | 5 | 3 | 1/4
ハンドオフ（自分の成果だけ） | 4 | 8 | 8 | 10 | 5 | 8 | 3/4
ハンドオフ（畳んで渡す） | 4 | 8 | 8 | 10 | 5 | 18 | 4/4
ハンドオフ（相手の要求に合わせる） | 4 | 8 | 8 | 10 | 5 | 10 | 4/4
オーケストレータ（並列・構造化） | 5 | 9 | 7 | 8 | 4 | 10 | 4/4"""

EXPECTED_REPORT = """# 経費レポート（2026-08-15 時点）

## 区分別の合計
- 交通費: 7,600 円
- 出張旅費: 145,000 円
- 接待交際費: 120,000 円
- 備品: 12,800 円

## 総額
- 285,400 円（6 件）

## 規程違反の疑い
- 基準額 50,000 円以上で未承認の申請: 2 件
  - EXP-0002
  - EXP-0004
"""

EXPECTED_NOTICE = ("月次レポートを session08/report.md に保存しました。"
                   "総額は 285,400 円です。規程違反の疑いは 2 件です。")

EXPECTED_SUMMARY = """判定基準（規程から）: 50,000 円以上は事前承認が必要
  交通費: 7,600 円
  出張旅費: 145,000 円
  接待交際費: 120,000 円
  備品: 12,800 円
  総額: 285,400 円（6 件）
  規程違反の疑い: EXP-0002, EXP-0004（2 件）"""

EXPECTED_FREE_REPORT = """# 経費レポート（2026-08-15 時点）

## 区分別の合計
- （区分別の内訳は引き継がれませんでした）

## 総額
- 285,400 円（6 件）

## 規程違反の疑い
- （申請一覧または判定基準が引き継がれず、判定していません）
"""

EXPECTED_AUDIT_OWN = """方式=ハンドオフ（自分の成果だけ） 採点=3/4
区間 | 項目数 | 欠けた入力
collector→analyst | 3 | （なし）
analyst→writer | 4 | （なし）
writer→notifier | 1 | violations_count/violations
最初に落ちた区間: writer→notifier"""

EXPECTED_HOPS_OWN = """区間 | 項目数 | 渡した鍵
collector→analyst | 3 | expenses, policy_digest, threshold
analyst→writer | 4 | by_category, count, total, violations
writer→notifier | 1 | report_path"""

EXPECTED_HOPS_STRUCTURED = """区間 | 項目数 | 渡した鍵
親→analyst | 2 | expenses, threshold
親→writer | 5 | by_category, count, threshold, total, violations
親→notifier | 3 | report_path, total, violations_count"""

EXPECTED_CONFLICT = """やり方 | 予約行数 | 黒板の記録 | latest が指す値 | 試した回数
2体がそれぞれ予約する | 2 | 2 | みなと 14:00 | 2
2体が同じ枠を取りにいく | 0 | 2 | みなと 10:00（失敗） | 2
書くのは1体・latest() だけ見る | 0 | 3 | みなと 予約できず | 1
書くのは1体・read() で全候補を見る | 1 | 3 | みなと 11:00（確定） | 1"""

EXPECTED_PRIVILEGE = """構成 | ツール数 | 手数 | 注入に従えた操作 | 拒否された操作 | 送信件数 | 宛先
単体（6ツール） | 6 | 4 | get_employee, send_message | なし | 1 | external@example.com
分割（収集係は3ツール） | 3 | 4 | なし | get_employee, send_message | 0 | なし"""

EXPECTED_REVIEWER = """方式 | 体数 | 手数 | 段数 | 定義 | 再送 | 項目 | 採点
オーケストレータ（構造化） | 4 | 8 | 8 | 10 | 5 | 10 | 4/4
＋レビュー役（読まない） | 5 | 9 | 9 | 10 | 5 | 11 | 4/4
＋レビュー役（実際に読む） | 5 | 10 | 10 | 12 | 6 | 11 | 4/4"""

EXPECTED_MERGE = """方式 | 体数 | 手数 | 段数 | 定義 | 再送 | 項目 | 採点
オーケストレータ（並列・構造化） | 5 | 9 | 7 | 8 | 4 | 10 | 4/4
並列＋集計執筆を統合 | 4 | 8 | 6 | 8 | 4 | 5 | 4/4"""

EXPECTED_RECOVER = """方式 | 体数 | 手数 | 段数 | 定義 | 再送 | 項目 | 採点
上流が空振り（取り直さない） | 4 | 8 | 8 | 10 | 5 | 6 | 2/4
上流が空振り（集計係が取り直す） | 4 | 9 | 9 | 12 | 6 | 8 | 4/4"""

FREE_MISSING = ["区分別の合計が4区分そろっている", "規程違反2件が注記されている",
                "通知に違反件数が入っている"]

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


# --- 0. 採点の正解が業務データから導けているか -----------------------------
reset_data()
exp = expected_facts()
check("採点の正解が業務データから導ける",
      exp["threshold"] == 50_000 and exp["total"] == 285_400 and exp["count"] == 6
      and exp["violations"] == ["EXP-0002", "EXP-0004"]
      and exp["by_category"] == {"交通費": 7_600, "出張旅費": 145_000,
                                 "接待交際費": 120_000, "備品": 12_800},
      "\n" + render_expected())
check("採点の正解の表示が本文と一致する", render_expected() == EXPECTED_SUMMARY,
      "" if render_expected() == EXPECTED_SUMMARY else "\n" + render_expected())

# --- 1. 7通りの構成を走らせて比較表を突き合わせる ---------------------------
results = run_all()
solo, structured, free, own, carry, needs, parallel = results
table = render_table(results)
check("方式の比較表が本文の表と一致する", table == EXPECTED_TABLE,
      "" if table == EXPECTED_TABLE else "\n" + table)

check("どの方式でもツール呼び出しは4回で同じ",
      all(r["tool_calls"] == 4 for r in results),
      str([r["tool_calls"] for r in results]))
check("どの方式でも全ワーカーが done で終わる",
      all(reason == "done" for r in results for reason in r["stop_reasons"].values()),
      str([r["stop_reasons"] for r in results]))
check("どの方式でも通知は1通だけ（副作用はデータ側で数える）",
      all(len(r["notices"]) == 1 for r in results),
      str([len(r["notices"]) for r in results]))

# --- 2. 成果物：単体と構造化オーケストレータは1文字も違わない ---------------
check("単体の成果物が期待どおり", solo["report"] == EXPECTED_REPORT,
      "" if solo["report"] == EXPECTED_REPORT else "\n" + solo["report"])
check("分けても成果物は1文字も変わらない（手数だけ増える）",
      solo["report"] == structured["report"]
      and solo["notices"][0]["body"] == structured["notices"][0]["body"],
      f"solo={len(solo['report'])}字 orch={len(structured['report'])}字")
check("通知文が期待どおり", solo["notices"][0]["body"] == EXPECTED_NOTICE,
      solo["notices"][0]["body"])
check("手数は 5 → 8 に増える（1.6倍）",
      solo["ledger"].total_calls == 5 and structured["ledger"].total_calls == 8,
      f"{solo['ledger'].total_calls} → {structured['ledger'].total_calls}")

# --- 3. 分けると1回の呼び出しは軽くなる -----------------------------------
solo_series = solo["ledger"].approx_in["solo"]
check("単体では入力が呼び出しごとに増え続ける",
      all(b > a for a, b in zip(solo_series, solo_series[1:])) and len(solo_series) == 5,
      str(solo_series))
check("ツール定義の送信数は 20 → 10、ツール結果の再送は 10 → 5",
      solo["ledger"].total_specs == 20 and structured["ledger"].total_specs == 10
      and solo["ledger"].total_results == 10 and structured["ledger"].total_results == 5)
check("分割後はどのワーカーも1回の入力が単体の最大より軽い",
      structured["ledger"].max_in < solo["ledger"].max_in
      and parallel["ledger"].max_in < solo["ledger"].max_in,
      f"単体={solo['ledger'].max_in} 構造化={structured['ledger'].max_in} "
      f"並列={parallel['ledger'].max_in}")

# --- 4. 伝言ゲーム：渡し方だけで採点が変わる -------------------------------
check("自由文で渡すと採点が 4/4 → 1/4 に落ちる",
      structured["score"]["passed"] == 4 and free["score"]["passed"] == 1
      and free["score"]["missing"] == FREE_MISSING,
      str(free["score"]["missing"]))
check("落ちても最終回答は「できました」のまま（黙って劣化する）",
      free["trajectories"]["notifier"].final == "経理部へ完了を通知しました。"
      and free["trajectories"]["notifier"].stop_reason == "done",
      str(free["trajectories"]["notifier"].final))
check("自由文モードのレポートにも総額だけは残る（もっともらしく見える）",
      free["report"] == EXPECTED_FREE_REPORT,
      "" if free["report"] == EXPECTED_FREE_REPORT else "\n" + free["report"])
check("下流では復元できない（黒板にも集計結果が無い）",
      free["blackboard"].latest("by_category") is None
      and structured["blackboard"].latest("by_category") is not None)

# --- 5. ハンドオフ型で落ちる場所 -------------------------------------------
check("自分の成果だけ渡すと通知の件数が落ちる（3/4）",
      own["score"]["passed"] == 3
      and own["score"]["missing"] == ["通知に違反件数が入っている"],
      str(own["score"]["missing"]))
check("落ちたのは通知だけ（レポートは書けている）",
      "EXP-0002" in own["report"] and "- 未承認の申請: 2 件" in own["report"]
      and "基準額" not in own["report"],
      f"{len(own['report'])}字")
check("畳んで渡すと落ちないが、渡す項目が 10 → 18 に膨らむ",
      carry["score"]["passed"] == 4
      and carry["ledger"].total_hop_fields == 18
      and structured["ledger"].total_hop_fields == 10,
      f"carry={carry['ledger'].total_hop_fields} "
      f"structured={structured['ledger'].total_hop_fields}")
check("相手の要求に合わせて渡せば、項目10で 4/4 になる",
      needs["score"]["passed"] == 4 and needs["ledger"].total_hop_fields == 10)

hops_own, hops_structured = render_hops(own), render_hops(structured)
check("引き継ぎの明細（自分の成果だけ）が本文と一致する",
      hops_own == EXPECTED_HOPS_OWN,
      "" if hops_own == EXPECTED_HOPS_OWN else "\n" + hops_own)
check("引き継ぎの明細（構造化）が本文と一致する",
      hops_structured == EXPECTED_HOPS_STRUCTURED,
      "" if hops_structured == EXPECTED_HOPS_STRUCTURED else "\n" + hops_structured)

# --- 6. どこで落ちたかを機械的に特定できる ---------------------------------
check("自由文モードは最初の区間で落ちている", first_loss(free) == "親→analyst",
      str(first_loss(free)))
check("自分の成果だけモードは最後の区間で落ちている",
      first_loss(own) == "writer→notifier", str(first_loss(own)))
check("構造化・畳んで渡す・相手の要求に合わせるは落ちていない",
      first_loss(structured) is None and first_loss(carry) is None
      and first_loss(needs) is None)
check("欠けた入力の判定が引き継ぎの記録だけからできる",
      audit_hops(own)[2]["欠けた入力"] == ["violations_count/violations"],
      str(audit_hops(own)[2]))
check("切り分けの出力が本文と一致する", render_audit(own) == EXPECTED_AUDIT_OWN,
      "" if render_audit(own) == EXPECTED_AUDIT_OWN else "\n" + render_audit(own))

# --- 7. 並列：段数は減り、総手数は増える -----------------------------------
check("並列にすると段数 8 → 7、総手数 8 → 9",
      parallel["stages"] == 7 and structured["stages"] == 8
      and parallel["ledger"].total_calls == 9,
      f"段数={parallel['stages']} 手数={parallel['ledger'].total_calls}")
check("並列にしても成果物は同じ", parallel["report"] == EXPECTED_REPORT)
authors = [e["author"] for e in parallel["blackboard"].entries]
check("並列でも黒板への書き込み順が固定されている（先に規程係、次に経費係）",
      authors[:5] == ["policy_collector"] * 3 + ["expense_collector"] * 2
      and parallel["blackboard"].latest("expenses") is not None,
      str(authors[:6]))

# --- 8. 決定性：2回走らせて同じになる --------------------------------------
again = run_orchestrator("structured")
check("同じ構成を2回走らせると軌跡・成果物・計測値が一致する",
      row_of(again) == row_of(structured) and again["report"] == structured["report"]
      and {k: t.tool_names for k, t in again["trajectories"].items()}
      == {k: t.tool_names for k, t in structured["trajectories"].items()},
      str(row_of(again)))
check("ワーカーごとのツールの並びが設計どおり",
      {k: t.tool_names for k, t in structured["trajectories"].items()}
      == {"collector": ["get_policy", "list_expenses"], "analyst": [],
          "writer": ["write_file"], "notifier": ["send_message"]},
      str({k: t.tool_names for k, t in structured["trajectories"].items()}))

# --- 9. 権限を分けるための分割 ---------------------------------------------
privilege_rows = [run_injected(SOLO_ALLOW, "単体（6ツール）", role="solo"),
                  run_injected(SPLIT_ALLOW, "分割（収集係は3ツール）")]
privilege_table = render_privilege(privilege_rows)
check("権限の比較表が本文と一致する", privilege_table == EXPECTED_PRIVILEGE,
      "" if privilege_table == EXPECTED_PRIVILEGE else "\n" + privilege_table)
check("分割側の拒否メッセージが使えるツールを教えている",
      all("ツール 'get_employee' は存在しません" in m
          or "ツール 'send_message' は存在しません" in m
          for m in privilege_rows[1]["拒否メッセージ"])
      and "使えるツール: get_policy, list_expenses, search_docs"
      in privilege_rows[1]["拒否メッセージ"][0],
      str(privilege_rows[1]["拒否メッセージ"][0]))
check("注入は単体でも分割でも同じように届いている（届き方は変わらない）",
      all(r["軌跡"].tool_names[0] == "search_docs" and len(r["軌跡"].steps) == 4
          for r in privilege_rows),
      str([r["軌跡"].tool_names for r in privilege_rows]))

# --- 10. 共有状態の競合 ----------------------------------------------------
lost = lost_update()
check("同じ鍵に2体が書くと latest は最後の1件しか見せない",
      lost["latest"] == "みなと 14:00" and lost["entries"] == 2
      and lost["read"] == ["みなと 11:00", "みなと 14:00"], str(lost))
conflict_table = render_conflict([race(s) for s in STRATEGIES])
check("競合の比較表が本文と一致する", conflict_table == EXPECTED_CONFLICT,
      "" if conflict_table == EXPECTED_CONFLICT else "\n" + conflict_table)

# --- 11. 軌跡はワーカーごとに保存して読み戻せる ----------------------------
saved = save_traces(structured, "verify_structured")
reloaded = Trajectory.from_jsonl(saved[0])
check("ワーカーごとに軌跡を保存し、読み戻せる",
      len(saved) == 4 and reloaded.task_id == "TASK-008-01"
      and reloaded.tool_names == ["get_policy", "list_expenses"],
      f"{len(saved)} ファイル / {reloaded.task_id}")

# --- 12. 練習問題の解答（レビュー役の追加・落ちた事実の取り直し） -----------
reviewer_results = reviewer_rows()
reviewer_table = render_reviewer(reviewer_results)
check("練習問題6の表が解答と一致する（レビュー役は手数だけ増やす）",
      reviewer_table == EXPECTED_REVIEWER,
      "" if reviewer_table == EXPECTED_REVIEWER else "\n" + reviewer_table)
check("レビュー役を足しても成果物は同一",
      all(r["report"] == EXPECTED_REPORT for r in reviewer_results))

merge_results = merge_rows()
merge_table = render_merge(merge_results)
check("練習問題8の表が解答と一致する（統合すると段数と引き継ぎが減る）",
      merge_table == EXPECTED_MERGE,
      "" if merge_table == EXPECTED_MERGE else "\n" + merge_table)
check("統合しても成果物は同一",
      merge_results[0]["report"] == merge_results[1]["report"] == EXPECTED_REPORT)

recover_results = recover_rows()
recover_table = render_recover(recover_results)
check("練習問題9の表が解答と一致する（取り直せば 2/4 → 4/4）",
      recover_table == EXPECTED_RECOVER,
      "" if recover_table == EXPECTED_RECOVER else "\n" + recover_table)
check("取り直した集計係だけが判定基準を持てる",
      recover_results[0]["threshold"] is None
      and recover_results[1]["threshold"] == 50_000,
      str([r["threshold"] for r in recover_results]))
check("上流が空振りしたときに落ちるのは違反の判定と通知の件数",
      recover_results[0]["score"]["missing"]
      == ["規程違反2件が注記されている", "通知に違反件数が入っている"],
      str(recover_results[0]["score"]["missing"]))

reset_data()

if failures:
    print()
    print(render_table(results))
    print()
    print(render_missing(results))
    print()
    print(render_tokens(results))
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション8の検証はすべて成功しました。")
