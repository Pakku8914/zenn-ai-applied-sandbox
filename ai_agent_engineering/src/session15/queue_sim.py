#!/usr/bin/env python3
"""セッション15：キューとワーカー（決定的な協調スケジューラ）。

    python src/session15/queue_sim.py

本物のスレッドで並行実行すると、走らせるたびに処理順が変わり、軌跡が再現しない。
運用の練習としても教材としても、**同じ入力なら毎回同じ処理順になる**ことが要る。
そこで本章は時間をティックに刻み、次の規則だけで並行を表す。

  ① 1ステップ（LLM 呼び出し1回）＝1ティック＝1仮想秒
  ② 各ティックで、空いているワーカーが番号順にジョブを取る
  ③ レート上限に達したら、順番待ちの行列（到着順）に並ぶ
  ④ 待機は実時間では待たない（セッション11の `RecordingSleeper` に記録する）

ここに出る秒数は**モデル上の仮想秒**であり、実 API のレイテンシではない。
モデルであっても「多重度を上げても速くならない点がある」ことは正しく出る。
"""

from __future__ import annotations

import shutil
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
S11 = ROOT / "src" / "session11"
for _p in (str(ROOT), str(S11), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.loop import ReActAgent  # noqa: E402
from agentkit.models import Trajectory  # noqa: E402
from agentkit.state import Checkpoint  # noqa: E402
from backoff import RecordingSleeper  # noqa: E402  （セッション11）
from guards import RunLimits, handoff_report, render_limit_final  # noqa: E402
from jobspec import (Job, build_job_tools, crash_jobs, isolation_jobs,  # noqa: E402
                     strategy_jobs, total_steps, workload)
from ratelimit import RateLimit, backoff_ticks  # noqa: E402

CHECKPOINT_DIR = ROOT / "traces" / "checkpoints" / "session15"
STATE_ORDER = ("done", "cancelled", "limited", "failed", "running", "queued")


# ---------------------------------------------------------------------------
@dataclass
class JobRun:
    """1件のジョブの実行記録。キューが持つのはこれ（ジョブそのものではない）。"""

    job: Job
    trajectory: Trajectory
    state: str = "queued"
    attempts: int = 0
    requeues: int = 0
    available_at: int = 0        # 再配達の待ち（この時刻までは取り出せない）
    started_at: int | None = None
    first_step_at: int | None = None
    finished_at: int | None = None
    waited: int = 0
    tools: object = None

    @property
    def steps_done(self) -> int:
        return len(self.trajectory.steps)

    @property
    def wait_to_first_step(self) -> int:
        """受け付けてから最初の一歩までの待ち。行列の公平さはここに出る。"""
        if self.started_at is None or self.first_step_at is None:
            return 0
        return self.first_step_at - self.started_at


@dataclass
class Worker:
    index: int
    free_at: int = 0
    run: JobRun | None = None
    attempt: int = 0             # 当たってから謝る方式の連続失敗回数


@dataclass
class Result:
    mode: str
    workers: int
    makespan: int = 0
    llm_calls: int = 0
    waits: int = 0               # 待った回数
    waited_seconds: int = 0
    wasted_calls: int = 0        # 上限に当たって捨てた呼び出し
    redone_steps: int = 0        # やり直したステップ
    tool_counts: Counter = field(default_factory=Counter)
    runs: list[JobRun] = field(default_factory=list)
    events: list[tuple] = field(default_factory=list)

    def by_id(self, job_id: str) -> JobRun:
        for run in self.runs:
            if run.job.job_id == job_id:
                return run
        raise KeyError(f"未知のジョブです: {job_id}")

    def states(self) -> str:
        counts = Counter(run.state for run in self.runs)
        return " / ".join(f"{s} {counts[s]}" for s in STATE_ORDER if counts[s])

    def completed(self) -> int:
        return sum(1 for run in self.runs if run.state == "done")

    def trace(self) -> list[tuple]:
        """処理順の指紋。2回走らせて一致すれば決定的である。"""
        return [(t, w, jid, kind) for t, w, jid, kind, _ in self.events]

    def max_wait_to_first_step(self) -> int:
        return max((run.wait_to_first_step for run in self.runs), default=0)


# ---------------------------------------------------------------------------
class Scheduler:
    """キュー・ワーカー・レート制限・キャンセル・再配達を1つに束ねた実行器。

    rate_mode … "queue"（手前で順番待ち）/ "backoff"（当たってから謝る）
    cancel    … {job_id: 何秒の時点でキャンセル要求が届くか}
    crash     … {job_id: 何秒の時点でワーカーが落ちるか}
    resume    … 落ちたあとチェックポイントから再開するか
    """

    def __init__(self, jobs: list[Job], *, workers: int = 2, limit: int = 2,
                 rate_mode: str = "queue", fair: bool = True,
                 max_steps_per_job: int = 8, redelivery: int = 1,
                 cancel: dict[str, int] | None = None,
                 crash: dict[str, int] | None = None, resume: bool = True,
                 checkpoint_dir: Path | None = None, max_ticks: int = 400) -> None:
        if rate_mode not in ("queue", "backoff"):
            raise ValueError(f"rate_mode は queue か backoff です: {rate_mode!r}")
        self.runs = [JobRun(job, Trajectory(task_id=job.job_id, task=job.task))
                     for job in jobs]
        self.pending: list[JobRun] = list(self.runs)
        self.workers = [Worker(i) for i in range(workers)]
        self.rate = RateLimit(limit=limit, fair=fair)
        self.rate_mode = rate_mode
        self.limits = RunLimits(max_steps=max_steps_per_job)
        self.redelivery = redelivery
        self.cancel = dict(cancel or {})
        self.crash = dict(crash or {})
        self.resume = resume
        self.checkpoint_dir = checkpoint_dir
        self.sleeper = RecordingSleeper()
        self.max_ticks = max_ticks
        self.result = Result(mode=rate_mode, workers=workers, runs=self.runs)

    # -- 走行 ---------------------------------------------------------------
    def run(self) -> Result:
        t = 0
        while self.pending or any(w.run is not None for w in self.workers):
            if t >= self.max_ticks:
                raise RuntimeError(f"{self.max_ticks} ティックで終わりませんでした。")
            self._control(t)                       # ①キャンセル・打ち切り・クラッシュ
            self._assign(t)                        # ②空きワーカーにジョブを渡す
            if self.rate_mode == "queue":
                self._execute_queue(t)             # ③順番待ちの行列から許可を出す
            else:
                self._execute_backoff(t)           # ③'当たってから謝る
            t += 1
        self.result.makespan = max((r.finished_at or 0) for r in self.runs)
        self.result.waited_seconds = int(self.sleeper.total)
        self.result.wasted_calls = self.rate.rejected_total
        self.result.redone_steps = (self.result.llm_calls
                                    - sum(r.steps_done for r in self.runs))
        return self.result

    # -- ①止める理由がないかを、行動の前に見る -----------------------------
    def _control(self, t: int) -> None:
        for w in self.workers:
            run = w.run
            if run is None:
                continue
            jid = run.job.job_id
            if jid in self.cancel and t >= self.cancel[jid]:
                del self.cancel[jid]
                self._finish_cancel(t, w, run)
                continue
            hit = self.limits.reached(run.trajectory,
                                      elapsed=t - (run.started_at or t))
            if hit:
                self._finish_limit(t, w, run, hit)
                continue
            if jid in self.crash and t >= self.crash[jid]:
                del self.crash[jid]
                self._requeue(t, w, run)

    def _finish_cancel(self, t: int, w: Worker, run: JobRun) -> None:
        """止める。止めたあとに人が何を受け取るかまでがキャンセルである。"""
        run.trajectory.stop_reason = "error"       # `done` にはしない（未完了である）
        run.trajectory.final = handoff_report(
            run.trajectory, run.tools,
            reason=f"利用者がキャンセルしました（{t} 秒時点・{run.steps_done} ステップ実行済み）")
        self._close(t, w, run, "cancelled", f"{run.steps_done} ステップで停止")

    def _finish_limit(self, t: int, w: Worker, run: JobRun, hit: str) -> None:
        """上限に達したジョブだけを落とす。キュー全体は止めない。"""
        run.trajectory.stop_reason = "max_steps" if hit == "max_steps" else "budget"
        run.trajectory.final = render_limit_final("handoff", hit, run.trajectory,
                                                  self.limits, run.tools)
        self._close(t, w, run, "limited", f"上限に到達（{self.limits.text(hit)}）")

    def _close(self, t: int, w: Worker, run: JobRun, state: str, detail: str,
               *, finished_at: int | None = None) -> None:
        run.state = state
        run.finished_at = t if finished_at is None else finished_at
        self.rate.leave(w.index)
        self._event(t, w.index, run, state, detail)
        w.run = None

    def _requeue(self, t: int, w: Worker, run: JobRun) -> None:
        """ワーカーが落ちた。ジョブはキューに戻る（メモリ上の続きは失われる）。"""
        run.state = "queued"
        run.requeues += 1
        run.available_at = t + self.redelivery
        if self.resume and self.checkpoint_dir is not None \
                and Checkpoint.exists(run.job.job_id, self.checkpoint_dir):
            run.trajectory = Checkpoint.load(run.job.job_id, self.checkpoint_dir).trajectory
            detail = f"チェックポイントから {run.steps_done} ステップを復元"
        else:
            run.trajectory = Trajectory(task_id=run.job.job_id, task=run.job.task)
            detail = "続きが無いので最初からやり直す"
        self.rate.leave(w.index)
        self._event(t, w.index, run, "requeued", detail)
        w.run = None
        self.pending.insert(0, run)

    # -- ②割り当て ---------------------------------------------------------
    def _assign(self, t: int) -> None:
        for w in self.workers:
            if w.free_at > t:
                continue
            if w.run is None:
                run = self._pull(t)
                if run is None:
                    continue
                run.state = "running"
                run.attempts += 1
                if run.started_at is None:
                    run.started_at = t
                run.tools = build_job_tools(run.job.job_id)
                w.run = run
                self._event(t, w.index, run,
                            "resumed" if run.requeues else "started",
                            f"{run.job.kind} / 手数 {run.job.steps}")
            if self.rate_mode == "queue":
                self.rate.join(t, w.index)

    def _pull(self, t: int) -> JobRun | None:
        """取り出せる先頭の1件を返す。再配達待ちのものは飛ばす（見えていない）。"""
        for i, run in enumerate(self.pending):
            if run.available_at <= t:
                return self.pending.pop(i)
        return None

    # -- ③実行（順番待ち）---------------------------------------------------
    def _execute_queue(self, t: int) -> None:
        for index in self.rate.serve(t):
            w = self.workers[index]
            self._step(t, w)
        for index in list(self.rate.line):          # 許可が出なかったワーカー
            w = self.workers[index]
            if w.free_at > t or w.run is None:
                continue
            wait = self.rate.wait_to_next_window(t)
            self._wait(t, w, wait, "順番待ち")

    # -- ③'実行（当たってから謝る）------------------------------------------
    def _execute_backoff(self, t: int) -> None:
        for w in self.workers:
            if w.free_at > t or w.run is None:
                continue
            if self.rate.take(t):
                w.attempt = 0
                self._step(t, w)
            else:
                w.attempt += 1
                self._wait(t, w, backoff_ticks(w.attempt - 1),
                           f"上限に当たった（{w.attempt} 回目）")

    def _wait(self, t: int, w: Worker, wait: int, why: str) -> None:
        w.free_at = t + wait
        self.sleeper.sleep(wait)                    # 実時間では待たない
        self.result.waits += 1
        if w.run is not None:
            w.run.waited += wait
        self._event(t, w.index, w.run, "waited", f"{wait} 秒待つ（{why}）")

    # -- 1ステップ進める -----------------------------------------------------
    def _step(self, t: int, w: Worker) -> None:
        run = w.run
        assert run is not None
        traj = run.trajectory
        client = ScriptedClient(run.job.scenario)
        client.cursor = len(traj.steps)             # セッション6と同じ「位置合わせ」
        agent = ReActAgent(client, run.tools, max_steps=len(traj.steps) + 1)
        run.trajectory = agent.run(run.job.task, task_id=run.job.job_id, resume=traj)
        self.result.llm_calls += 1
        if run.first_step_at is None:
            run.first_step_at = t
        w.free_at = t + 1

        last = run.trajectory.steps[-1]
        for call in last.calls:
            self.result.tool_counts[call.name] += 1
        action = last.calls[0].name if last.calls else "（最終回答）"
        self._event(t, w.index, run, "step", f"{run.steps_done} 手目 {action}")

        if self.checkpoint_dir is not None:
            Checkpoint(task_id=run.job.job_id, trajectory=run.trajectory,
                       state={"steps": run.steps_done, "attempts": run.attempts},
                       ).save(self.checkpoint_dir)

        if run.trajectory.stop_reason == "done":
            self._close(t, w, run, "done", f"{run.steps_done} ステップで完了",
                        finished_at=t + 1)
        elif run.trajectory.stop_reason == "error":
            self._close(t, w, run, "failed", "LLM 呼び出しに失敗", finished_at=t + 1)

    def _event(self, t: int, worker: int, run: JobRun | None, kind: str,
               detail: str) -> None:
        self.result.events.append(
            (t, worker, run.job.job_id if run else "-", kind, detail))


# ---------------------------------------------------------------------------
# 走らせ方（本文の表はここから出る）
# ---------------------------------------------------------------------------
def run_workload(*, workers: int = 2, limit: int = 2, fair: bool = True,
                 cancel: dict[str, int] | None = None) -> Result:
    return Scheduler(workload(), workers=workers, limit=limit, fair=fair,
                     cancel=cancel).run()


def multiplicity_rows(counts: tuple[int, ...] = (1, 2, 4, 8)) -> list[dict]:
    rows = []
    for n in counts:
        r = run_workload(workers=n)
        rows.append({"workers": n, "makespan": r.makespan, "llm_calls": r.llm_calls,
                     "waits": r.waits, "waited": r.waited_seconds,
                     "done": r.completed()})
    return rows


def floor_seconds(total_calls: int, limit: int) -> int:
    """レート上限が決める完了時刻の下限。多重度をいくら上げてもこれより速くならない。"""
    return -(-total_calls // limit)


def knee(rows: list[dict], floor: int) -> int:
    """下限に最初に届いた多重度（＝それ以上増やしても速くならない点）。"""
    for row in rows:
        if row["makespan"] <= floor:
            return row["workers"]
    return rows[-1]["workers"]


def run_strategy(mode: str) -> Result:
    """上限に当たったときの2つの作法を、同じワークロードで比べる。"""
    return Scheduler(strategy_jobs(), workers=4, limit=2, rate_mode=mode).run()


def strategy_rows() -> list[dict]:
    rows = []
    for label, mode in (("当たってから謝る（バックオフ）", "backoff"),
                        ("手前で順番待ち（行列）", "queue")):
        r = run_strategy(mode)
        rows.append({"label": label, "makespan": r.makespan, "calls": r.llm_calls,
                     "wasted": r.wasted_calls, "waits": r.waits,
                     "waited": r.waited_seconds})
    return rows


def run_crash(resume: bool) -> Result:
    """ワーカーが3秒の時点で落ちる。チェックポイントの有無で何が変わるか。"""
    if CHECKPOINT_DIR.exists():
        shutil.rmtree(CHECKPOINT_DIR)
    return Scheduler(crash_jobs(), workers=1, crash={"TASK-161": 3}, resume=resume,
                     checkpoint_dir=CHECKPOINT_DIR).run()


def run_isolation(max_steps_per_job: int = 4) -> Result:
    """止まらないジョブを1件混ぜる。打ち切られるのはその1件だけである。"""
    return Scheduler(isolation_jobs(), workers=2,
                     max_steps_per_job=max_steps_per_job).run()


def progress_at(result: Result, job_id: str, t: int) -> dict:
    """利用者に見せる進捗。**％は出さない**（総ステップ数が分からないため）。"""
    view = {"job_id": job_id, "state": "queued", "steps_done": 0,
            "last_action": "—", "waited_seconds": 0, "started_at": None}
    for et, _w, jid, kind, detail in result.events:
        if jid != job_id or et > t:
            continue
        if kind in ("started", "resumed"):
            view["state"] = "running"
            view["started_at"] = et
        elif kind == "step":
            view["state"] = "running"
            view["steps_done"] += 1
            view["last_action"] = detail.rsplit(" ", 1)[-1]
        elif kind == "waited":
            view["state"] = "waiting"
            view["waited_seconds"] += int(detail.split(" ", 1)[0])
        elif kind == "requeued":
            view["state"] = "queued"
        else:
            view["state"] = kind
    return view


def render_events(result: Result, limit: int = 12) -> str:
    lines = ["時刻 | ワーカー | ジョブ | 種類 | 内容"]
    for t, w, jid, kind, detail in result.events[:limit]:
        lines.append(f"{t} | w{w} | {jid} | {kind} | {detail}")
    if len(result.events) > limit:
        lines.append(f"…（全 {len(result.events)} 件）")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
def main() -> None:
    jobs = workload()
    total = total_steps(jobs)
    floor = floor_seconds(total, 2)

    print("=== 多重度を変えて同じ8件を流す ===")
    print(f"ワークロード {len(jobs)} 件 / のべ {total} ステップ / "
          f"レート上限 2 回/秒 / 1ステップ＝1仮想秒")
    print("多重度 | 完了(仮想秒) | LLM呼び出し | 待った回数 | 待機の合計(秒) | 完了件数")
    rows = multiplicity_rows()
    for row in rows:
        print(f"{row['workers']} | {row['makespan']} | {row['llm_calls']} | "
              f"{row['waits']} | {row['waited']} | {row['done']}")
    print(f"\n完了時刻の下限 = のべ {total} 回 ÷ 上限 2 回/秒 = {floor} 秒")
    print(f"多重度 {knee(rows, floor)} で下限に届く。"
          "そこから先は完了が速くならず、待ちだけが増える。")

    print("\n=== 同じ入力なら毎回同じ処理順になる ===")
    a, b = run_workload(workers=4), run_workload(workers=4)
    print(f"2回走らせたイベント列の一致: {a.trace() == b.trace()}（{len(a.trace())} 件）")
    print(render_events(a, limit=6))

    print("\n=== レート上限に当たったときの2つの作法（4件×3ステップ / ワーカー4）===")
    print("戦略 | 完了(仮想秒) | 通った呼び出し | 上限に当たった回数 | 待った回数 | 待機の合計(秒)")
    for row in strategy_rows():
        print(f"{row['label']} | {row['makespan']} | {row['calls']} | "
              f"{row['wasted']} | {row['waits']} | {row['waited']}")

    print("\n=== 長時間タスクを途中で止める（キャンセル）===")
    base = run_workload(workers=2)
    cut = run_workload(workers=2, cancel={"TASK-157": 9})
    print(f"キャンセルなし | 完了 {base.makespan} 秒 | LLM {base.llm_calls} 回 | {base.states()}")
    print(f"9秒でキャンセル | 完了 {cut.makespan} 秒 | LLM {cut.llm_calls} 回 | {cut.states()}")
    stopped = cut.by_id("TASK-157")
    print(f"止めたジョブ: {stopped.steps_done} ステップ / "
          f"stop_reason={stopped.trajectory.stop_reason}")
    print(stopped.trajectory.final)

    print("\n=== 進捗の見せ方（％を出さない）===")
    print(progress_at(base, "TASK-153", 4))

    print("\n=== 1件が止まらなくても、キュー全体は止めない ===")
    iso = run_isolation()
    print(f"完了 {iso.makespan} 秒 | LLM {iso.llm_calls} 回 | {iso.states()}")
    runaway = iso.by_id("TASK-172")
    print(f"打ち切ったジョブ: {runaway.steps_done} ステップ / "
          f"stop_reason={runaway.trajectory.stop_reason}")

    print("\n=== ワーカーが落ちたとき（再配達と再開）===")
    print("落ちたあとの方針 | 完了(仮想秒) | LLM呼び出し | やり直したステップ | write_file の実行回数")
    for label, resume in (("チェックポイントから再開", True), ("最初からやり直す", False)):
        r = run_crash(resume)
        print(f"{label} | {r.makespan} | {r.llm_calls} | {r.redone_steps} | "
              f"{r.tool_counts['write_file']}")
    shutil.rmtree(CHECKPOINT_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
