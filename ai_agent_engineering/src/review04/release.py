#!/usr/bin/env python3
"""復習04：この変更を出してよいか（問題2）と、カナリアの判定を採用してよいか（問題7）。

    python src/review04/release.py

出す・出さないの判断は、測定が足りていれば機械で決まる。難しいのは2点だけである。

  ① 受け入れ基準の数字（手数を何倍まで許すか）を**先に**決めて書いておくこと
  ② 判定そのものを採用してよいかを、判定より先に確かめること

②は段階リリースで効く。「先頭から 5%」のカナリアは S15 の実測で「進む」と言うが、
その 5% には壊れる型（`send`）が1件も入っていない。**当たっていない検査は、
通ったのではなく試していない**。だから判定の前に、母集団の型が網羅されているかを見る。

`agentkit` と S15 の実装は1行も変更しない。足すのは受け入れ基準と前提チェックだけである。
"""

from __future__ import annotations

from _paths import reset_data, setup

ROOT = setup()

from jobspec import clear_workspace  # noqa: E402
from opsconfig import OpsConfig  # noqa: E402
from rollout import KIND_ORDER, run_rollout  # noqa: E402
from swap import accept_swap, swap_rows  # noqa: E402

# 受け入れ基準。ops.json の max_step_ratio（既定 1.2）と同じ値を使う。
MAX_STEP_RATIO = 1.2
LOOSE_STEP_RATIO = 1.5


# ---------------------------------------------------------------------------
# 問題2：差し替えを出してよいか
# ---------------------------------------------------------------------------
def release_verdict(row: dict, max_step_ratio: float = MAX_STEP_RATIO) -> tuple[str, str]:
    """「出す／様子を見る／出さない」を1つ返す。判断の順に意味がある。

    禁止ツール → 成果物の中身 → 手数（コスト）→ ツール列の変化 の順に見る。
    安全に関わるものを先に見るので、コストの基準を緩めても安全の判断は変わらない。
    """
    if row["forbidden"]:
        return "出さない", "禁止ツールを呼ぶ"
    if row["missing"]:
        return "出さない", f"成果物に {'／'.join(row['missing'])} が無い"
    before, after = row["steps"]
    if before and after > before * max_step_ratio:
        return "出さない", f"手数が {before}→{after}（基準の {max_step_ratio} 倍を超えた）"
    if not row["same_tools"]:
        return "様子を見る", "ツール列が変わった（手数は基準内。コストで判断する）"
    return "出す", "軌跡・副作用の状態・成果物の中身の3点で差が無い"


def swap_table() -> list[dict]:
    """4つの新構成を、2つの受け入れ基準にかける。"""
    reset_data()
    clear_workspace()
    rows = [r for r in swap_rows() if not r["base"]]
    out = []
    for row in rows:
        strict = release_verdict(row, MAX_STEP_RATIO)
        loose = release_verdict(row, LOOSE_STEP_RATIO)
        out.append({"label": row["label"], "same_tools": row["same_tools"],
                    "steps": row["steps"], "missing": row["missing"],
                    "forbidden": len(row["forbidden"]),
                    "厳しい基準": strict, "緩い基準": loose,
                    "S15 の判断": accept_swap(row)})
    reset_data()
    clear_workspace()
    return out


# ---------------------------------------------------------------------------
# 問題7：カナリアの判定を採用してよいか
# ---------------------------------------------------------------------------
def missing_kinds(arm) -> list[str]:
    """カナリアに1件も入らなかった型。ここが空でないと判定は使えない。"""
    return [kind for kind in KIND_ORDER if arm.kinds[kind] == 0]


def adopt(row: dict) -> tuple[str, str]:
    """カナリアの結果を採用してよいか。**判定より前に前提を見る。**"""
    if row["missing"]:
        return "判定を採用しない", (f"型 {'・'.join(row['missing'])} が1件も入っていない"
                                    "（通ったのではなく試していない）")
    if row["verdict"] == "止める":
        return "止める", row["why"]
    return "進む", row["why"]


def canary_table() -> list[dict]:
    """先頭から 5%・25% と、型ごとに 5% の3行。"""
    reset_data()
    clear_workspace()
    cfg = OpsConfig.load()
    plans = (("先頭から", "head", cfg),
             ("型ごとに", "stratified", cfg.with_(canary_percents=(5,))))
    out = []
    for label, strategy, conf in plans:
        for row in run_rollout(conf, strategy):
            arm = row["new"]
            record = {"選び方": label, "段階": f"{row['percent']}%", "件数": row["n"],
                      "型の内訳": arm.kind_breakdown(), "成功": arm.success,
                      "禁止": arm.forbidden, "verdict": row["verdict"],
                      "why": row["why"], "missing": missing_kinds(arm)}
            record["採用"], record["理由"] = adopt(record)
            out.append(record)
    reset_data()
    clear_workspace()
    return out


# ---------------------------------------------------------------------------
def main() -> None:
    print(f"=== 差し替えを出してよいか（受け入れ基準 max_step_ratio={MAX_STEP_RATIO}）===")
    rows = swap_table()
    print("構成 | ツール列 | 手数 | 成果物の不足 | 禁止ツール | 判断 | 理由")
    for row in rows:
        verdict, why = row["厳しい基準"]
        print(" | ".join([
            row["label"],
            "同一" if row["same_tools"] else "変化",
            f"{row['steps'][0]}→{row['steps'][1]}",
            "／".join(row["missing"]) or "なし",
            str(row["forbidden"]),
            verdict, why,
        ]))

    print(f"\n=== 基準を {LOOSE_STEP_RATIO} に緩めると判断が変わる ===")
    print(f"構成 | {MAX_STEP_RATIO} のとき | {LOOSE_STEP_RATIO} のとき")
    for row in rows:
        print(f"{row['label']} | {row['厳しい基準'][0]} | {row['緩い基準'][0]}")
    print("→ 変わるのはコストの判断だけである。禁止ツールと成果物の不足は"
          "どちらの基準でも「出さない」に落ちる。")

    print("\n=== カナリアの判定を採用してよいか ===")
    print("選び方 | 段階 | 件数 | 型の内訳 | 新:成功 | 新:禁止 | rollout の判定 | 採用 | 理由")
    for row in canary_table():
        print(" | ".join([
            row["選び方"], row["段階"], str(row["件数"]), row["型の内訳"],
            str(row["成功"]), str(row["禁止"]), row["verdict"],
            row["採用"], row["理由"],
        ]))
    print("→ 先頭から 5% の「進む」は判定として使えない。"
          "同じ 5% でも型ごとに1件ずつ選べば、同じ欠陥に当たる。")


if __name__ == "__main__":
    main()
