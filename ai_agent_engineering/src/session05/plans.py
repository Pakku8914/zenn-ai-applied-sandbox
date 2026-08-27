#!/usr/bin/env python3
"""計画の台本と、サブゴールごとのモデル応答（すべて決定的）。

ScriptedClient はプロンプトを読まないので、「計画担当の LLM が返す JSON」と
「各サブゴールを担当する LLM の応答」を、ここに台本として置く。
台本の中のレポート本文は impact.render_report が実データから組み立てる
（数値を台本に直接書くと、データが変わったときに黙って食い違う）。
"""

from __future__ import annotations

import json

from impact import (NEW_APPROVAL, NEW_DEADLINE_DAYS, OLD_APPROVAL,  # noqa: I001
                    OLD_DEADLINE_DAYS, fmt, impact_facts, render_report)
from planner import Plan, parse_plan


def plan_from(raw: dict) -> Plan:
    """dict の計画を JSON 経由で Plan にする（実運用と同じ経路を通す）。"""
    return parse_plan(json.dumps(raw, ensure_ascii=False))


def plan_json(raw: dict) -> str:
    return json.dumps(raw, ensure_ascii=False)


def planner_turns(*plans: dict) -> list[dict]:
    """計画担当の LLM の応答列（JSON だけを返す）。"""
    return [{"thought": "計画を組み立てる。", "final": plan_json(p)} for p in plans]


# ---------------------------------------------------------------------------
# サブゴールの定義（計画の部品）
# ---------------------------------------------------------------------------
SG_POLICY = {
    "id": "sg_policy",
    "goal": "経費精算の現行規程を取得し、事前承認の基準額と申請期限を確認する",
    "tools": ["get_policy"], "needs": [], "consumes": [], "produces": ["policy"],
    "max_steps": 2,
}
# 前提が誤ったサブゴール：規程の項目名を「経費精算規程」だと思い込んでいる
SG_POLICY_X = {
    "id": "sg_policy_x",
    "goal": "規程集から「経費精算規程」の本文を取得する",
    "tools": ["get_policy"], "needs": [], "consumes": [], "produces": ["policy"],
    "max_steps": 2,
}
SG_POLICY_FIX = {
    "id": "sg_policy_fix",
    "goal": "get_policy が受け付ける項目名（経費精算）で現行規程を取得し直す",
    "tools": ["get_policy"], "needs": [], "consumes": [], "produces": ["policy"],
    "max_steps": 2,
}
SG_EXPENSES = {
    "id": "sg_expenses",
    "goal": "経費申請の一覧を取得し、金額と起票日を確認する",
    "tools": ["list_expenses"], "needs": [], "consumes": [], "produces": ["expenses"],
    "max_steps": 2,
}
SG_AMOUNT = {
    "id": "sg_amount",
    "goal": "基準額が1万円に下がったときに新たに事前承認が必要になる申請を洗い出す",
    "tools": [], "needs": ["sg_expenses"], "consumes": ["expenses"],
    "produces": ["amount_impact"], "max_steps": 1,
}
SG_DEADLINE = {
    "id": "sg_deadline",
    "goal": "申請期限が5日に短くなったときに新たに期限を超過する申請を洗い出す",
    "tools": [], "needs": ["sg_expenses"], "consumes": ["expenses"],
    "produces": ["deadline_impact"], "max_steps": 1,
}
# 分解しすぎ：一覧を必要とするのに、それを作るサブゴールへの依存を書いていない
SG_AMOUNT_NOCONTEXT = {
    "id": "sg_amount_nocontext",
    "goal": "新たに事前承認が必要になる申請を洗い出す",
    "tools": [], "needs": [], "consumes": ["expenses"],
    "produces": ["amount_impact"], "max_steps": 1,
}


# 新情報（結果に出た却下済みの申請）を受けて足すサブゴール
SG_REJECTED = {
    "id": "sg_rejected",
    "goal": "却下済み（rejected）の申請を影響調査でどう扱うかを確定させる",
    "tools": [], "needs": ["sg_expenses"], "consumes": ["expenses"],
    "produces": ["rejected_note"], "max_steps": 1,
}


def _report(sg_id: str, needs: list[str]) -> dict:
    return {
        "id": sg_id,
        "goal": "影響一覧と対応方針をレポートにまとめ、作業領域に保存する",
        "tools": ["write_file"], "needs": needs,
        "consumes": ["policy", "amount_impact", "deadline_impact"],
        "produces": ["report"], "max_steps": 2,
    }


SG_REPORT = _report("sg_report", ["sg_policy", "sg_amount", "sg_deadline"])
SG_REPORT_REPAIR = _report("sg_report", ["sg_policy_fix", "sg_amount", "sg_deadline"])
SG_REPORT_NOPOLICY = _report("sg_report_nopolicy", ["sg_policy_x", "sg_amount", "sg_deadline"])
SG_REPORT_WRONG = _report("sg_report_wrong",
                          ["sg_policy", "sg_amount_nocontext", "sg_deadline"])
SG_REPORT_MIN = {
    "id": "sg_report_min",
    "goal": "調べ終わった観点だけでレポートを保存し、未調査の観点を明記する",
    "tools": ["write_file"], "needs": ["sg_policy_fix", "sg_expenses"],
    "consumes": ["policy", "expenses"], "produces": ["report"], "max_steps": 2,
}

# ---------------------------------------------------------------------------
# 計画（台本）
# ---------------------------------------------------------------------------
GOAL = "経費精算規程の改定案の影響を調べ、影響調査レポートを残す"

PLAN_OK = {"goal": GOAL, "subgoals": [SG_POLICY, SG_EXPENSES, SG_AMOUNT, SG_DEADLINE,
                                      SG_REPORT]}
PLAN_BROKEN = {"goal": GOAL, "subgoals": [SG_POLICY_X, SG_EXPENSES, SG_AMOUNT, SG_DEADLINE,
                                          SG_REPORT_NOPOLICY]}
PLAN_REPAIR = {"goal": GOAL + "（規程の取得を修正した計画）",
               "subgoals": [SG_POLICY_FIX, SG_EXPENSES, SG_AMOUNT, SG_DEADLINE,
                            SG_REPORT_REPAIR]}
PLAN_MIN = {"goal": GOAL + "（予算に合わせて縮小した計画）",
            "subgoals": [SG_EXPENSES, SG_REPORT_MIN]}
PLAN_FRAGMENTED = {"goal": GOAL + "（依存を書き忘れた計画）",
                   "subgoals": [SG_POLICY, SG_EXPENSES, SG_AMOUNT_NOCONTEXT, SG_DEADLINE,
                                SG_REPORT_WRONG]}
# 新情報を受けて、サブゴールを1つ足した計画（PLAN_OK に sg_rejected を挿す）
PLAN_PLUS = {"goal": GOAL + "（却下済みの扱いを追加した計画）",
             "subgoals": [SG_POLICY, SG_EXPENSES, SG_REJECTED, SG_AMOUNT, SG_DEADLINE,
                          SG_REPORT]}

# 検証だけに使う計画（実行しない）
PLAN_OVERSPLIT = {
    "goal": GOAL + "（1手ずつに割った計画）",
    "subgoals": [
        {"id": "sg1", "goal": "経費精算の規程を取得する", "tools": ["get_policy"],
         "produces": ["policy"], "max_steps": 1},
        {"id": "sg2", "goal": "接待交際費の規程を取得する", "tools": ["get_policy"],
         "produces": ["policy_ent"], "max_steps": 1},
        {"id": "sg3", "goal": "申請一覧を取得する", "tools": ["fetch_expenses"],
         "produces": ["expenses"], "max_steps": 1},
        {"id": "sg4", "goal": "金額の列だけを抜き出す", "consumes": ["expenses"],
         "produces": ["amounts"], "max_steps": 1},
        {"id": "sg5", "goal": "1万円以上の申請を数える", "consumes": ["amounts"],
         "produces": ["count_new"], "max_steps": 1},
        {"id": "sg6", "goal": "5万円以上の申請を数える", "needs": ["sg3"],
         "consumes": ["expenses"], "produces": ["count_old"], "max_steps": 1},
        {"id": "sg7", "goal": "起票日の列だけを抜き出す", "needs": ["sg3"],
         "consumes": ["expenses"], "produces": ["dates"], "max_steps": 1},
        {"id": "sg8", "goal": "経過日数を計算する", "needs": ["sg7"],
         "consumes": ["dates"], "produces": ["days"], "max_steps": 1},
        {"id": "sg9", "goal": "期限超過の申請を数える", "needs": ["sg8"],
         "consumes": ["days"], "produces": ["count_late"], "max_steps": 1},
        {"id": "sg10", "goal": "レポートを保存する", "tools": ["write_file"],
         "needs": ["sg1", "sg5", "sg6", "sg9"],
         "consumes": ["policy", "count_new", "count_old", "count_late"],
         "produces": ["report"], "max_steps": 1},
    ],
}
PLAN_CYCLE = {
    "goal": "循環した計画",
    "subgoals": [
        {"id": "sg_a", "goal": "sg_b の結果を使って集計する", "needs": ["sg_b"],
         "produces": ["report"], "max_steps": 1},
        {"id": "sg_b", "goal": "sg_a の結果を使って一覧を作る", "needs": ["sg_a"],
         "produces": ["expenses"], "max_steps": 1},
    ],
}
# JSON にならない応答（計画も生成物なので、この形で返ってくることがある）
PLAN_NOT_JSON = "まず規程を確認し、次に申請一覧を取得します。最後にレポートを書きます。"

# ---------------------------------------------------------------------------
# 計画担当の応答列（方式ごと）
# ---------------------------------------------------------------------------
TURNS_STATIC_OK = planner_turns(PLAN_OK)
TURNS_STATIC_BROKEN = planner_turns(PLAN_BROKEN)
TURNS_REPLAN = planner_turns(PLAN_BROKEN, PLAN_REPAIR)
TURNS_BUDGET = planner_turns(PLAN_BROKEN, PLAN_REPAIR, PLAN_MIN)
# 毎サブゴール再計画（アンチパターン）。同じ計画を返し続けるだけでも呼び出しは増える
TURNS_EVERY = planner_turns(PLAN_BROKEN, PLAN_REPAIR, PLAN_REPAIR, PLAN_REPAIR,
                            PLAN_REPAIR, PLAN_REPAIR)
TURNS_FRAGMENTED = planner_turns(PLAN_FRAGMENTED)
TURNS_NEWFACT = planner_turns(PLAN_OK, PLAN_PLUS)


# ---------------------------------------------------------------------------
# サブゴールごとのモデル応答
# ---------------------------------------------------------------------------
def _policy_fact() -> str:
    return (f"現行規程: 事前承認は1件 {OLD_APPROVAL:,} 円以上、"
            f"申請期限は支出日から {OLD_DEADLINE_DAYS} 日以内。")


def _get_policy_turns(topic: str, ok: bool) -> list[dict]:
    if ok:
        return [
            {"thought": "事前承認の基準額と申請期限を現行規程で確認する。",
             "calls": [{"name": "get_policy", "args": {"topic": topic}}]},
            {"thought": "基準額と期限が取れた。", "final": _policy_fact()},
        ]
    return [
        {"thought": "規程集から本文を取得する。",
         "calls": [{"name": "get_policy", "args": {"topic": topic}}]},
        {"thought": "項目名が見つからなかった。ここは飛ばして先に進む。",
         "final": f"現行規程の本文は取得できませんでした（項目名 '{topic}' が見つかりません）。"},
    ]


def turns_for(sg_id: str) -> list[dict]:
    """サブゴール担当の LLM の応答列。実データから組み立てるので決定的。"""
    facts = impact_facts()
    if sg_id in ("sg_policy", "sg_policy_fix"):
        return _get_policy_turns("経費精算", ok=True)
    if sg_id == "sg_policy_x":
        return _get_policy_turns("経費精算規程", ok=False)
    if sg_id == "sg_expenses":
        return [
            {"thought": "金額と起票日を見るために一覧を取得する。",
             "calls": [{"name": "list_expenses", "args": {"status": "all"}}]},
            {"thought": "一覧が取れた。",
             "final": f"経費申請は {len(facts['rows'])} 件。金額・区分・状態・起票日を取得した。"},
        ]
    if sg_id == "sg_amount":
        return [{"thought": "引き継いだ一覧から金額で絞る。",
                 "final": (f"新たに事前承認が必要: {fmt(facts['newly_approval'])}"
                           f"（{len(facts['newly_approval'])} 件）。"
                           f"すでに対象: {fmt(facts['already_approval'])}"
                           f"（{len(facts['already_approval'])} 件）。"
                           f"基準額 {NEW_APPROVAL:,} 円で判定した。")}]
    if sg_id == "sg_deadline":
        newly = "、".join(r["expense_id"] for r in facts["newly_late"])
        already = "、".join(r["expense_id"] for r in facts["already_late"])
        return [{"thought": "引き継いだ一覧の起票日から経過日数を出す。",
                 "final": (f"新たに期限超過: {newly}（{len(facts['newly_late'])} 件）。"
                           f"元から超過: {already}（{len(facts['already_late'])} 件）。"
                           f"期限 {NEW_DEADLINE_DAYS} 日で判定した。")}]
    if sg_id == "sg_rejected":
        rejected = [r for r in facts["rows"] if r["status"] == "rejected"]
        return [{"thought": "却下済みの申請の扱いを決める。",
                 "final": (f"却下済みは {'、'.join(r['expense_id'] for r in rejected)}"
                           f"（{len(rejected)} 件）。再申請時に新基準が適用されるため、"
                           "影響一覧には残し、対応方針で注記する。")}]
    if sg_id == "sg_amount_nocontext":
        return [{"thought": "引き継いだ情報を見る。一覧が無い。",
                 "final": "引き継いだ情報に申請一覧が無いため、"
                          "新たに事前承認が必要になる申請は特定できませんでした。"}]
    if sg_id in _REPORT_VARIANTS:
        path, kwargs = _REPORT_VARIANTS[sg_id]
        content = render_report(facts, **kwargs)
        return [
            {"thought": "引き継いだ情報をレポートにまとめて保存する。",
             "calls": [{"name": "write_file", "args": {"path": path, "content": content}}]},
            {"thought": "保存できた。", "final": f"{path} に影響調査レポートを保存しました。"},
        ]
    raise KeyError(
        f"サブゴール '{sg_id}' の台本がありません。plans.turns_for に追加してください。"
    )


_REPORT_VARIANTS: dict[str, tuple[str, dict]] = {
    # 満点のレポート
    "sg_report": ("impact.md", {}),
    # 現行規程が取れなかったまま書いたレポート（静的計画の黙った失敗）
    "sg_report_nopolicy": ("impact_static_broken.md", {"policy": False}),
    # 予算が足りず観点を落としたレポート（未調査を明記する）
    "sg_report_min": ("impact_budget.md",
                      {"deadline": False,
                       "note": "残り予算が足りないため、申請期限の観点は未調査です。"}),
    # 文脈が分断されて金額の観点が落ちたレポート
    "sg_report_wrong": ("impact_fragmented.md", {"amount": False}),
}


def noplan_turns() -> list[dict]:
    """計画を立てず、思いついた順に進める場合のモデル応答。"""
    facts = impact_facts()
    return [
        {"thought": "経費精算のことなので、まず関連文書を探してみる。",
         "calls": [{"name": "search_docs", "args": {"query": "経費精算"}}]},
        {"thought": "手順書が出てきた。申請の一覧も見てみる。",
         "calls": [{"name": "list_expenses", "args": {"status": "all"}}]},
        {"thought": "金額で影響を受ける申請が分かったので、レポートにする。",
         "calls": [{"name": "write_file",
                    "args": {"path": "impact_noplan.md",
                             "content": render_report(facts, policy=False, deadline=False)}}]},
        {"thought": "保存したので報告する。",
         "final": "impact_noplan.md に影響調査レポートを保存しました。"},
    ]


if __name__ == "__main__":
    for _sid in ("sg_policy", "sg_policy_x", "sg_expenses", "sg_amount", "sg_deadline",
                 "sg_rejected", "sg_amount_nocontext", *_REPORT_VARIANTS):
        _turns = turns_for(_sid)
        print(f"{_sid:<22} 応答 {len(_turns)} 個 / "
              f"ツール {[c['name'] for t in _turns for c in t.get('calls', [])]}")
