#!/usr/bin/env python3
"""セッション14の自己検証：本文の主張を機械判定する。

    python src/session14/verify.py

主張が1つでも崩れたら非0で終了する。数値は本文に書いた値そのものである。
副作用（申請・予約・送信・ファイル作成）を出すので、冒頭と末尾で data/ を初期化する。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, str(_p))

from breakdown import kind_totals, step_rows, token_shape  # noqa: E402
from failtags import (all_traces, kind_of, root_step, sampling_rows,  # noqa: E402
                      symptom_ranking, symptoms, verdict)
from redaction import (FULL, FULL_MASKED, HASHED, SUMMARY, args_digest,  # noqa: E402
                       cleanup, grain_rows, mask_values, record_for, run_leak,
                       secret_hits)
from replay import (exception_name, make_cassette, replay_with_fixture,  # noqa: E402
                    replay_with_recorded_ids, same_trajectory, save_cassette)
from spanlog import (UNITS_A, UNITS_B, ancestors, counts_by_kind,  # noqa: E402
                     find_by_call_id, live_tracer_counts, render_tree, reset_data,
                     run_case, spans_from_trajectory, unit_cost_is_stable,
                     wallclock_is_stable)

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.trace import redact  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


reset_data()

# --- ① スパンの階層 ---------------------------------------------------------
traj = run_case("expense_report", "経費レポート作成")
spans = spans_from_trajectory(traj)
c = counts_by_kind(spans)
check("軌跡からスパンの木が作れる（task → step → tool）",
      (len(spans), c["task"], c["step"], c["llm"], c["tool"]) == (12, 1, 4, 4, 3),
      f"スパン数={len(spans)}（task={c['task']} step={c['step']} "
      f"llm={c['llm']} tool={c['tool']}）")
check("行き掛け順に採番され、親が先に来る",
      spans[0].span_id == "TASK-expense_report/00" and spans[0].parent_id is None
      and spans[3].span_id == "TASK-expense_report/03" and spans[3].name == "get_policy",
      f"{spans[0].span_id} → {spans[3].span_id}（{spans[3].name}）")
check("所要は回数×単価で決まる（宣言値・実測ではない）", spans[0].ms == 2060,
      f"合計={spans[0].ms}ms（llm 500×4 + tool 20×3）")
check("木は文字列として描ける", len(render_tree(spans)) == 12,
      f"{len(render_tree(spans))} 行")

# --- ② 相関ID ---------------------------------------------------------------
hits = find_by_call_id(spans, "expense_report-3-0")
check("call_id はトレース全体で一意に引ける",
      len(hits) == 1 and hits[0].name == "write_file"
      and hits[0].span_id == "TASK-expense_report/09",
      f"{len(hits)} 件 → {hits[0].span_id}（{hits[0].name}）")
check("親をたどると1件の中の位置が決まる",
      ancestors(spans, hits[0].span_id)
      == ["TASK-expense_report/09", "TASK-expense_report/07", "TASK-expense_report/00"],
      " → ".join(ancestors(spans, hits[0].span_id)))

# --- ③ agentkit.trace.Tracer との比較 ---------------------------------------
counts = live_tracer_counts()
check("最小実装の Tracer は llm と tool しか持たない", counts == {"llm": 4, "tool": 3},
      f"{counts}（task スパン・親子関係・call_id が無い）")
check("実時間の所要は再現しない", wallclock_is_stable() is False,
      "5回走らせて合計が毎回同じか → いいえ")
check("回数×単価の所要は再現する", unit_cost_is_stable() is True,
      "5回走らせて合計が毎回同じか → はい")

# --- ④ 失敗した1件 ----------------------------------------------------------
bad = run_case("max_steps_loop", "同じ検索を繰り返す", 6)
bad_spans = spans_from_trajectory(bad)
bc = counts_by_kind(bad_spans)
check("失敗した1件も同じ形で記録できる",
      (len(bad.steps), bad.stop_reason, len(bad_spans), bad_spans[0].ms) == (6, "max_steps", 19, 3120),
      f"手数={len(bad.steps)} 停止理由={bad.stop_reason} スパン数={len(bad_spans)}"
      f"（task={bc['task']} step={bc['step']} llm={bc['llm']} tool={bc['tool']}）"
      f" 所要合計={bad_spans[0].ms}ms")

# --- ⑤ 内訳 -----------------------------------------------------------------
rows_a = step_rows(traj, UNITS_A)
check("ステップ単位の内訳が出せる", [r["ms"] for r in rows_a] == [520, 520, 520, 500],
      " / ".join(f"{r['step']}={r['ms']}ms({r['share']:.1f}%)" for r in rows_a))
ta, tb = kind_totals(traj, UNITS_A), kind_totals(traj, UNITS_B)
check("単価表を差し替えると内訳の1位が入れ替わる",
      (ta["llm"], ta["tool"], ta["total"], ta["top"]) == (2000, 60, 2060, "llm")
      and (tb["llm"], tb["tool"], tb["total"], tb["top"]) == (200, 900, 1100, "tool"),
      f"A: llm {ta['llm']}ms({ta['llm_share']:.1f}%) / tool {ta['tool']}ms({ta['tool_share']:.1f}%)"
      f" ・B: llm {tb['llm']}ms({tb['llm_share']:.1f}%) / tool {tb['tool']}ms({tb['tool_share']:.1f}%)")
shape = token_shape(traj)
check("入力トークンはステップごとに増える（近似トークン数・比較用）",
      shape["monotonic"] is True and shape["peak"] == 3,
      f"単調増加={shape['monotonic']} 最大=step[{shape['peak']}]")

# --- ⑥ 記録しないもの -------------------------------------------------------
sample = {"employee_id": "EMP-002", "api_key": "sk-minato-0001",
          "note": "住所は東京都品川区2-2-2"}
masked_key = redact(sample)
check("キー名で落とす層は、値の中の機密を落とせない",
      masked_key["api_key"] == "***" and "東京都品川区2-2-2" in masked_key["note"]
      and "東京都品川区2-2-2" not in mask_values(masked_key)["note"],
      "api_key=*** だが note の住所はそのまま。値を伏せる層（S12）が要る")

grains = grain_rows()
check("粒度を落とすと機密は消えるが、再生もできなくなる",
      [r["secrets"] for r in grains] == [0, 0, 2, 0]
      and grains[2]["replay"].startswith("できる")
      and grains[3]["replay"].startswith("できない"),
      " / ".join(f"{r['grain']}:機密{r['secrets']}件・再生{r['replay']}" for r in grains))
leak_spans = spans_from_trajectory(run_leak())
tool_span = next(s for s in leak_spans if s.kind == "tool")
check("相関IDはどの粒度でも残る",
      all(k in record_for(tool_span, SUMMARY) for k in ("span_id", "parent_id", "call_id"))
      and "args" not in record_for(tool_span, SUMMARY)
      and "args_hash" in record_for(tool_span, HASHED),
      f"要約のみの項目: {list(record_for(tool_span, SUMMARY))}")
check("引数のハッシュは同一判定にだけ使える",
      args_digest({"a": 1}) == args_digest({"a": 1})
      and args_digest({"a": 1}) != args_digest({"a": 2})
      and len(args_digest({"a": 1})) == 16,
      "同じ引数→同じハッシュ / 1文字違い→別のハッシュ / 16桁")
check("全文だけが機密を持ち込む",
      secret_hits([record_for(s, FULL) for s in leak_spans]) == 2
      and secret_hits([record_for(s, FULL_MASKED) for s in leak_spans]) == 0,
      "get_employee の結果と write_file の引数の2か所")
cleanup()

# --- ⑦ 再生 -----------------------------------------------------------------
task, max_steps = "同じ検索を繰り返す", 6
cassette = make_cassette(task, bad, build_registry().specs())
save_cassette("s14_max_steps_loop", cassette)
fixture = replay_with_fixture(task, "s14_max_steps_loop", max_steps=max_steps)
check("FixtureClient は call_id を作り直すので2手目で止まる",
      (len(fixture.steps), fixture.stop_reason, exception_name(fixture)) == (1, "error", "KeyError"),
      f"手数={len(fixture.steps)} 停止理由={fixture.stop_reason} 例外={exception_name(fixture)}")
replayed = replay_with_recorded_ids(task, cassette, max_steps=max_steps)
flags = same_trajectory(bad, replayed)
check("記録した call_id のまま返せば、同じ失敗が再現する",
      all(flags.values()) and len(replayed.steps) == 6 and replayed.stop_reason == "max_steps",
      f"手数={len(replayed.steps)} 停止理由={replayed.stop_reason} 一致={flags}")
changed = replay_with_recorded_ids(task + "。", cassette, max_steps=max_steps)
check("依頼文を1文字変えると再生できない",
      (len(changed.steps), changed.stop_reason) == (0, "error"),
      f"手数={len(changed.steps)} 停止理由={changed.stop_reason} 例外={exception_name(changed)}")

# --- ⑧ 失敗の分類とサンプリング ---------------------------------------------
traces = all_traces()
check("8件の判定が期待どおりに分かれる",
      [verdict(t) for t in traces] == ["正常", "警戒", "正常", "失敗", "失敗", "失敗", "失敗", "失敗"],
      " / ".join(f"{t.task_id.replace('TASK-', '')}:{verdict(t)}" for t in traces))
check("原因のステップを特定できる",
      {t.task_id: root_step(t) for t in traces} == {
          "TASK-expense_report": "—",
          "TASK-book_room_conflict": "step[0]",
          "TASK-submit_expense_approval": "—",
          "TASK-injection_naive": "step[2]",
          "TASK-max_steps_loop": "step[2]",
          "TASK-expense_report-exception": "step[1]",
          "TASK-expense_report-empty": "step[1]",
          "TASK-expense_report-repeat": "step[2]"},
      "打ち切りの原因は最後のステップではなく、反復が始まった step[2]")
check("症状と失敗の種類（S11）は別の軸",
      kind_of(traces[1]) == "恒久的" and kind_of(traces[5]) == "一時的"
      and symptoms(traces[1]) == ["ツール失敗（回復済み）"],
      f"競合={kind_of(traces[1])} / 例外={kind_of(traces[5])}")
ranking = symptom_ranking(traces)
check("症状を頻度順に並べられる",
      (ranking[0]["symptom"], ranking[0]["count"]) == ("同じ操作の反復", 2)
      and len(ranking) == 6,
      " / ".join(f"{r['symptom']}={r['count']}" for r in ranking))
sampling = sampling_rows(traces)
check("一律サンプリングは失敗から先に取りこぼす",
      [(r["kept"], r["kept_failures"], r["lost"]) for r in sampling]
      == [("8/8", "5/5", 0), ("4/8", "2/5", 3), ("7/8", "5/5", 0)],
      " / ".join(f"{r['plan']}:{r['kept']}（失敗 {r['kept_failures']}）" for r in sampling))

# --- 後片付け ---------------------------------------------------------------
cleanup()
reset_data()
run_case("expense_report", "経費レポート作成")   # workspace/report.md を戻す

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション14の検証はすべて成功しました。")
