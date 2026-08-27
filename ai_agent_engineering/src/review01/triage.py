#!/usr/bin/env python3
"""業務要求の振り分けと、エージェントに回す場合の上限設計（S02 × S03）。

    docker compose exec app python src/review01/triage.py

S02 で作った3択（ワークフロー／ツール付き単発呼び出し／エージェント）は
「やるかやらないか」までしか決めない。エージェントを選んだ瞬間に、S03 で決めた
2つの設計判断——**上限をいくつにするか**と**上限に達したらどう振る舞うか**——が
必ず付いてくる。ここではその2つを1つの関数で繋ぐ。
"""

from __future__ import annotations

from _paths import setup

ROOT = setup()

import decision  # noqa: E402  (src/session02)
from my_agent import choose_on_limit, recommend_max_steps  # noqa: E402  (src/session03)

# 業務要求と、上限設計に必要な追加の情報。
#   depth             … 正常に進んだときに必要なツール呼び出しの回数（設計時の見積り）
#   has_side_effect   … 途中で外の世界を書き換えるか
#   partial_is_useful … 途中結果に価値があるか
#   retry_is_cheap    … やり直しが安いか
REQUESTS = [
    (decision.Request("請求書の区分付け", path_fixed=True, needs_judgment=True,
                      steps=1, failure_tolerance="medium"),
     {"depth": 1, "has_side_effect": False, "partial_is_useful": False,
      "retry_is_cheap": True}),
    (decision.Request("月次の経費集計", path_fixed=True, needs_judgment=True,
                      steps=3, failure_tolerance="medium"),
     {"depth": 3, "has_side_effect": True, "partial_is_useful": False,
      "retry_is_cheap": True}),
    (decision.Request("監査指摘の洗い出し", path_fixed=False, needs_judgment=True,
                      steps=0, failure_tolerance="high"),
     {"depth": 4, "has_side_effect": False, "partial_is_useful": True,
      "retry_is_cheap": False}),
    (decision.Request("取引先への謝罪文送付", path_fixed=False, needs_judgment=True,
                      steps=0, failure_tolerance="low", irreversible=True,
                      audit="strict"),
     {"depth": 3, "has_side_effect": True, "partial_is_useful": True,
      "retry_is_cheap": False}),
]


def triage(req, *, depth: int, has_side_effect: bool,
           partial_is_useful: bool, retry_is_cheap: bool) -> dict:
    """3択を決め、エージェントを選んだ場合だけ上限と振る舞いも決める。"""
    result = decision.choose(req)
    row: dict = {"choice": result.choice, "guardrails": list(result.guardrails)}
    if result.choice == decision.AGENT:
        row["max_steps"] = recommend_max_steps(depth)
        row["on_limit"] = choose_on_limit(has_side_effect=has_side_effect,
                                          partial_is_useful=partial_is_useful,
                                          retry_is_cheap=retry_is_cheap)
    return row


def truth() -> dict:
    """要求名 → 判断結果。verify.py と練習問題の答え合わせに使う。"""
    return {req.name: triage(req, **opts) for req, opts in REQUESTS}


def main() -> None:
    print("=== 4つの業務要求を振り分け、上限まで決める ===")
    for name, row in truth().items():
        print(f"\n--- {name} ---")
        print(f"選択: {row['choice']}")
        if "max_steps" in row:
            print(f"max_steps: {row['max_steps']} / on_limit: {row['on_limit']}")
        print(f"付ける仕掛け: {' / '.join(row['guardrails'])}")


if __name__ == "__main__":
    main()
