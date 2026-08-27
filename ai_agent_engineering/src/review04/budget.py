#!/usr/bin/env python3
"""復習04：予算を超えたときに何を削るか（問題4）と、前提が変わると効く打ち手が
変わること（問題5）。

    python src/review04/budget.py

コスト削減の議論は「いちばん高いところを削る」で始まり、たいてい「いちばん品質を
落とすところを削った」で終わる。そうならないために、この章では2つだけ決めておく。

  ① 打ち手には**失うもの**を必ず書く。書けない打ち手は評価できない
  ② 選ぶ順は削減額の大きい順ではなく、**失うものが小さい順**。予算に収まったら止める

金額はすべて厘（1/1000円）の整数で持つ。単価表は S14 の所要の単価表と同じく
**こちらが宣言する固定値**であり、実在モデルの料金ではない。
"""

from __future__ import annotations

from dataclasses import dataclass

from _paths import setup

ROOT = setup()

from signals import (BUDGET_RIN, PRICES, PRICES_OUT_HEAVY, WORKLOAD,  # noqa: E402
                     find_row, input_output_rin, monthly_rin, rin, row_rin, yen)


@dataclass(frozen=True)
class Action:
    """コストの打ち手。**失うもの**と**効いたことの確かめ方**まで含めて1つ。"""

    code: str
    label: str
    target: str          # 対象のシナリオ（"*" は全シナリオ）
    effect: str          # tier（下位モデルに落とす）/ drop（受けない）/ input / output
    loses: str           # 失うもの
    loss_rank: int       # 失うものの重さ（小さいほど先に選ぶ）
    checked_by: str      # 効いたことをどう確かめるか
    num: int = 1         # input / output のときの削減率（分子）
    den: int = 1         # input / output のときの削減率（分母）


def savings(action: Action, prices: dict | None = None) -> int:
    """1か月あたりの削減額（厘）。整数だけで出す。"""
    prices = prices or PRICES
    rows = WORKLOAD if action.target == "*" else (find_row(action.target),)
    total = 0
    for row in rows:
        _label, count, _steps, in_tok, out_tok = row
        if action.effect == "tier":
            total += count * (rin(in_tok, out_tok, "上位", prices)
                              - rin(in_tok, out_tok, "下位", prices))
        elif action.effect == "drop":
            total += count * rin(in_tok, out_tok, "上位", prices)
        elif action.effect == "input":
            total += count * in_tok * prices["上位"]["in"] * action.num // action.den
        elif action.effect == "output":
            total += count * out_tok * prices["上位"]["out"] * action.num // action.den
        else:
            raise ValueError(f"未知の効き方です: {action.effect!r}")
    return total


# ---------------------------------------------------------------------------
# 問題4：予算に収める（失うものが小さい順に足す）
# ---------------------------------------------------------------------------
ACTIONS: tuple[Action, ...] = (
    Action("P1", "会議室予約を下位モデルに落とす", "会議室予約（競合あり）", "tier",
           "なし（整形だけの型）", 1,
           "S13 の3点セット（軌跡・副作用の状態・成果物の中身）"),
    Action("P4", "隔離実行の集計を月次の締めだけに寄せる", "隔離実行で集計", "drop",
           "即時性（当日中には出ない）と、日々の集計そのもの（60件/月 → 締めの1回に統合）", 2,
           "S15 の同期／非同期＋通知／バッチの選択表"),
    Action("P3", "反復するタスクを受け付けない", "同じ検索を繰り返す", "drop",
           "40 件を断る", 3,
           "S14 の症状「同じ操作の反復」の件数が 0 になること"),
    Action("P2", "経費レポート作成を下位モデルに落とす", "経費レポート作成", "tier",
           "判断を含む型の品質", 4,
           "成果物の内容検査（S15 の D 型：軌跡は同じで中身だけ薄くなる）"),
)


def by_code(code: str) -> Action:
    for action in ACTIONS:
        if action.code == code:
            return action
    raise KeyError(f"未知の打ち手です: {code}")


def plan(budget_rin: int = BUDGET_RIN, prices: dict | None = None) -> dict:
    """予算に収まる最小の組み合わせを返す。

    **削減額の大きい順に選ばない。** 失うものが小さい順に足し、収まった時点で止める。
    こうしないと「いちばん効く打ち手＝いちばん品質を落とす打ち手」を毎回選ぶことになる。
    """
    total = monthly_rin(prices=prices)
    over = max(total - budget_rin, 0)
    picked: list[str] = []
    saved = 0
    for action in sorted(ACTIONS, key=lambda a: a.loss_rank):
        if saved >= over:
            break
        picked.append(action.code)
        saved += savings(action, prices)
    warning = ("品質を落とす打ち手（P2）に手を付ける段階である。"
               "受け付ける件数そのものを減らす判断を人に上げること。"
               if "P2" in picked else "—")
    return {"total": total, "budget": budget_rin, "over": over,
            "picked": picked, "saved": saved, "after": total - saved,
            "remaining": max(over - saved, 0), "warning": warning}


BUDGETS = (25_000_000, 20_000_000, 10_000_000, 30_000_000)


# ---------------------------------------------------------------------------
# 問題5：前提（単価表）が変わると、効く打ち手が入れ替わる
# ---------------------------------------------------------------------------
ASSUMPTIONS: tuple[tuple[str, dict], ...] = (
    ("前提① 入力が支配的（既定の単価表）", PRICES),
    ("前提② 出力の単価が入力の50倍", PRICES_OUT_HEAVY),
)

# 前提の効き方を見るための4つ。入力だけに効くもの・出力だけに効くものを混ぜてある。
# input / output の削減率（30% と 50%）は**宣言値**であり、実測ではない。
# 各自の環境で測って差し替える前提の値である。
SHIFTS: tuple[Action, ...] = (
    Action("A1", "会議室予約を下位モデルに落とす", "会議室予約（競合あり）", "tier",
           "なし（整形だけの型）", 1, "S13 の3点セット"),
    Action("A2", "反復するタスクを受け付けない", "同じ検索を繰り返す", "drop",
           "40 件を断る", 3, "S14 の症状の件数"),
    Action("A3", "ツール結果を切り詰める（入力の30%）", "経費レポート作成", "input",
           "ツール結果の情報量", 2, "成果物の内容検査", 3, 10),
    Action("A4", "最終回答を半分の長さにする（出力の50%）", "*", "output",
           "回答の詳しさ", 2, "最終回答の期待語の検査", 1, 2),
)


def ranked_under(prices: dict) -> list[dict]:
    """1つの前提のもとで、打ち手を削減額の大きい順に並べる。"""
    rows = [{"code": a.code, "label": a.label, "saved": savings(a, prices)}
            for a in SHIFTS]
    rows.sort(key=lambda r: (-r["saved"], r["code"]))
    for i, row in enumerate(rows, start=1):
        row["rank"] = i
    return rows


def rank_map(prices: dict) -> dict[str, int]:
    return {row["code"]: row["rank"] for row in ranked_under(prices)}


def robust_rows() -> list[dict]:
    """2つの前提での順位を並べ、**悪い方の順位**で評価する。"""
    ranks = [rank_map(prices) for _label, prices in ASSUMPTIONS]
    saved = [{row["code"]: row["saved"] for row in ranked_under(prices)}
             for _label, prices in ASSUMPTIONS]
    rows = []
    for action in SHIFTS:
        r1, r2 = ranks[0][action.code], ranks[1][action.code]
        rows.append({"code": action.code, "label": action.label,
                     "saved1": saved[0][action.code], "rank1": r1,
                     "saved2": saved[1][action.code], "rank2": r2,
                     "worst": max(r1, r2)})
    return rows


def robust_pick() -> str:
    """どちらの前提でも上位に来る打ち手を1つ返す。"""
    rows = sorted(robust_rows(), key=lambda r: (r["worst"], r["rank1"], r["code"]))
    return rows[0]["code"]


# ---------------------------------------------------------------------------
def main() -> None:
    total = monthly_rin()
    print("=== 予算超過にどう応じるか（仮の単価表・上位モデル）===")
    print(f"月次の費用 {yen(total)} 円 / 予算 {yen(BUDGET_RIN)} 円 / "
          f"超過 {yen(max(total - BUDGET_RIN, 0))} 円")

    print("\n=== 打ち手（失うものが小さい順）===")
    print("順 | ID | 打ち手 | 削減額(円) | 失うもの | 効いたことの確かめ方")
    for i, action in enumerate(sorted(ACTIONS, key=lambda a: a.loss_rank), start=1):
        print(f"{i} | {action.code} | {action.label} | {yen(savings(action))} | "
              f"{action.loses} | {action.checked_by}")

    print("\n=== 予算ごとの選択（失うものが小さい順に足し、収まったら止める）===")
    print("予算(円) | 超過(円) | 選ぶ打ち手 | 削減(円) | 残る費用(円) | 残る超過(円)")
    for budget in BUDGETS:
        p = plan(budget)
        print(f"{yen(p['budget'])} | {yen(p['over'])} | "
              f"{'+'.join(p['picked']) or '（なし）'} | {yen(p['saved'])} | "
              f"{yen(p['after'])} | {yen(p['remaining'])}")
    warned = plan(10_000_000)
    print(f"※ 予算 {yen(warned['budget'])} 円のときの申し送り: {warned['warning']}")

    print("\n=== 前提を変えると内訳の1位が入れ替わる ===")
    print("前提 | 入力(円) | 出力(円) | 合計(円) | 1位")
    for label, prices in ASSUMPTIONS:
        split = input_output_rin(prices)
        print(f"{label} | {yen(split['in'])}（{split['in_share']:.1f}%） | "
              f"{yen(split['out'])}（{split['out_share']:.1f}%） | "
              f"{yen(split['total'])} | {split['top']}")

    print("\n=== 同じ4つの打ち手を2つの前提で並べ替える ===")
    print("ID | 打ち手 | 前提①の削減(円) | 順位 | 前提②の削減(円) | 順位 | 悪い方の順位")
    for row in robust_rows():
        print(f"{row['code']} | {row['label']} | {yen(row['saved1'])} | {row['rank1']} | "
              f"{yen(row['saved2'])} | {row['rank2']} | {row['worst']}")
    print(f"→ どちらの前提でも上位に来るのは {robust_pick()}。"
          "前提を確かめずに内訳の1位へ手を付けると、効かない打ち手を選ぶ。")

    print("\n=== 1件あたりの単価（参考・仮の単価表）===")
    print("シナリオ | 上位(円) | 下位(円)")
    for row in WORKLOAD:
        print(f"{row[0]} | {yen(row_rin(row, '上位'))} | {yen(row_rin(row, '下位'))}")


if __name__ == "__main__":
    main()
