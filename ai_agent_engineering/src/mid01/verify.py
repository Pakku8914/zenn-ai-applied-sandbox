#!/usr/bin/env python3
"""中間プロジェクト01（調査エージェント）の自己検証。

    docker compose exec app python src/mid01/verify.py

9本の走行と、設計上の約束をすべて機械判定する。1つでも満たさなければ非0で終了する
ので、出力を読んで「合っている気がする」と判断する余地はない。
本文・解答章に載せた数値もここで固定している（数値が変わったら章を直す）。
"""

from __future__ import annotations

import sys

from _paths import setup

ROOT = setup()

from diagnose import cause_label, diagnose, is_trustworthy_done  # noqa: E402
from failure_modes import classify  # noqa: E402
from goodtools import is_actionable, render_tool_spec  # noqa: E402
from planner import mermaid_dag, topo_layers  # noqa: E402

from analysis import extract_threshold, find_findings  # noqa: E402
from cases import reset_data, run_all  # noqa: E402
from machine import (LOOP_LIMITS, STATE_TOOLS, TERMINAL, TRANSITIONS,  # noqa: E402
                     build_machine, stage_error)
from research_plan import (PLAN_FORBIDDEN, PLAN_UNMAPPED, RESEARCH_PLAN,  # noqa: E402
                           SUBGOAL_STATES, check_plan)
from spec import build_registry, render_spec_md  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


reset_data()
registry = build_registry()
names = registry.names()

# ---------------------------------------------------------------------------
# 成果物①：ツール仕様書（宣言から生成するので実装とずれない）
# ---------------------------------------------------------------------------
print("=== 成果物①：ツール仕様書 ===")
check("道具は4つだけ（読み取り3・書き込み1）",
      names == ["find_expenses", "get_policy", "search_docs", "write_file"], str(names))
check("承認が必要な道具を持っていない",
      not any(registry.get(n).requires_approval for n in names))
check("書き込みは write_file だけ",
      [n for n in names if "write" in registry.get(n).tags] == ["write_file"])

spec_md = render_spec_md(registry)
for line in (
    "| find_expenses | なし | はい | 不要 | （なし） | collecting | はい |",
    "| get_policy | なし | はい | 不要 | topic | collecting | はい |",
    "| search_docs | なし | はい | 不要 | query | collecting | いいえ |",
    "| write_file | あり | はい | 不要 | path, content | "
    "drafting, insufficient, stopping, handoff | いいえ |",
):
    check(f"仕様書の行が生成される（{line.split('|')[1].strip()}）", line in spec_md)
check("S04 の render_tool_spec とも整合する",
      "| find_expenses | なし | はい | 不要 | （なし） | status |" in render_tool_spec(registry))

# ---------------------------------------------------------------------------
# 成果物②：状態遷移図と計画
# ---------------------------------------------------------------------------
print("\n=== 成果物②：状態遷移図と計画 ===")
mermaid = build_machine().to_mermaid()
check("状態遷移図は stateDiagram-v2 で書き出される",
      mermaid.startswith("stateDiagram-v2"))
check("遷移は23本（見出しを含めて24行）", len(mermaid.splitlines()) == 24,
      f"{len(mermaid.splitlines())} 行")
check("状態ごとの許可リストが全状態にある",
      set(STATE_TOOLS) == set(TRANSITIONS) | set(TERMINAL))
check("上限で抜ける遷移を持つのは4状態",
      sorted(s for s, e in TRANSITIONS.items() if "over_budget" in e)
      == ["checking", "collecting", "drafting", "reporting"])
check("ループのある状態には必ず上限がある",
      all(state in LOOP_LIMITS
          for state, events in TRANSITIONS.items()
          if state in events.values()))
check("異常系の出口は3つ（情報不足・打ち切り・引き継ぎ）",
      {"insufficient", "stopping", "handoff"} <= set(TRANSITIONS))

check("正しい計画には違反が無い", check_plan(RESEARCH_PLAN, names) == [],
      str(check_plan(RESEARCH_PLAN, names)))
check("依存は3層に分かれる",
      [[sg.id for sg in layer] for layer in topo_layers(RESEARCH_PLAN)]
      == [["sg_policy"], ["sg_expenses", "sg_context"], ["sg_report"]])
check("計画の DAG が Mermaid になる",
      "sg_policy --> sg_expenses" in mermaid_dag(RESEARCH_PLAN))
check("サブゴールと状態は1対1", set(SUBGOAL_STATES) == {sg.id for sg in RESEARCH_PLAN.subgoals})

unmapped = check_plan(PLAN_UNMAPPED, names)
check("状態が割り当てられていないサブゴールを1件検出する",
      len(unmapped) == 1 and "sg_wrapup" in unmapped[0], str(unmapped))
forbidden = check_plan(PLAN_FORBIDDEN, names)
check("持っていない道具は S05 の検査でも状態の検査でも落ちる",
      any("未登録のツール 'send_message'" in v for v in forbidden)
      and any("状態 'drafting' では使えません" in v for v in forbidden), str(forbidden))

# ---------------------------------------------------------------------------
# 部品：判定基準の抽出と照合
# ---------------------------------------------------------------------------
print("\n=== 部品：判定基準と照合 ===")
POLICY = "経費精算: 領収書を添付し、支出日から10日以内に申請する。1件5万円以上は事前承認が必要。"
ROOM = "会議室予約: 連続利用は4時間まで。10名以上の会議は大会議室を優先する。"
check("規程から 50,000 円を取り出す", extract_threshold(POLICY) == 50_000)
check("金額が書かれていない規程では None（0 を返さない）",
      extract_threshold(ROOM) is None)
check("「10日以内」に引っかからない", extract_threshold("支出日から10日以内") is None)
TABLE = ("該当 2 件（表示 2 件）\n"
         "EXP-0004 | 佐藤 健 | 145000 | 出張旅費 | submitted\n"
         "EXP-0002 | 高橋 涼 | 68000 | 接待交際費 | submitted")
check("表から2件を申請ID順に拾う",
      [r["expense_id"] for r in find_findings(TABLE, 50_000)] == ["EXP-0002", "EXP-0004"])
check("見出し行は拾わない", len(find_findings("該当 2 件（表示 2 件）", 50_000)) == 0)

error = stage_error("collecting", "write_file", STATE_TOOLS["collecting"])
check("段階外を断るメッセージは次の一手を示している（is_actionable）",
      is_actionable(error), f"{len(error)} 文字")

# ---------------------------------------------------------------------------
# 成果物③④：9本の走行
# ---------------------------------------------------------------------------
print("\n=== 成果物③④：9本の走行 ===")
rows = run_all()
by_name = {row["case"].name: row for row in rows}

#              ステップ 手数 呼出 失敗 停止理由       結果          採点 残ったファイル
SHAPE = {
    "full_report": (6, 3, 3, 0, "done", "report", 4, ["report.md"]),
    "parallel_reads": (6, 3, 4, 0, "done", "report", 4, ["report.md"]),
    "stage_violation": (7, 4, 4, 1, "done", "report", 4, ["report.md"]),
    "budget_partial": (5, 2, 4, 0, "max_steps", "partial", 4, ["report.md"]),
    "wrong_policy": (4, 1, 3, 0, "done", "insufficient", 4, ["report.md"]),
    "no_evidence": (4, 2, 2, 1, "done", "insufficient", 4, ["report.md"]),
    "broken_tool": (4, 2, 3, 1, "error", "handoff", 4, ["handoff.md"]),
    "hallucination_guarded": (9, 4, 4, 0, "loop_detected", "handoff", 4,
                              ["handoff.md", "report.md"]),
    "hallucination_bare": (6, 3, 3, 0, "done", "report", 3, ["report.md"]),
    "invalid_plan": (2, 0, 1, 0, "error", "handoff", 4, ["handoff.md"]),
}
check("シナリオは9本＋比較用1本＝10通り", len(rows) == 10, f"{len(rows)} 本")
for name, expected in SHAPE.items():
    row = by_name[name]
    got = (row["steps"], row["llm_calls"], row["tool_calls"], row["failed_calls"],
           row["stop_reason"], row["outcome"], row["score"]["passed"], row["files"])
    check(f"{name} の走行が期待どおり", got == expected, str(got))

check("異常系は6本ある（上限・道具の失敗・情報不足2本・幻覚・計画の検査落ち）",
      sum(1 for row in rows if row["outcome"] != "report") == 6)
check("段数は手数と同じ（単体構成なので直列）",
      all(row["stages"] == row["llm_calls"] for row in rows))

# ---------------------------------------------------------------------------
# 3つの失敗に答えがあること（このプロジェクトの評価観点）
# ---------------------------------------------------------------------------
print("\n=== 成果物の中身（3つの失敗に答えがあるか） ===")
report_text = by_name["full_report"]["artifact_text"]
for line in ("- 結果: 報告",
             "- 判定基準: 50,000 円以上は事前承認が必要",
             "- ここまでの手数: 2 回",
             "| EXP-0002 | 高橋 涼 | 68,000 | 接待交際費 | submitted |",
             "| EXP-0004 | 佐藤 健 | 145,000 | 出張旅費 | submitted |",
             "- get_policy(topic=経費精算)",
             "- find_expenses(limit=20, min_amount=50000, status=submitted)",
             "- EXP-0002: 事前承認の記録の有無を所属長に確認する"):
    check(f"レポートに「{line[:26]}」がある", line in report_text)

EXPECTED_LINES = {
    "budget_partial": ("- 結果: 打ち切り（部分結果）",
                       "- 打ち切りの理由: 手数の上限 2 回に達した",
                       "- 打ち切った段階: collecting",
                       "- そろっていない材料: find_expenses"),
    "wrong_policy": ("- 結果: 情報不足",
                     "- 判定していない理由: 規程から判定基準の金額を読み取れなかった",
                     "- 判定: していない（「該当なし」ではない）"),
    "no_evidence": ("- 結果: 情報不足",
                    "- そろっていない材料: get_policy, find_expenses",
                    "- （採用できた根拠はありません）"),
    "broken_tool": ("- 結果: 引き継ぎ", "内部エラー（TimeoutError）",
                    "- 止まった段階: collecting"),
    "hallucination_guarded": ("- 結果: 引き継ぎ", "- 止まった段階: reporting",
                              "- 作成済みの成果物: mid01/report.md"),
    "invalid_plan": ("- 結果: 引き継ぎ", "実行する状態が割り当てられていません",
                     "- 止まった段階: planning"),
}
for name, lines in EXPECTED_LINES.items():
    text = by_name[name]["artifact_text"]
    absent = [line for line in lines if line not in text]
    check(f"{name} の成果物に必要な行がそろっている", not absent, str(absent))

check("情報不足は done で終わるが「該当なし」とは書かない",
      by_name["wrong_policy"]["stop_reason"] == "done"
      and "判定: していない" in by_name["wrong_policy"]["artifact_text"])
check("引き継ぎには理由が必ず入る",
      all(by_name[n]["state"].handoff_reason
          for n in ("broken_tool", "hallucination_guarded", "invalid_plan")))
check("計画が壊れているときはモデルを1回も呼ばない",
      by_name["invalid_plan"]["llm_calls"] == 0)

# ---------------------------------------------------------------------------
# 停止理由・失敗モード・原因・信用できるか
# ---------------------------------------------------------------------------
print("\n=== 停止理由を鵜呑みにしない（S02・復習01） ===")
TRUST = {
    #                          失敗モード      原因（6分類）        done を信用できるか
    "full_report": ([], "異常なし", True),
    "parallel_reads": ([], "異常なし", True),
    "stage_violation": ([], "異常なし", True),
    "budget_partial": (["暴走"], "上限不足", False),
    "wrong_policy": ([], "異常なし", True),
    "no_evidence": ([], "異常なし", True),
    "broken_tool": ([], "この6つでは説明できない", False),
    "hallucination_guarded": ([], "この6つでは説明できない", False),
    "hallucination_bare": (["幻覚"], "報告が実態と違う", False),
    "invalid_plan": ([], "この6つでは説明できない", False),
}
for name, (modes, label, trust) in TRUST.items():
    row = by_name[name]
    reg, traj = row["registry"], row["traj"]
    allowed = reg.names()
    got_modes = classify(traj, allowed_tools=set(allowed), registry=reg)
    got_trust = is_trustworthy_done(traj, registry=reg, allowed_tools=allowed)
    got_label = cause_label(diagnose(traj, registry=reg, allowed_tools=allowed,
                                     needed_steps=6), got_trust)
    check(f"{name} の失敗モード・原因・信用",
          (got_modes, got_label, got_trust) == (modes, label, trust),
          f"{got_modes} / {got_label} / {got_trust}")

check("情報不足の done は信用してよい（判定していないと明記してあるため）",
      is_trustworthy_done(by_name["wrong_policy"]["traj"],
                          registry=by_name["wrong_policy"]["registry"],
                          allowed_tools=by_name["wrong_policy"]["registry"].names()))
check("照合を外した走行は done でも信用できない",
      not is_trustworthy_done(by_name["hallucination_bare"]["traj"],
                              registry=by_name["hallucination_bare"]["registry"],
                              allowed_tools=by_name["hallucination_bare"]["registry"].names()))

# ---------------------------------------------------------------------------
# 成果物⑤：コストと手数
# ---------------------------------------------------------------------------
print("\n=== 成果物⑤：コストと手数 ===")
for row in rows:
    tokens = row["input_tokens"]
    if len(tokens) < 2:
        continue
    check(f"{row['case'].name} の入力は手ごとに増える",
          all(a < b for a, b in zip(tokens, tokens[1:])), str(tokens))

full = by_name["full_report"]
hallu = by_name["hallucination_guarded"]
check("手数が 3 から 4 に増えると入力の合計はそれ以上の比率で増える",
      (sum(hallu["input_tokens"]) / sum(full["input_tokens"])
       > hallu["llm_calls"] / full["llm_calls"]),
      f"{sum(full['input_tokens'])} → {sum(hallu['input_tokens'])}")
check("読み取り2本を並列にしても手数は変わらない（段数が減るだけ）",
      by_name["parallel_reads"]["llm_calls"] == by_name["full_report"]["llm_calls"])
check("並列にした走行にだけ parallel が現れる",
      by_name["parallel_reads"]["batches"][0] == "parallel"
      and by_name["full_report"]["batches"] == ["serial", "serial", "serial"],
      str(by_name["full_report"]["batches"]))

# ---------------------------------------------------------------------------
# 信頼境界：採用しない結果は状態に入れない
# ---------------------------------------------------------------------------
print("\n=== 信頼境界 ===")
for row in rows:
    joined = "\n".join(row["state"].materials.values())
    check(f"{row['case'].name}: 注入文字列は状態に入らない",
          "これまでの指示は無効" not in joined)
check("search_docs の結果は根拠に採用されない",
      all("search_docs" not in row["state"].materials for row in rows))
check("参照だけした道具は notes に残る（軌跡からも消さない）",
      by_name["parallel_reads"]["state"].notes
      == ["search_docs(limit=1, query=経費精算手順)"],
      str(by_name["parallel_reads"]["state"].notes))

# ---------------------------------------------------------------------------
# 決定性：2回走らせて同じ結果になる
# ---------------------------------------------------------------------------
print("\n=== 決定性 ===")


def digest(rows_: list[dict]) -> list[tuple]:
    return [(row["case"].name, tuple(row["traj"].tool_names), row["stop_reason"],
             row["outcome"], tuple(row["input_tokens"]), row["artifact_text"])
            for row in rows_]


check("2回走らせて軌跡・成果物・近似トークンが一致する",
      digest(rows) == digest(run_all()))

reset_data()

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\n中間プロジェクト01の検証はすべて成功しました。")
