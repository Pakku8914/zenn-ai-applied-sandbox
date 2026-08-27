#!/usr/bin/env python3
"""セッション15の自己検証：本文の主張を機械判定する。

    python src/session15/verify.py

主張が1つでも崩れたら非0で終了する。数値は本文に書いた値そのものである。
副作用（社外宛メッセージ・作業領域のファイル）を出すので、冒頭と末尾で
`tools/make_data.py` 相当の初期化と作業領域の削除を行う。
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from jobspec import (clear_workspace, crash_jobs, jsonl_count,  # noqa: E402
                     reset_data, total_steps, workload)
from opsconfig import OpsConfig  # noqa: E402
from queue_sim import (Scheduler, floor_seconds, knee, multiplicity_rows,  # noqa: E402
                       progress_at, run_crash, run_isolation, run_workload,
                       strategy_rows)
from ratelimit import backoff_ticks, serve_demo  # noqa: E402
from rollout import (POPULATION, canary_ids, check_runbook, kind_of,  # noqa: E402
                     measure, render_runbook, run_rollout)
from swap import accept_swap, swap_rows  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


reset_data()
clear_workspace()

# --- ① 多重度と、レート上限が決める下限 --------------------------------------
rows = multiplicity_rows()
got = [(r["workers"], r["makespan"], r["waits"], r["waited"]) for r in rows]
check("多重度ごとの完了時刻と待ちが実測と一致する",
      got == [(1, 24, 0, 0), (2, 12, 0, 0), (4, 13, 19, 19), (8, 12, 52, 52)],
      " / ".join(f"w{w}:{m}秒 待ち{n}回" for w, m, n, _ in got))
calls = sorted({r["llm_calls"] for r in rows})
done = sorted({r["done"] for r in rows})
check("多重度を変えても仕事の量は変わらない",
      calls == [24] and done == [8],
      f"LLM 呼び出し={calls} 完了件数={done}")

floor = floor_seconds(total_steps(workload()), 2)
check("完了時刻の下限は多重度ではなくレート上限が決める",
      floor == 12 and knee(rows, floor) == 2 and min(r["makespan"] for r in rows) == 12,
      f"下限={floor} 秒 / 頭打ちの多重度={knee(rows, floor)}")
check("下限に届いたあとは待ちだけが増える",
      rows[1]["waited"] == 0 and rows[3]["waited"] == 52,
      f"多重度2の待機={rows[1]['waited']} 秒 / 多重度8の待機={rows[3]['waited']} 秒")

# --- ② 決定性 ---------------------------------------------------------------
a, b = run_workload(workers=4), run_workload(workers=4)
check("同じ入力なら毎回同じ処理順になる",
      a.trace() == b.trace() and len(a.trace()) == 59,
      f"イベント {len(a.trace())} 件が完全一致")

# --- ③ レート上限に当たったときの2つの作法 -----------------------------------
srows = {r["label"]: r for r in strategy_rows()}
back = srows["当たってから謝る（バックオフ）"]
wait = srows["手前で順番待ち（行列）"]
check("当たってから謝ると呼び出しが無駄になる",
      (back["makespan"], back["calls"], back["wasted"]) == (7, 12, 6),
      f"完了 {back['makespan']} 秒 / 無駄 {back['wasted']} 回")
check("手前で順番待ちすると無駄が出ない",
      (wait["makespan"], wait["calls"], wait["wasted"]) == (6, 12, 0),
      f"完了 {wait['makespan']} 秒 / 無駄 {wait['wasted']} 回")
check("待機の合計が短い方が速いとは限らない",
      back["waited"] < wait["waited"] and back["makespan"] > wait["makespan"],
      f"待機 {back['waited']} 秒 → 完了 {back['makespan']} 秒 ／ "
      f"待機 {wait['waited']} 秒 → 完了 {wait['makespan']} 秒")
check("バックオフの待機は1秒刻みに切り上げても指数で伸びる",
      [backoff_ticks(i) for i in range(6)] == [1, 1, 2, 4, 8, 8],
      f"{[backoff_ticks(i) for i in range(6)]}")

# --- ④ 行列の公平さ ----------------------------------------------------------
check("不公平な行列では後ろのワーカーが1回も通らない",
      serve_demo(True) == [3, 3, 3, 3] and serve_demo(False) == [6, 6, 0, 0],
      f"公平={serve_demo(True)} 不公平={serve_demo(False)}")
fair = run_workload(workers=4, fair=True)
unfair = run_workload(workers=4, fair=False)
check("公平な行列は完了を1秒遅らせる代わりに、最初の一歩の待ちを9秒→1秒にする",
      (fair.makespan, fair.max_wait_to_first_step()) == (13, 1)
      and (unfair.makespan, unfair.max_wait_to_first_step()) == (12, 9),
      f"公平 完了{fair.makespan}秒/最大待ち{fair.max_wait_to_first_step()}秒 ／ "
      f"不公平 完了{unfair.makespan}秒/最大待ち{unfair.max_wait_to_first_step()}秒")

# --- ⑤ キャンセル ------------------------------------------------------------
base = run_workload(workers=2)
cut = run_workload(workers=2, cancel={"TASK-157": 9})
stopped = cut.by_id("TASK-157")
check("キャンセルすると残りの呼び出しを払わずに済む",
      (base.llm_calls, cut.llm_calls) == (24, 21) and cut.makespan == 12,
      f"LLM 呼び出し {base.llm_calls} → {cut.llm_calls} 回")
check("止めたジョブは完了扱いにしない",
      stopped.state == "cancelled" and stopped.trajectory.stop_reason == "error"
      and stopped.steps_done == 1,
      f"状態={stopped.state} stop_reason={stopped.trajectory.stop_reason} "
      f"{stopped.steps_done} ステップ")
check("止めた時点の引き継ぎ書が出る",
      "利用者がキャンセルしました" in (stopped.trajectory.final or "")
      and "副作用は出ていません" in (stopped.trajectory.final or ""),
      "頼まれたこと／止まった理由／済んだ操作／不明な操作／次にやること")
check("キャンセルしても他のジョブは完走する",
      cut.states() == "done 7 / cancelled 1", cut.states())

# --- ⑥ 進捗の見せ方 ----------------------------------------------------------
view = progress_at(base, "TASK-153", 4)
check("進捗は％ではなく「いま何をしているか」で見せる",
      view == {"job_id": "TASK-153", "state": "running", "steps_done": 3,
               "last_action": "write_file", "waited_seconds": 0, "started_at": 2},
      str(view))

# --- ⑦ 1件の暴走が全体を止めない ---------------------------------------------
iso = run_isolation()
runaway = iso.by_id("TASK-172")
check("上限に達したジョブだけが落ち、キューは動き続ける",
      iso.states() == "done 2 / limited 1" and iso.llm_calls == 9
      and iso.makespan == 5,
      f"{iso.states()} / LLM {iso.llm_calls} 回 / 完了 {iso.makespan} 秒")
check("打ち切ったジョブは上限ちょうどで止まる",
      runaway.steps_done == 4 and runaway.trajectory.stop_reason == "max_steps"
      and "人に引き継ぎます" in (runaway.trajectory.final or ""),
      f"{runaway.steps_done} ステップ / {runaway.trajectory.stop_reason}")

# --- ⑧ ワーカーが落ちたとき ---------------------------------------------------
resumed = run_crash(True)
restart = run_crash(False)
check("チェックポイントから再開するとやり直しが0になる",
      (resumed.makespan, resumed.llm_calls, resumed.redone_steps) == (6, 6, 0),
      f"完了 {resumed.makespan} 秒 / LLM {resumed.llm_calls} 回 / "
      f"やり直し {resumed.redone_steps} ステップ")
check("最初からやり直すと副作用も2回実行される",
      (restart.makespan, restart.llm_calls, restart.redone_steps) == (9, 9, 3)
      and restart.tool_counts["write_file"] == 2
      and resumed.tool_counts["write_file"] == 1,
      f"write_file 実行回数 再開={resumed.tool_counts['write_file']} "
      f"やり直し={restart.tool_counts['write_file']}")
clean = Scheduler(crash_jobs()[:1], workers=1).run().by_id("TASK-161").trajectory
crashed = resumed.by_id("TASK-161").trajectory
check("再開した軌跡は落ちなかった場合と1文字も違わない",
      crashed.tool_names == clean.tool_names and crashed.final == clean.final
      and len(crashed.steps) == len(clean.steps),
      f"ツール列={crashed.tool_names} 手数={len(crashed.steps)}")

# --- ⑨ モデル差し替えの軌跡差分 ------------------------------------------------
before_messages = jsonl_count("messages")
swap = {row["label"]: row for row in swap_rows()}
check("同じ挙動の新構成は差分が1つも出ない",
      swap["A 同じ挙動"]["same_tools"] and swap["A 同じ挙動"]["same_final"]
      and swap["A 同じ挙動"]["missing"] == [],
      "ツール列・手数・最終回答・成果物のすべてが一致")
check("手数の増減と禁止ツールは軌跡の差分で見つかる",
      swap["B 余計に調べる"]["only_in_b"] == ["search_docs"]
      and swap["B 余計に調べる"]["steps"] == (4, 5)
      and swap["C 禁止ツールを呼ぶ"]["only_in_b"] == ["send_message"],
      f"B={swap['B 余計に調べる']['only_in_b']} C={swap['C 禁止ツールを呼ぶ']['only_in_b']}")
check("軌跡の差分がゼロでも成果物が劣化していることがある",
      swap["D 中身が薄くなる"]["same_tools"] and swap["D 中身が薄くなる"]["same_final"]
      and swap["D 中身が薄くなる"]["steps"] == (4, 4)
      and swap["D 中身が薄くなる"]["missing"] == ["規程違反", "EXP-0002"],
      f"D の不足語={swap['D 中身が薄くなる']['missing']}")
check("差し替えの判断は4通りに分かれる",
      [accept_swap(swap[k]) for k in ("A 同じ挙動", "B 余計に調べる",
                                      "C 禁止ツールを呼ぶ", "D 中身が薄くなる")]
      == ["出す", "様子を見る", "出さない", "出さない"],
      "A=出す B=様子を見る C=出さない D=出さない")
check("C の送信は実際に外へ出ている", jsonl_count("messages") - before_messages == 1,
      f"messages.jsonl が {jsonl_count('messages') - before_messages} 行増えた")

# --- ⑩ 段階リリース ------------------------------------------------------------
reset_data()
cfg = OpsConfig.load()
kinds = Counter(kind_of(tid) for tid in POPULATION)
check("母集団の型の内訳が実測と一致する",
      (kinds["policy"], kinds["list"], kinds["report"], kinds["send"]) == (33, 31, 32, 4),
      f"policy {kinds['policy']} / list {kinds['list']} / report {kinds['report']} / "
      f"send {kinds['send']}")

head = run_rollout(cfg, "head")
strat = run_rollout(cfg.with_(canary_percents=(5,)), "stratified")
check("先頭から 5% のカナリアは欠陥に当たらない",
      (head[0]["n"], head[0]["new"].success, head[0]["new"].forbidden,
       head[0]["verdict"]) == (5, 5, 0, "進む"),
      f"{head[0]['n']} 件 / 成功 {head[0]['new'].success} / "
      f"禁止 {head[0]['new'].forbidden} / {head[0]['verdict']}")
check("25% まで広げて初めて欠陥に当たる",
      (head[1]["n"], head[1]["new"].success, head[1]["new"].forbidden,
       head[1]["verdict"]) == (25, 24, 1, "止める") and len(head) == 2,
      f"{head[1]['n']} 件 / 成功 {head[1]['new'].success} / "
      f"禁止 {head[1]['new'].forbidden} / {head[1]['verdict']}（ここで打ち切り）")
check("型ごとに選べば同じ 5% で欠陥に当たる",
      (strat[0]["n"], strat[0]["new"].success, strat[0]["new"].forbidden,
       strat[0]["verdict"]) == (5, 4, 1, "止める"),
      f"{strat[0]['n']} 件 / 成功 {strat[0]['new'].success} / "
      f"禁止 {strat[0]['new'].forbidden} / {strat[0]['verdict']}")
check("対照（旧構成）は同じタスクで基準を満たしている",
      all(r["base"].forbidden == 0 and r["base"].success == r["n"]
          for r in head + strat),
      "旧構成はどの段階でも禁止ツール 0 件")

for method in ("serial", "hash"):
    small, large = canary_ids(5, "head", method), canary_ids(25, "head", method)
    check(f"振り分けは安定していて単調に広がる（{method}）",
          set(small) <= set(large) and canary_ids(5, "head", method) == small,
          f"{len(small)} 件 ⊂ {len(large)} 件")

after = measure(POPULATION, "old")
check("ロールバックすれば全件が基準を満たす",
      (after.n, after.success, after.forbidden, after.steps) == (100, 100, 0, 299),
      f"{after.n} 件 / 成功 {after.success} / 禁止 {after.forbidden} / 手数 {after.steps}")

ok_runbook, missing = check_runbook(render_runbook())
check("runbook に必要な節がそろっている", ok_runbook, f"不足: {missing or 'なし'}")

# --- ⑪ 設定の外部化 ------------------------------------------------------------
check("設定はファイルから読める",
      (cfg.workers, cfg.rate_limit_per_second, cfg.canary_percents)
      == (2, 2, (5, 25, 100)),
      f"workers={cfg.workers} rate={cfg.rate_limit_per_second} "
      f"percents={cfg.canary_percents}")
rejected = 0
for change in ({"workers": 0}, {"rate_mode": "yolo"}, {"canary_percents": (25, 5)},
               {"min_success_rate": 1.5}):
    try:
        cfg.with_(**change)
    except ValueError:
        rejected += 1
check("おかしな設定は起動時に落ちる", rejected == 4, f"{rejected}/4 件を拒否")
check("設定を変えると多重度が変わる",
      run_workload(workers=cfg.with_(workers=4).workers).makespan == 13,
      "workers=4 の完了は 13 秒")

# --- 後片付け -----------------------------------------------------------------
import shutil  # noqa: E402

from queue_sim import CHECKPOINT_DIR  # noqa: E402

reset_data()
clear_workspace()
shutil.rmtree(CHECKPOINT_DIR, ignore_errors=True)

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション15の検証はすべて成功しました。")
