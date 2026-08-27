#!/usr/bin/env python3
"""復習04：今週の測定結果（材料）。4系統を1枚のボードに並べる。

    python src/review04/signals.py

運用当番が手にしているのは4つの数字の束である。

  測る（S13）  … 期待どおりか（成功率・期待整合率・再現率・適合率・手数）
  追う（S14）  … どこで壊れたか（スパン・症状の頻度・記録の残し方）
  回す（S15）  … 間に合うか（多重度・レート上限・完了の下限・段階リリース）
  支払う       … いくら払うか（仮の単価表 × 月次のワークロード）

このファイルは**材料だけ**を持つ。材料から次の一手を決めるのは他のモジュールである。
測る・追う・回すの値は既存セッションの実測を転記した宣言（出典を併記）で、
支払うの値だけは本章の仮の単価表から決定的に計算する。
"""

from __future__ import annotations

from _paths import setup

ROOT = setup()

from evalspec import CASES as S13_CASES  # noqa: E402  （S13：評価する6ケースの宣言）
from judges import JUDGES  # noqa: E402   （S13：判定方式3種＋厳格版の名前）

FAMILIES = ("測る", "追う", "回す", "支払う")

# ---------------------------------------------------------------------------
# ① 測る（出典: python src/session13/scoreboard.py・2026-08-15 実測）
# ---------------------------------------------------------------------------
QUALITY = {
    "cases": 6,
    "success_rate": 0.667,      # 期待どおり失敗すべき2件を含むので 1.000 にはならない
    "declared_rate": 1.000,     # 「期待どおりか」で数え直すと 1.000
    "recall": 1.000,            # 呼ぶべきツールは全部呼んでいる
    "precision": 0.750,         # 余計な呼び出しが 7 回ある
    "extra_calls": 7,
    "mean_steps": 3.83,
    "step_dist": {3: 3, 4: 2, 6: 1},
}

# ---------------------------------------------------------------------------
# ② 追う（出典: python src/session14/failtags.py・python src/session14/breakdown.py）
# ---------------------------------------------------------------------------
TRACE = {
    "traces": 8, "failures": 5, "symptom_kinds": 6,
    "top_symptom": "同じ操作の反復", "top_count": 2,
    "spans_ok": 12,             # 経費レポート作成（task 1 / step 4 / llm 4 / tool 3）
    "spans_bad": 19,            # 同じ検索を繰り返す（task 1 / step 6 / llm 6 / tool 6）
    "share_llm_units_a": 97.1,  # 単価表 A（LLM が支配的）での llm の割合
    "share_tool_units_b": 81.8,  # 単価表 B（ツールが支配的）での tool の割合
}

# ---------------------------------------------------------------------------
# ③ 回す（出典: python src/session15/queue_sim.py・1ステップ＝1ティック＝1仮想秒）
# ---------------------------------------------------------------------------
OPS = {
    "jobs": 8, "total_steps": 24, "rate_limit": 2,
    "floor_seconds": 12,        # のべ 24 回 ÷ 上限 2 回/秒
    "knee_workers": 2,          # ここで下限に届く。以降は待ちだけが増える
    "makespan": {1: 24, 2: 12, 4: 13, 8: 12},
}

# ---------------------------------------------------------------------------
# ④ 支払う（本章の宣言）
# ---------------------------------------------------------------------------
# **仮の単価表**（実在モデルの料金ではない。比較のために本章が宣言する固定値である）。
# 単位は「近似トークン 1,000 件あたりの円」。
# 近似トークン数（比較用）＝プロンプトの文字数 ÷ 3 であり、実 API の計測値ではない。
PRICES = {
    "上位": {"in": 30, "out": 150},
    "下位": {"in": 3, "out": 15},        # 上位の 1/10
}

# 出力の単価が入力の 50 倍になる仮の単価表（前提②）。
# S14 で単価表を差し替えると内訳の1位が入れ替わったのと同じことを、費用でも見る。
PRICES_OUT_HEAVY = {
    "上位": {"in": 30, "out": 1500},
    "下位": {"in": 3, "out": 150},
}

# 月次のワークロード。件数は本章の宣言、手数と近似トークン数は
# `tools/traj_stats.py`（2026-08-15 実測）の値である。
# (ラベル, 件数/月, 手数, 近似in, 近似out)
WORKLOAD = (
    ("経費レポート作成", 400, 4, 1022, 48),
    ("会議室予約（競合あり）", 300, 3, 436, 35),
    ("経費申請（5万円以上）", 200, 3, 449, 34),
    ("隔離実行で集計", 60, 3, 722, 23),
    ("同じ検索を繰り返す", 40, 6, 2966, 12),
)

BUDGET_RIN = 25_000_000        # 月次予算 25,000 円（厘＝1/1000円で持つ）


def rin(in_tok: int, out_tok: int, tier: str = "上位", prices: dict | None = None) -> int:
    """1件のコストを厘（1/1000円）の整数で返す。

    **整数だけで計算する。** 金額を float で積み上げると、同じ表を2回作っただけで
    末尾がずれ、「昨日と数字が違う」という不毛な議論が生まれる。
    """
    p = (prices or PRICES)[tier]
    return in_tok * p["in"] + out_tok * p["out"]


def yen(value_rin: int) -> str:
    """厘を円の文字列にする（小数第3位まで）。"""
    return f"{value_rin / 1000:,.3f}"


def row_rin(row: tuple, tier: str = "上位", prices: dict | None = None) -> int:
    """1行（シナリオ）の1件あたりコスト。"""
    _label, _count, _steps, in_tok, out_tok = row
    return rin(in_tok, out_tok, tier, prices)


def monthly_rin(tier: str = "上位", prices: dict | None = None) -> int:
    """月次の合計コスト。"""
    return sum(row[1] * row_rin(row, tier, prices) for row in WORKLOAD)


def find_row(label: str) -> tuple:
    for row in WORKLOAD:
        if row[0] == label:
            return row
    raise KeyError(f"未知のシナリオです: {label}")


def input_output_rin(prices: dict | None = None, tier: str = "上位") -> dict:
    """月次コストを入力ぶんと出力ぶんに割る。**1位は単価表で入れ替わる。**"""
    p = (prices or PRICES)[tier]
    in_rin = sum(count * in_tok * p["in"] for _l, count, _s, in_tok, _o in WORKLOAD)
    out_rin = sum(count * out_tok * p["out"] for _l, count, _s, _i, out_tok in WORKLOAD)
    total = in_rin + out_rin
    return {"in": in_rin, "out": out_rin, "total": total,
            "in_share": in_rin / total * 100, "out_share": out_rin / total * 100,
            "top": "入力" if in_rin >= out_rin else "出力"}


# ---------------------------------------------------------------------------
# 問題1：どの問いが、どの測定で答えられるか
# ---------------------------------------------------------------------------
# (ID, 問い, 答えられる系統, 出どころ)
QUESTIONS = (
    ("Q1-01", "先週の差し替えでタスクの成功率が下がったか", "測る",
     "src/session13/scoreboard.py"),
    ("Q1-02", "失敗した1件が、どのステップで壊れたか", "追う",
     "src/session14/spanlog.py"),
    ("Q1-03", "多重度を4に上げると完了は速くなるか", "回す",
     "src/session15/queue_sim.py"),
    ("Q1-04", "1タスクあたりいくら払っているか", "支払う",
     "src/review04/signals.py"),
    ("Q1-05", "同じ症状が今週何件出たか", "追う",
     "src/session14/failtags.py"),
    ("Q1-06", "正しい道具を使ったのに失敗した件数はいくつか", "測る",
     "src/session13/scoreboard.py"),
    ("Q1-07", "レート上限に当たって捨てた呼び出しは何回か", "回す",
     "src/session15/ratelimit.py"),
    ("Q1-08", "費用は入力と出力のどちらが支配的か", "支払う",
     "src/review04/budget.py"),
    ("Q1-09", "承認者は中身を読んでから承認しているか", "—",
     "この4系統では答えられない"),
    ("Q1-10", "実モデルに差し替えても同じ軌跡になるか", "—",
     "この4系統では答えられない"),
)


def truth_q1() -> dict[str, str]:
    return {qid: family for qid, _q, family, _src in QUESTIONS}


# ---------------------------------------------------------------------------
def board() -> list[tuple[str, str, str, str]]:
    """4系統を1行ずつにまとめたボード。"""
    cost = monthly_rin()
    return [
        ("測る", "期待どおりか", "python src/session13/scoreboard.py",
         f"{QUALITY['cases']} ケース / 成功率 {QUALITY['success_rate']:.3f} / "
         f"期待整合率 {QUALITY['declared_rate']:.3f} / 再現率 {QUALITY['recall']:.3f} / "
         f"適合率 {QUALITY['precision']:.3f} / 平均手数 {QUALITY['mean_steps']:.2f}"),
        ("追う", "どこで壊れたか", "python src/session14/failtags.py",
         f"{TRACE['traces']} 件 / 失敗 {TRACE['failures']} 件 / "
         f"症状 {TRACE['symptom_kinds']} 種 / "
         f"1位「{TRACE['top_symptom']}」{TRACE['top_count']} 件"),
        ("回す", "間に合うか", "python src/session15/queue_sim.py",
         f"のべ {OPS['total_steps']} ステップ / 完了の下限 {OPS['floor_seconds']} 仮想秒 / "
         f"頭打ちの多重度 {OPS['knee_workers']}"),
        ("支払う", "いくら払うか", "本章の仮の単価表",
         f"{sum(r[1] for r in WORKLOAD):,} 件/月 / {yen(cost)} 円 / "
         f"予算 {yen(BUDGET_RIN)} 円 / 超過 {yen(max(cost - BUDGET_RIN, 0))} 円"),
    ]


def main() -> None:
    print("=== 今週の測定結果（4系統）===")
    print("系統 | 測るもの | 出どころ | 今週の値")
    for family, what, src, value in board():
        print(f"{family} | {what} | {src} | {value}")

    total = monthly_rin()
    print("\n=== 支払う：月次のワークロードと費用（仮の単価表・上位モデル）===")
    print("シナリオ | 件数/月 | 手数 | 近似in | 近似out | 1件(円) | 月額(円) | 費用シェア")
    for row in WORKLOAD:
        label, count, steps, in_tok, out_tok = row
        per = row_rin(row)
        print(f"{label} | {count} | {steps} | {in_tok:,} | {out_tok} | "
              f"{yen(per)} | {yen(count * per)} | {count * per / total * 100:.1f}%")
    print(f"合計 | {sum(r[1] for r in WORKLOAD):,} | — | — | — | — | "
          f"{yen(total)} | {total / total * 100:.1f}%")

    loop = find_row("同じ検索を繰り返す")
    report = find_row("経費レポート作成")
    print("\n=== 件数のシェアと費用のシェアは一致しない ===")
    print(f"{loop[0]}: 件数 {loop[1] / sum(r[1] for r in WORKLOAD) * 100:.1f}% / "
          f"費用 {loop[1] * row_rin(loop) / total * 100:.1f}%"
          f"（1件 {yen(row_rin(loop))} 円は「{report[0]}」の "
          f"{row_rin(loop) / row_rin(report):.2f} 倍）")

    print("\n=== 材料の出どころ（S13 の宣言をそのまま使う）===")
    print(f"評価するケース: {len(S13_CASES)} 件"
          f"（うち期待どおり失敗すべき "
          f"{sum(1 for c in S13_CASES if not c.expect_success)} 件）")
    print(f"判定方式: {' / '.join(JUDGES)}")

    print("\n=== 問題1の材料：この4系統で答えられる問い・答えられない問い ===")
    print("ID | 問い | 出どころ")
    for qid, question, _family, src in QUESTIONS:
        print(f"{qid} | {question} | {src}")
    print("※ 答え（どの系統で答えられるか）は伏せてある。src/review04/answers.py に書くこと。")


if __name__ == "__main__":
    main()
