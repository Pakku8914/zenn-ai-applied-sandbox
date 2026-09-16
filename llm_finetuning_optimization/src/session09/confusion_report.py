#!/usr/bin/env python3
"""混同表の整形と派生指標（セッション9）。

`ftkit.evaluate.EvalResult.confusion()` が返す表を、

  - レポートにそのまま貼れる Markdown 表
  - micro（全体）と macro（クラス平均）の正解率
  - 崩壊率（最大の予測クラスが全体に占める割合）

に変換する。**モデルを読まないので数秒で終わる。**

  python src/session09/confusion_report.py

このファイルに置いてある2つの表は **合成** である。実測から分かっているのは
「対角（区分ごとの正解数）」「各区分の件数」「正解率」「形式遵守率」だけで、
誤りがどの区分に流れたか（対角以外）は公開された実測値に含まれていない。
指標の計算を検算するための材料として、誤りの行き先だけをこちらで置いている。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ftkit.evaluate import EvalResult  # noqa: E402

# --- 実測の出典 -------------------------------------------------------------
# 測定条件：2026-08-15 実測 / aarch64 / CPU 2コア / メモリ 5.8GB /
#           Python 3.12.13 / torch 2.13.0+cpu / OMP_NUM_THREADS=2
#
# Qwen2.5-0.5B-Instruct / format / 80 step / test 先頭30件 / bf16
#   正解率 0.833（25/30）・形式遵守率 1.000（30/30）
#   対角は 経費 5/6・勤怠 3/3・PC 3/5・アカウント 2/3・オフィス 7/7・セキュリティ 5/6
QWEN_AFTER_SPEC: dict[str, dict[str, int]] = {
    "経費": {"経費": 5, "勤怠": 1},
    "勤怠": {"勤怠": 3},
    "PC": {"PC": 3, "アカウント": 2},
    "アカウント": {"PC": 1, "アカウント": 2},
    "オフィス": {"オフィス": 7},
    "セキュリティ": {"セキュリティ": 5, "不明": 1},   # 3行の形は守ったが区分名が6つのどれでもない
}
QWEN_AFTER_FORMAT_OK = 30

# SmolLM2-135M-Instruct / classify / 60 step / test 先頭30件 / fp32
#   正解率 0.200（6/30）・形式遵守率 0.933（28/30）
#   予測が「アカウント」に 21 件集中している（1クラスへの崩壊）
SMOL_AFTER_SPEC: dict[str, dict[str, int]] = {
    "経費": {"経費": 2, "アカウント": 4},
    "勤怠": {"アカウント": 3},
    "PC": {"PC": 1, "アカウント": 4},
    "アカウント": {"アカウント": 3},
    "オフィス": {"アカウント": 7},
    "セキュリティ": {"経費": 4, "回答できません": 2},   # 2件は区分名を返せていない
}
SMOL_AFTER_FORMAT_OK = 28


def build_result(spec: dict[str, dict[str, int]], format_ok: int) -> EvalResult:
    """(正解, 予測, 件数) の指定から EvalResult を組み立てる（モデルを読まない）。"""
    result = EvalResult(format_ok=format_ok)
    index = 0
    for gold, predictions in spec.items():
        for predicted, count in predictions.items():
            for _ in range(count):
                index += 1
                result.predictions.append((f"S-{index:04d}", gold, predicted))
                result.n += 1
                result.correct += int(predicted == gold)
    return result


def column_totals(table: dict[str, dict[str, int]]) -> dict[str, int]:
    """予測ごとの件数（列合計）。1クラスへの崩壊はここに現れる。"""
    keys = list(next(iter(table.values())).keys())
    return {key: sum(row[key] for row in table.values()) for key in keys}


def row_totals(table: dict[str, dict[str, int]]) -> dict[str, int]:
    """正解ごとの件数（行合計）。評価セットのクラス分布そのもの。"""
    return {gold: sum(row.values()) for gold, row in table.items()}


def macro_accuracy(table: dict[str, dict[str, int]]) -> float:
    """クラス別正解率の単純平均。件数の少ない区分も1票として数える。"""
    rates = [row[gold] / total for gold, row in table.items()
             if (total := sum(row.values()))]
    return sum(rates) / len(rates) if rates else 0.0


def collapse_ratio(table: dict[str, dict[str, int]]) -> tuple[str, int, float]:
    """最大の予測クラスとその比率。1.000 に近いほど「1クラスへの崩壊」。"""
    totals = column_totals(table)
    total = sum(totals.values())
    top = max(totals, key=lambda key: totals[key])
    return top, totals[top], (totals[top] / total if total else 0.0)


def render_markdown(table: dict[str, dict[str, int]]) -> str:
    """Markdown の表にする。評価レポートにそのまま貼れる形にしておく。"""
    keys = list(next(iter(table.values())).keys())
    lines = ["| 正解＼予測 | " + " | ".join(keys) + " |",
             "| :--- |" + " ---: |" * len(keys)]
    for gold, row in table.items():
        lines.append(f"| {gold} | " + " | ".join(str(row[key]) for key in keys) + " |")
    return "\n".join(lines)


def summarize(result: EvalResult) -> str:
    """1行の要約。loss を含めないのが要点（loss は学習の指標で成否の指標ではない）。"""
    table = result.confusion()
    top, count, ratio = collapse_ratio(table)
    return (f"n={result.n} micro={result.accuracy:.3f} macro={macro_accuracy(table):.3f} "
            f"最大予測クラス={top}({count}) 崩壊率={ratio:.3f} "
            f"形式遵守率={result.format_rate:.3f}")


def main() -> None:
    for title, spec, format_ok in (
        ("Qwen2.5-0.5B / format / 80 step（対角は実測・誤りの行き先は合成）",
         QWEN_AFTER_SPEC, QWEN_AFTER_FORMAT_OK),
        ("SmolLM2-135M / classify / 60 step（対角は実測・誤りの行き先は合成）",
         SMOL_AFTER_SPEC, SMOL_AFTER_FORMAT_OK),
    ):
        result = build_result(spec, format_ok)
        print(f"=== 学習後の混同表：{title} ===")
        print(render_markdown(result.confusion()))
        print(summarize(result))
        print()


if __name__ == "__main__":
    main()
