#!/usr/bin/env python3
"""セッション5：学習曲線から「収束したか」を判定する。

  python src/session05/curve_report.py

モデルを読まないので一瞬で終わる。やること:
  1. loss 列を区間平均で要約する（最後の1点だけを見ないため）
  2. 「下降中 / 頭打ち / 発散」を判定する
  3. 合成データで判定器そのものを検証する（外れたら非0で終了する）
  4. runs/*.json があれば、実際の学習曲線も同じ判定にかける（無ければ飛ばす）

**早期終了（悪化したら止める）はここでは実装しない。** 判定を表示するだけに
とどめる（止める仕組みはセッション7で扱う）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import fmean

RUNS = Path(__file__).resolve().parents[2] / "runs"

DIVERGED = 1.10   # 後半平均が前半平均の 1.10 倍を超えたら「発散」
IMPROVING = 0.05  # 直前区間から 5% 以上良くなっていれば「下降中」

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def summarize(losses: list[float], window: int = 5) -> dict:
    """loss 列を3つの区間平均に潰し、収束の状態を判定する。

    1 step ごとの loss はバッチの中身で大きく揺れる。最後の1点で判断すると
    「たまたま簡単なバッチだった」だけで成功に見えてしまうので、必ず区間平均で見る。
    """
    if len(losses) < window * 3:
        raise ValueError(f"最低 {window * 3} step 必要です（今 {len(losses)} step）")

    early = fmean(losses[:window])                     # 最初の window step
    middle = fmean(losses[-2 * window: -window])       # 終盤の1つ前の区間
    late = fmean(losses[-window:])                     # 最後の window step

    total_gain = early / late if late > 0 else float("inf")
    recent_gain = (middle - late) / middle if middle > 0 else 0.0

    if late > early * DIVERGED:
        verdict = "発散"
    elif recent_gain >= IMPROVING:
        verdict = "下降中"
    else:
        verdict = "頭打ち"

    return {"steps": len(losses), "early": early, "middle": middle, "late": late,
            "total_gain": total_gain, "recent_gain": recent_gain, "verdict": verdict}


def render(name: str, report: dict) -> str:
    return (f"{name:<22} {report['verdict']:<6} "
            f"前半 {report['early']:.4f} -> 後半 {report['late']:.4f} "
            f"（{report['total_gain']:.1f} 倍改善 / 直近 {report['recent_gain'] * 100:+.1f}%）")


def main() -> int:
    # --- 判定器そのものを合成データで検証する -------------------------------
    falling = [3.0 * 0.9 ** i for i in range(30)]                   # ずっと下がる
    plateau = [3.0 * 0.9 ** i for i in range(20)] + [0.3] * 10      # 途中で止まる
    rising = [1.0 + 0.1 * i for i in range(30)]                     # 上がっていく
    wobbling = [1.0 + (0.2 if i % 2 else -0.2) for i in range(30)]  # 揺れているだけ

    print("--- 判定器の検証（合成データ）---")
    for name, series, expected in (("下がり続ける", falling, "下降中"),
                                   ("途中で止まる", plateau, "頭打ち"),
                                   ("上がっていく", rising, "発散"),
                                   ("揺れているだけ", wobbling, "頭打ち")):
        report = summarize(series)
        print(render(name, report))
        check(f"{name} → {expected} と判定する", report["verdict"] == expected,
              f"判定={report['verdict']}")

    report = summarize(falling)
    check("改善倍率が計算できる", 13.0 < report["total_gain"] < 15.0,
          f"{report['total_gain']:.1f} 倍")

    try:
        summarize([1.0] * 10)
        check("step が少なすぎる列は例外にする", False, "例外が出なかった")
    except ValueError as exc:
        check("step が少なすぎる列は例外にする", True, str(exc))

    # --- 実際の学習結果があれば同じ判定にかける -----------------------------
    print("\n--- runs/ に保存済みの学習曲線 ---")
    found = sorted(RUNS.glob("*.json"))
    if not found:
        print("まだありません（学習を回すと TrainResult.save() がここに書き出します）。")
    else:
        for path in found:
            data = json.loads(path.read_text(encoding="utf-8"))
            losses = data.get("losses") or []
            if len(losses) < 15:
                print(f"{path.name:<22} step が少ないので判定しません（{len(losses)} step）")
                continue
            print(render(path.name, summarize(losses)))

    if failures:
        print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
        return 1
    print("\n収束判定の検証はすべて成功しました。")
    return 0


if __name__ == "__main__":
    # 他のスクリプトから summarize() を import できるように、検証は main() に閉じる
    sys.exit(main())
