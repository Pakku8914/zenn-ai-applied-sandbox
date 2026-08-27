#!/usr/bin/env python3
"""セッション16の練習問題の参照解。

    python src/session16/ex_cost.py

**先に自分で書いてから読んでください。** 自分の実装で判定したい場合は、
`verify_practice.py` の import 元を自分のファイルに差し替えるだけで動きます。
各関数は「判定できる形（辞書）」を返すことだけを約束しています。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _d in (ROOT, HERE, ROOT / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

from agentkit.eval import task_success, tool_choice_accuracy  # noqa: E402
from capguard import (admit_rows, behaviour_rows, check_handoff,  # noqa: E402
                      limit_rows)
from costshape import (cacheable_tokens, detail_trajectory,  # noqa: E402
                       step_rows, table_rows, unstable_head)
from prices import HIGH, io_split, shares, traj_cost  # noqa: E402
from resultsize import pad_rows, slim_row  # noqa: E402
from tiering import (EXPECTED, degraded_trajectory, precision,  # noqa: E402
                     route_all_high, route_by_role, route_threshold,
                     tier_rows, tiered_cost)

DAILY_LIMIT = 50_000
PER_TASK_LIMIT = 15_000


# --- 問題1: 1タスクあたりの単価表 -------------------------------------------
def cost_table() -> dict:
    rows = table_rows()
    cus = [r["cu"] for r in rows]
    top = max(rows, key=lambda r: r["cu"])
    base = rows[0]
    return {"行": rows, "cu": cus, "合計": sum(cus), "最も高い": top["シナリオ"],
            "倍率": round(top["cu"] / base["cu"], 2),
            "最も高い件の停止理由": top["停止理由"]}


# --- 問題2: ステップ別の内訳 --------------------------------------------------
def step_breakdown() -> dict:
    traj = detail_trajectory()
    rows = step_rows(traj)
    in_cost, out_cost = io_split(traj, HIGH)
    p_in, p_out = shares([in_cost, out_cost])
    return {"cu": [r["cu"] for r in rows],
            "割合": [round(r["share"], 1) for r in rows],
            "合計": sum(r["cu"] for r in rows),
            "入力割合": round(p_in, 1), "出力割合": round(p_out, 1),
            "支配要因": "入力" if in_cost >= out_cost else "出力"}


# --- 問題3: ツール結果の大きさは残りステップ数だけ課金される -------------------
def pad_effect() -> dict:
    rows = pad_rows()
    return {"増分": [r["増分"] for r in rows[1:]],
            "理論値": [r["理論値"] for r in rows[1:]],
            "入力合計": [r["in"] for r in rows],
            "基準のステップ別": rows[0]["ステップ別"],
            "get_policy のステップ別": rows[1]["ステップ別"]}


# --- 問題4: 前方一致キャッシュ -------------------------------------------------
def cache_effect() -> dict:
    traj = detail_trajectory()
    total = traj.total_tokens
    stable = cacheable_tokens(traj)
    broken = cacheable_tokens(traj, unstable_head)
    full = traj_cost(traj, HIGH)
    cached = traj_cost(traj, HIGH, cached_in=stable)
    return {"再利用できる入力": stable, "新しく払う入力": total["input"] - stable,
            "最後のステップの入力": traj.steps[-1].usage["input_tokens"],
            "時刻を先頭に入れた場合": broken,
            "コスト": (full, cached),
            "削減率": round((full - cached) / full * 100, 1)}


# --- 問題5: モデル階層 ---------------------------------------------------------
def tier_plan() -> dict:
    traj = detail_trajectory()
    high = tiered_cost(traj, route_all_high)
    tiered = tiered_cost(traj, route_by_role)
    threshold = tiered_cost(traj, route_threshold(5_000))
    bad = degraded_trajectory()
    return {"全部上位": high, "役割で振り分け": tiered, "閾値で格下げ": threshold,
            "削減率": round((high - tiered) / high * 100, 1),
            "階層": [r["階層"] for r in tier_rows(traj, route_by_role)],
            "成功": task_success(traj, EXPECTED),
            "格下げで壊れた版": {"手数": len(bad.steps),
                                 "成功": task_success(bad, EXPECTED),
                                 "再現率": tool_choice_accuracy(bad, EXPECTED),
                                 "適合率": round(precision(bad), 3),
                                 "余計なツール": [n for n in bad.tool_names
                                                  if n not in EXPECTED.tools]}}


# --- 問題6: 見積もり型の上限 ---------------------------------------------------
def guard_table() -> dict:
    rows = limit_rows()
    return {"上限": [r["上限"] for r in rows],
            "事後": [(r["事後"]["手数"], r["事後"]["in"], r["事後"]["停止理由"]) for r in rows],
            "見積": [(r["見積"]["手数"], r["見積"]["in"], r["見積"]["停止理由"]) for r in rows],
            "守れた上限（事後）": [r["上限"] for r in rows if r["事後"]["in"] <= r["上限"]],
            "守れた上限（見積）": [r["上限"] for r in rows if r["見積"]["in"] <= r["上限"]]}


# --- 問題7: ツール結果を実際に短くする -----------------------------------------
def slim_effect() -> dict:
    row = slim_row()
    full_len, slim_len = row["結果の文字数"]
    base_in, slim_in = row["入力の合計"]
    return {"結果の文字数": (full_len, slim_len),
            "半分以下になったか": slim_len * 2 < full_len,
            "入力の合計": (base_in, slim_in),
            "減った入力": base_in - slim_in,
            "ツール列は同じ": row["ツール列"][0] == row["ツール列"][1],
            "停止理由": row["停止理由"][1]}


# --- 問題8: 3層の上限 -----------------------------------------------------------
def daily_plan() -> dict:
    costs = [(r["シナリオ"], r["cu"]) for r in table_rows()]
    orders = (("到着順", costs), ("暴走が先", list(reversed(costs))))
    out: dict[str, dict] = {}
    for label, order in orders:
        out[label] = {}
        for key, per_task in (("上限なし", None), ("1タスク上限あり", PER_TASK_LIMIT)):
            rows = admit_rows(order, DAILY_LIMIT, per_task)
            out[label][key] = {"拒否": [r["タスク"] for r in rows if r["判定"] == "拒否"],
                               "合計": rows[-1]["累計"]}
    return out


# --- 問題9: 超過時の振る舞い -----------------------------------------------------
def behaviour_table() -> dict:
    rows = behaviour_rows()
    note = rows[2]["note"]
    return {"行": [(r["振る舞い"], r["手数"], r["cu"], r["停止理由"]) for r in rows],
            "上限内で完走した振る舞い": [r["振る舞い"] for r in rows
                                        if r["停止理由"] == "done" and r["cu"] <= 10_000],
            "引き継ぎ書の不足項目": check_handoff(note),
            "引き継ぎ書": note}


# --- 問題10: コスト上限の設計メモ -------------------------------------------------
REQUIRED_SECTIONS = ("測定条件", "上限の3層", "超過時の振る舞い", "削減の打ち手", "再評価")

DESIGN_MEMO = """# コスト上限の設計メモ（みなと商事 業務代行エージェント）

## 測定条件
- 近似トークン数（プロンプトの文字数 ÷ 3・比較用）。実 API の計測値ではない
- 単価は仮の単価表（上位 入力10 / 出力50 cu、下位 入力1 / 出力5 cu）。相対値であって金額ではない
- 2026-08-15 実測 / aarch64 / CPU 2コア / メモリ 5.8GB / Python 3.12.13

## 上限の3層
- 1タスク: 15,000 cu。見積もり型（CostGuard）で、次の1ステップを足してから判定する
- 1ユーザー: 1日 20,000 cu。超えたら以降は下位モデルのみに格下げする
- 全体: 1日 50,000 cu。超えたら新規の受け付けを止め、実行中のタスクは完走させる

## 超過時の振る舞い
- 既定は格下げ（downgrade）。上限の 50% を超えたら以降のステップを下位モデルに回す
- 格下げでも収まらない場合は打ち切り（fail）し、引き継ぎ書を出して人に渡す（handoff）
- 副作用を伴うツールの実行中は打ち切らない。ステップの境界でだけ止める

## 削減の打ち手（費用対効果の高い順）
1. ツール結果の削減: 残りステップ数だけ効く。早いステップの結果ほど優先して削る
2. モデル階層: 整形ステップを下位に回す。軌跡テストで挙動が変わらないことを確認する
3. ステップ削減: 計画を見直して手数を減らす。二次で効くので効果が最も大きい
4. 前方一致キャッシュ: 履歴の先頭を書き換えない。時刻・乱数を先頭に入れない

## 再評価
- モデルを差し替えたとき / ツール結果の形を変えたとき / 手数の中央値が 1 増えたとき
- 週次で「1タスクあたり単価の中央値と 95 パーセンタイル」を確認する
"""


def check_design(memo: str = DESIGN_MEMO) -> list[str]:
    """設計メモに必要な節がそろっているか（足りない節を返す）。"""
    return [s for s in REQUIRED_SECTIONS if s not in memo]


def main() -> None:
    for name, fn in (("問題1 単価表", cost_table), ("問題2 内訳", step_breakdown),
                     ("問題3 ツール結果", pad_effect), ("問題4 キャッシュ", cache_effect),
                     ("問題5 モデル階層", tier_plan), ("問題6 上限", guard_table),
                     ("問題7 結果の削減", slim_effect), ("問題8 3層の上限", daily_plan),
                     ("問題9 超過時の振る舞い", behaviour_table)):
        result = fn()
        if isinstance(result, dict):
            result = {k: v for k, v in result.items() if k not in ("行", "引き継ぎ書")}
        print(f"--- {name} ---\n{result}\n")
    print(f"--- 問題10 設計メモ ---\n不足している節: {check_design() or 'なし'}")


if __name__ == "__main__":
    main()
