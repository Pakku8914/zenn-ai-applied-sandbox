#!/usr/bin/env python3
"""復習02：圧縮した保存物から再開できるか（S06 × S07 の合わせ技）。

    docker compose exec app python src/review02/resume.py

S06 の `ResumableRunner` をそのまま使い、**保存の仕方だけ**を4通りに変えて再開する。
圧縮は「送るものを減らす」話だと思われがちだが、同じ手つきで**保存するもの**も
減らせる。減らしたものによって、再開できるかどうかと、再開したあとに何ができるかが
変わる。ここを取り違えると、落ちたあとに続けられないエージェントになる。

データは各再開の前に `tools/make_data.py` で初期状態へ戻すので、何度実行しても
同じ数値になる。
"""

from __future__ import annotations

from _paths import setup

ROOT = setup()

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.models import Trajectory  # noqa: E402
from agentkit.state import Checkpoint  # noqa: E402
from durability import bookings_rows, fresh_dir, reset_data  # noqa: E402 (S06)
from runner import ResumableRunner, SimulatedCrash  # noqa: E402 (S06)
from scenarios import RESEARCH  # noqa: E402 (S06)

TASK = ("経費精算の規程を確認し、規程に照らして問題のある申請を洗い出して"
        "レポートにまとめ、報告会の会議室を予約してください")
TASK_ID = "TASK-R02"
DIR = ROOT / "traces" / "checkpoints" / "review02"

CRASH_AT = 5    # 5手ぶん進んだところで落とす（レポートを書き終えた直後）
KEEP_STEPS = 2  # 「軌跡を圧縮」で残す末尾の手数

VARIANTS = (
    ("軌跡だけ残す", {"drop_state": True}),
    ("軌跡を圧縮＋状態は全部", {"steps": KEEP_STEPS}),
    ("全部残す", {}),
    ("状態から本文を捨てる", {"drop_materials": True}),
)


def _runner(**kwargs) -> ResumableRunner:
    return ResumableRunner(ScriptedClient(RESEARCH), build_registry(),
                           task_id=TASK_ID, checkpoint_dir=DIR, **kwargs)


def crash_once() -> Checkpoint:
    """5手ぶん進めて落とし、そのときのチェックポイントを読み出す。"""
    reset_data()
    fresh_dir(DIR)
    try:
        _runner().run(TASK, crash_at=CRASH_AT)
    except SimulatedCrash:
        pass
    return Checkpoint.load(TASK_ID, DIR)


def write_variant(checkpoint: Checkpoint, *, steps: int | None = None,
                  drop_state: bool = False, drop_materials: bool = False) -> None:
    """保存の仕方を変えて置き直す（元のチェックポイントは書き換えない）。"""
    fresh_dir(DIR)
    traj = checkpoint.trajectory
    if steps is None:
        saved_traj = traj
    else:
        saved_traj = Trajectory(task_id=traj.task_id, task=traj.task,
                                steps=list(traj.steps[-steps:]), final=traj.final,
                                stop_reason=traj.stop_reason)
    state = {} if drop_state else dict(checkpoint.state)
    if drop_materials:
        # 本文（get_policy と list_expenses の中身）を落とす。鍵ごと消える
        state.pop("materials", None)
    Checkpoint(task_id=TASK_ID, trajectory=saved_traj, state=state).save(DIR)


def resume_once() -> dict:
    """保存物から再開する。再開できなければ理由を返す。"""
    reset_data()
    runner = _runner()
    try:
        traj = runner.run(TASK, resume=True)
    except TypeError as exc:
        # 状態が無いと TaskState を作れない＝どこから続けるか決められない
        return {"再開できる": False, "到達した手数": None, "違反": None,
                "予約の行数": bookings_rows(), "停止理由": f"{type(exc).__name__}"}
    return {"再開できる": True, "到達した手数": len(traj.steps),
            "違反": len(runner.state.violations), "予約の行数": bookings_rows(),
            "停止理由": traj.stop_reason}


def variants() -> list[dict]:
    """4通りの保存の仕方を、同じ落ち方から比べる。"""
    checkpoint = crash_once()
    rows: list[dict] = []
    for name, kwargs in VARIANTS:
        write_variant(checkpoint, **kwargs)
        saved = Checkpoint.load(TASK_ID, DIR)  # 保存物を読み直して形を測る
        row = {
            "方式": name,
            "保存した手数": len(saved.trajectory.steps),
            "状態の鍵": len(saved.state),
            "基準を変えて再計算できる":
                bool(saved.state.get("materials", {}).get("list_expenses")),
        }
        row.update(resume_once())
        rows.append(row)
    reset_data()
    return rows


def crash_point() -> dict:
    """落ちた時点で保存されていたもの（4通りに共通する出発点）。"""
    checkpoint = crash_once()
    reset_data()
    return {"保存された手数": len(checkpoint.trajectory.steps),
            "状態": checkpoint.state["state"],
            "違反": len(checkpoint.state["violations"]),
            "予約の行数": bookings_rows()}


def mark(flag: bool) -> str:
    return "○" if flag else "×"


def cell(value) -> str:
    return "-" if value is None else str(value)


def main() -> None:
    point = crash_point()
    print(f"=== {CRASH_AT} 手まで進んだところで落ちた（step {CRASH_AT} の直前）===")
    print(f"保存された手数: {point['保存された手数']} / 状態: {point['状態']} / "
          f"違反: {point['違反']} 件 / 予約の行数: {point['予約の行数']}")

    print()
    print("=== 保存の仕方を変えて再開する ===")
    print("方式 | 保存した手数 | 状態の鍵 | 再開できる | 到達した手数 | 違反 | "
          "予約の行数 | 基準を変えて再計算")
    for row in variants():
        print(f"{row['方式']} | {row['保存した手数']} | {row['状態の鍵']} | "
              f"{mark(row['再開できる'])} | {cell(row['到達した手数'])} | "
              f"{cell(row['違反'])} | {row['予約の行数']} | "
              f"{mark(row['基準を変えて再計算できる'])}")


if __name__ == "__main__":
    main()
