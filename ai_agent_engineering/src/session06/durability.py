#!/usr/bin/env python3
"""チェックポイントの粒度・二重実行・部分書き込みの実測（すべて決定的）。

    python src/session06/durability.py

各節の前に `tools/make_data.py` を実行してデータを初期状態に戻すので、
何度実行しても同じ数値になる。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.biztools import DATA, build_registry  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.models import Step, Trajectory  # noqa: E402
from agentkit.state import Checkpoint  # noqa: E402
from runner import ResumableRunner, SimulatedCrash  # noqa: E402
from scenarios import RESEARCH  # noqa: E402
from states import TaskState  # noqa: E402

TASK = ("経費精算の規程を確認し、規程に照らして問題のある申請を洗い出して"
        "レポートにまとめ、報告会の会議室を予約してください")
TASK_ID = "TASK-006"
DIR = ROOT / "traces" / "checkpoints" / "session06_dur"


def reset_data() -> None:
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_data.py")],
                   check=True, capture_output=True)


def fresh_dir(directory: Path) -> None:
    """チェックポイントの置き場を空にする（前回の実行を持ち込まない）。"""
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True, exist_ok=True)


def bookings_rows() -> int:
    """実際に予約された件数。副作用はデータ側で数えるしかない。"""
    path = DATA / "bookings.jsonl"
    if not path.exists():
        return 0
    return sum(1 for line in path.open(encoding="utf-8") if line.strip())


def make_runner(**kwargs) -> ResumableRunner:
    return ResumableRunner(ScriptedClient(RESEARCH), build_registry(),
                           task_id=TASK_ID, checkpoint_dir=DIR, **kwargs)


# ---------------------------------------------------------------------------
# ① 落ち方と再開の仕方で、副作用の回数がどう変わるか
# ---------------------------------------------------------------------------
def crash_matrix() -> list[dict]:
    rows: list[dict] = []

    # (1) チェックポイントを使わず、落ちたら最初からやり直す
    reset_data()
    fresh_dir(DIR)
    try:
        make_runner().run(TASK, crash_at=8)
    except SimulatedCrash:
        pass
    again = make_runner()
    again.run(TASK)
    rows.append({"やり方": "最初からやり直す", "落ちた場所": "step 8（保存の後）",
                 "bookings の行数": bookings_rows(),
                 "手数": len(again.trajectory.steps),
                 "停止理由": again.trajectory.stop_reason})

    # (2) チェックポイントから再開する（保存の後に落ちた）
    reset_data()
    fresh_dir(DIR)
    try:
        make_runner().run(TASK, crash_at=8)
    except SimulatedCrash:
        pass
    resumed = make_runner()
    resumed.run(TASK, resume=True)
    rows.append({"やり方": "チェックポイントから再開", "落ちた場所": "step 8（保存の後）",
                 "bookings の行数": bookings_rows(),
                 "手数": len(resumed.trajectory.steps),
                 "停止理由": resumed.trajectory.stop_reason})

    # (3) 実行したが保存する前に落ちた（guard なし）
    reset_data()
    fresh_dir(DIR)
    try:
        make_runner(guard="none").run(TASK, crash_before_save=7)
    except SimulatedCrash:
        pass
    naive = make_runner(guard="none")
    naive.run(TASK, resume=True)
    rows.append({"やり方": "再開（guard なし）", "落ちた場所": "step 7（実行の後・保存の前）",
                 "bookings の行数": bookings_rows(),
                 "手数": len(naive.trajectory.steps),
                 "停止理由": naive.trajectory.stop_reason})

    # (4) 実行の前に意図を保存しておき、再開時に外部の記録と照合する
    reset_data()
    fresh_dir(DIR)
    try:
        make_runner(guard="ahead").run(TASK, crash_before_save=7)
    except SimulatedCrash:
        pass
    safe = make_runner(guard="ahead")
    safe.run(TASK, resume=True)
    rows.append({"やり方": "再開（guard=ahead）", "落ちた場所": "step 7（実行の後・保存の前）",
                 "bookings の行数": bookings_rows(),
                 "手数": len(safe.trajectory.steps),
                 "停止理由": safe.trajectory.stop_reason})

    reset_data()
    return rows


# ---------------------------------------------------------------------------
# ② チェックポイントの粒度
# ---------------------------------------------------------------------------
def granularity_report(crash_at: int = 6) -> list[dict]:
    rows: list[dict] = []
    for granularity in ("step", "subgoal"):
        reset_data()
        fresh_dir(DIR)
        full = make_runner(granularity=granularity)
        full.run(TASK)
        saves_full = full.saves

        reset_data()
        fresh_dir(DIR)
        try:
            make_runner(granularity=granularity).run(TASK, crash_at=crash_at)
        except SimulatedCrash:
            pass
        checkpoint = Checkpoint.load(TASK_ID, DIR)
        saved_steps = len(checkpoint.trajectory.steps)
        rows.append({"粒度": granularity, "完走時の保存回数": saves_full,
                     "保存済みの手数": saved_steps,
                     "やり直す手数": crash_at - saved_steps,
                     "再開する状態": checkpoint.state["state"]})
    reset_data()
    return rows


# ---------------------------------------------------------------------------
# ③ 部分書き込み（保存の途中で落ちる）
# ---------------------------------------------------------------------------
def partial_write_demo() -> dict:
    directory = ROOT / "traces" / "checkpoints" / "session06_partial"
    fresh_dir(directory)
    task_id = "TASK-006P"
    traj = Trajectory(task_id=task_id, task="部分書き込みの実験")
    Checkpoint(task_id, traj, TaskState(task_id=task_id, state="collecting").to_dict()
               ).save(directory)
    before = Checkpoint.load(task_id, directory).state["state"]

    state_path = directory / f"{task_id}.state.json"
    backup = state_path.read_text(encoding="utf-8")
    text = json.dumps(TaskState(task_id=task_id, state="drafting").to_dict(),
                      ensure_ascii=False, indent=2)

    # (1) tmp を使わず本体に直接書いている途中で落ちた（半分だけ書けた）
    state_path.write_text(text[: len(text) // 2], encoding="utf-8")
    try:
        Checkpoint.load(task_id, directory)
        direct = "読めた（想定外）"
    except json.JSONDecodeError:
        direct = "JSONDecodeError"

    # (2) tmp に書いてから rename する方式で、rename の前に落ちた
    state_path.write_text(backup, encoding="utf-8")
    (directory / f"{task_id}.state.tmp").write_text(text[: len(text) // 2],
                                                    encoding="utf-8")
    after = Checkpoint.load(task_id, directory).state["state"]
    return {"落ちる前の状態": before, "直接書き込みで落ちた場合": direct,
            "tmp→rename で落ちた場合": after}


# ---------------------------------------------------------------------------
# ④ 原子的な保存を自分で書く（agentkit は state だけ tmp→rename している）
# ---------------------------------------------------------------------------
def save_checkpoint_atomic(cp: Checkpoint, directory: Path) -> Path:
    """軌跡も tmp→rename で置き換える版。

    残る弱点: rename が2回あるので、その間に落ちると
    「軌跡は新しいが状態は古い」組み合わせが残る。
    完全に揃えたければ `save_checkpoint_single` のように1ファイルにする。
    """
    directory.mkdir(parents=True, exist_ok=True)
    traj_tmp = directory / f"{cp.task_id}.traj.tmp"
    cp.trajectory.to_jsonl(traj_tmp)
    state_tmp = directory / f"{cp.task_id}.state.tmp"
    state_tmp.write_text(json.dumps(cp.state, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    traj_tmp.replace(directory / f"{cp.task_id}.traj.jsonl")
    state_tmp.replace(directory / f"{cp.task_id}.state.json")
    return directory / f"{cp.task_id}.state.json"


def save_checkpoint_single(cp: Checkpoint, directory: Path) -> Path:
    """軌跡と状態を1ファイルにまとめ、rename 1回で切り替える。"""
    directory.mkdir(parents=True, exist_ok=True)
    staging = directory / f"{cp.task_id}.__traj"
    cp.trajectory.to_jsonl(staging)
    payload = {"task_id": cp.task_id, "state": cp.state,
               "trajectory_jsonl": staging.read_text(encoding="utf-8")}
    staging.unlink()
    tmp = directory / f"{cp.task_id}.ckpt.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    target = directory / f"{cp.task_id}.ckpt.json"
    tmp.replace(target)  # 切り替わるのはこの一瞬だけ
    return target


def load_checkpoint_single(task_id: str, directory: Path) -> Checkpoint:
    """1ファイル版を読む。

    `Trajectory.from_jsonl` はパスしか受け取らない（API 契約なので変えない）。
    いったん書き出して読み直すことで、この層だけで吸収する。
    """
    payload = json.loads((directory / f"{task_id}.ckpt.json").read_text(encoding="utf-8"))
    staging = directory / f"{task_id}.__load"
    staging.write_text(payload["trajectory_jsonl"], encoding="utf-8")
    traj = Trajectory.from_jsonl(staging)
    staging.unlink()
    return Checkpoint(task_id=task_id, trajectory=traj, state=payload["state"])


def single_file_crash_demo() -> dict:
    directory = ROOT / "traces" / "checkpoints" / "session06_single"
    fresh_dir(directory)
    task_id = "TASK-006S"
    traj = Trajectory(task_id=task_id, task="1ファイル版の実験")
    traj.steps.append(Step(index=0, thought="1手目",
                           usage={"state": "planning", "event": "plan_ready"}))
    save_checkpoint_single(
        Checkpoint(task_id, traj, TaskState(task_id=task_id, state="collecting").to_dict()),
        directory)
    # 次の保存の途中で落ちた：tmp に半分だけ書かれ、rename されないまま残る
    (directory / f"{task_id}.ckpt.tmp").write_text(
        '{"task_id": "TASK-006S", "state": {"sta', encoding="utf-8")
    cp = load_checkpoint_single(task_id, directory)
    return {"読めた状態": cp.state["state"], "軌跡の手数": len(cp.trajectory.steps),
            "壊れた tmp が残っているか": (directory / f"{task_id}.ckpt.tmp").exists()}


def main() -> None:
    print("--- ① 落ち方と再開の仕方（bookings の行数が副作用の回数） ---")
    for row in crash_matrix():
        print(row)
    print("--- ② チェックポイントの粒度（crash_at=6） ---")
    for row in granularity_report():
        print(row)
    print("--- ③ 部分書き込み ---")
    print(partial_write_demo())
    print("--- ④ 1ファイル版の保存 ---")
    print(single_file_crash_demo())


if __name__ == "__main__":
    main()
