#!/usr/bin/env python3
"""復習04：遅いと言われたときに何を変えるか（問題6）。

    python src/review04/capacity.py

「遅い」への反射は多重度を上げることである。ところが S15 の実測では、多重度を
2 から 4 に上げると完了は 12 秒から 13 秒に**遅くなる**。完了時刻の下限を決めて
いるのは多重度ではなくレート上限だからである（のべ 24 回 ÷ 上限 2 回/秒 ＝ 12 秒）。

だから判断はこの順で行う。

  ① 目標時間が下限より短いか → 短いなら多重度では届かない（上限を上げるか、非同期へ）
  ② 届くなら、目標を満たす**いちばん小さい多重度**を選ぶ（大きいほど待ちが増える）
  ③ そもそも同期で受けるべき仕事かを、型ごとに決めておく

数値は S15 のスケジューラを実際に走らせて取る（1ステップ＝1ティック＝1仮想秒）。
"""

from __future__ import annotations

from _paths import setup

ROOT = setup()

from jobspec import KINDS, total_steps, workload  # noqa: E402
from queue_sim import floor_seconds, multiplicity_rows, run_workload  # noqa: E402

RATE_LIMIT = 2
TARGETS = (30, 15, 12, 10)

# 承認ゲートが要る型。人を待つので同期では受けない（S10）
APPROVAL_KINDS = ("send",)
KIND_ORDER = ("policy", "list", "search", "send", "report", "runaway")


def table() -> list[dict]:
    """多重度ごとの完了・待ち（S15 の実測をその場で取り直す）。"""
    return multiplicity_rows()


def floor() -> int:
    """完了時刻の下限。レート上限が決める。"""
    return floor_seconds(total_steps(workload()), RATE_LIMIT)


def decide(target_seconds: int, rows: list[dict] | None = None) -> dict:
    """目標時間に対する容量の判断を1つ返す。"""
    rows = rows if rows is not None else table()
    low = floor()
    feasible = [r for r in rows if r["makespan"] <= target_seconds]
    if feasible:
        best = min(feasible, key=lambda r: r["workers"])
        return {"目標": target_seconds, "判断": f"多重度を {best['workers']} にする",
                "多重度": best["workers"], "完了": best["makespan"],
                "必要なレート上限": RATE_LIMIT,
                "根拠": f"多重度 {best['workers']} で {best['makespan']} 秒"
                        f"（完了の下限 {low} 秒）"}
    need = -(-total_steps(workload()) // target_seconds)
    return {"目標": target_seconds,
            "判断": "多重度では届かない（レート上限を上げるか、非同期＋通知にする）",
            "多重度": None, "完了": min(r["makespan"] for r in rows),
            "必要なレート上限": need,
            "根拠": f"下限 {low} 秒 > 目標 {target_seconds} 秒。"
                    f"必要なレート上限は {need} 回/秒"}


def mode_for(kind: str) -> str:
    """ジョブの型ごとの受け方。同期／非同期＋通知／バッチ の3択（S15）。"""
    steps = KINDS[kind][2]
    if kind in APPROVAL_KINDS:
        return "非同期＋通知"       # 承認を待つ間、利用者を画面に縛らない
    if steps >= 7:
        return "バッチ"             # 1件が長い。まとめて夜間に回す
    if steps >= 4:
        return "非同期＋通知"
    return "同期"


def mode_rows() -> list[dict]:
    return [{"型": kind, "手数": KINDS[kind][2],
             "承認": "あり" if kind in APPROVAL_KINDS else "なし",
             "受け方": mode_for(kind)}
            for kind in KIND_ORDER]


def slowdown() -> dict:
    """多重度を上げると遅くなる区間を取り出す（2 → 4）。"""
    rows = {r["workers"]: r for r in table()}
    return {"from": 2, "to": 4,
            "makespan": (rows[2]["makespan"], rows[4]["makespan"]),
            "waits": (rows[2]["waits"], rows[4]["waits"])}


def main() -> None:
    rows = table()
    total = total_steps(workload())
    print("=== 多重度を変えたときの完了（S15 の実測・1ステップ＝1仮想秒）===")
    print("多重度 | 完了(仮想秒) | LLM呼び出し | 待った回数 | 待機の合計(秒)")
    for row in rows:
        print(f"{row['workers']} | {row['makespan']} | {row['llm_calls']} | "
              f"{row['waits']} | {row['waited']}")
    print(f"のべ {total} ステップ / レート上限 {RATE_LIMIT} 回/秒 → "
          f"完了の下限 {floor()} 仮想秒")

    print("\n=== 目標時間ごとの判断 ===")
    print("目標(仮想秒) | 判断 | 根拠")
    for target in TARGETS:
        d = decide(target, rows)
        print(f"{d['目標']} | {d['判断']} | {d['根拠']}")

    slow = slowdown()
    print(f"\n多重度 {slow['from']} → {slow['to']}: 完了 {slow['makespan'][0]} → "
          f"{slow['makespan'][1]} 秒（遅くなる）／ 待った回数 {slow['waits'][0]} → "
          f"{slow['waits'][1]} 回")
    print("→ 下限に届いたあとに多重度を上げると、増えるのは待ちだけである。")

    print("\n=== ジョブの型ごとの受け方 ===")
    print("型 | 手数 | 承認 | 受け方")
    for row in mode_rows():
        print(f"{row['型']} | {row['手数']} | {row['承認']} | {row['受け方']}")

    print("\n=== 同じ入力なら毎回同じ処理順になる（判断の再現性）===")
    a, b = run_workload(workers=4), run_workload(workers=4)
    print(f"2回走らせたイベント列の一致: {a.trace() == b.trace()}（{len(a.trace())} 件）")


if __name__ == "__main__":
    main()
