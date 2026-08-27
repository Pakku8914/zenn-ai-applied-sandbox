#!/usr/bin/env python3
"""セッション16の自己検証：本文の主張を機械判定する。

    python src/session16/verify.py

主張が1つでも崩れたら非0で終了する。数値は本文に書いた値そのものである。
副作用（経費の申請・会議室の予約・作業領域のファイル）を出すので、
冒頭と末尾で業務データを初期状態に戻す。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _d in (ROOT, HERE, ROOT / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

from agentkit.eval import task_success, tool_choice_accuracy  # noqa: E402
from agentkit.models import Trajectory  # noqa: E402
from capguard import (admit_rows, behaviour_rows, capped_runaway,  # noqa: E402
                      check_handoff, daily_rows, estimate_next_input,
                      limit_rows, strictness)
from costshape import (cacheable_tokens, cumulative_inputs,  # noqa: E402
                       detail_trajectory, fitted_per_step, messages_for,
                       model_input, prompt_tokens, reset_data, table_rows,
                       unstable_head)
from prices import (HIGH, LOW, SENSITIVITY, crossover_out_rate,  # noqa: E402
                    dominant, io_split, shares, step_costs, traj_cost)
from resultsize import pad_rows, slim_row  # noqa: E402
from tiering import (EXPECTED, degraded_trajectory, precision,  # noqa: E402
                     route_all_high, route_by_role, route_threshold, tiered_cost)

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


reset_data()

# --- ① シナリオ別の表（測定条件：初期化してから4件を順に実行）-------------------
rows = table_rows()
got = [(r["手数"], r["ツール"], r["in"], r["out"], r["停止理由"]) for r in rows]
check("シナリオ別の手数・ツール・トークン・停止理由が実測と一致する",
      got == [(4, 3, 1022, 48, "done"), (3, 2, 436, 35, "done"),
              (3, 2, 449, 34, "done"), (6, 6, 2966, 12, "max_steps")],
      " / ".join(f"{r['シナリオ']}:{r['in']}" for r in rows))

cus = [r["cu"] for r in rows]
check("仮の単価表（上位）で見た1タスクあたり単価が一致する",
      cus == [12620, 6110, 6190, 30260] and sum(cus) == 55180,
      f"{cus} 合計 {sum(cus)} cu")
check("最も高いのは成果ゼロで打ち切られた1件（正常系の 2.40 倍）",
      max(cus) == 30260 and round(30260 / 12620, 2) == 2.40
      and rows[3]["停止理由"] == "max_steps",
      f"手数は {rows[3]['手数'] / rows[0]['手数']:.1f} 倍・入力は "
      f"{rows[3]['in'] / rows[0]['in']:.2f} 倍・コストは "
      f"{rows[3]['cu'] / rows[0]['cu']:.2f} 倍")

# --- ② 詳細モード（経費7件の状態。①の 1,022 と足してはいけない）-----------------
traj = detail_trajectory()
ins = [s.usage["input_tokens"] for s in traj.steps]
outs = [s.usage["output_tokens"] for s in traj.steps]
check("ステップ別の入力トークンが 13 → 129 → 374 → 545 になる",
      ins == [13, 129, 374, 545] and sum(ins) == 1061, f"{ins} 合計 {sum(ins)}")
check("ステップ別の出力トークンが 5 → 4 → 7 → 32 になる",
      outs == [5, 4, 7, 32] and sum(outs) == 48, f"{outs} 合計 {sum(outs)}")
check("入力はステップごとに単調増加する（履歴が毎回全部送られる）",
      all(a < b for a, b in zip(ins, ins[1:]))
      and cumulative_inputs(traj) == [13, 142, 516, 1061],
      f"累計 {cumulative_inputs(traj)}")
check("①の 1,022 と②の 1,061 は測定条件が違う（足したり比べたりしない）",
      rows[0]["in"] == 1022 and sum(ins) == 1061 and rows[0]["in"] != sum(ins),
      "①は経費6件・②は経費7件（submit_expense_approval が1件追加したあと）")

# --- ③ 会話履歴の復元が実測と一致する（以降の計算の土台）------------------------
rebuilt = [prompt_tokens(messages_for(traj, i)) for i in range(len(traj.steps))]
check("軌跡から復元した会話履歴のトークン数が実測と1つも違わない",
      rebuilt == ins, f"復元 {rebuilt}")

# --- ④ コストの式 ---------------------------------------------------------------
per_step = fitted_per_step(traj)
check("入力の累計は n の2次式で近似できる（n·13 + 177·n(n−1)/2）",
      per_step == 177 and model_input(4, 13, 177) == 1114
      and abs(model_input(4, 13, 177) - 1061) / 1061 < 0.06,
      f"予測 {model_input(4, 13, 177)} / 実測 1061（誤差 "
      f"{(model_input(4, 13, 177) - 1061) / 1061 * 100:.1f}%）")
check("手数を2倍にすると入力は約 4.54 倍になる（比例ではない）",
      model_input(8, 13, 177) == 5060
      and round(model_input(8, 13, 177) / model_input(4, 13, 177), 2) == 4.54,
      f"n=4 → {model_input(4, 13, 177)} / n=8 → {model_input(8, 13, 177)}")

# --- ⑤ 内訳と支配要因 -------------------------------------------------------------
costs = step_costs(traj, HIGH)
pcts = [round(p, 1) for p in shares(costs)]
check("ステップ別コストは 380 / 1,490 / 4,090 / 7,050 cu になる",
      costs == [380, 1490, 4090, 7050] and sum(costs) == 13010, f"{costs}")
check("最後のステップだけで全体の 54.2% を占める",
      pcts == [2.9, 11.5, 31.4, 54.2], f"{pcts}")
in_cost, out_cost = io_split(traj, HIGH)
p_in, p_out = (round(p, 1) for p in shares([in_cost, out_cost]))
check("支配しているのは入力（履歴）であって出力ではない",
      (in_cost, out_cost) == (10610, 2400) and (p_in, p_out) == (81.6, 18.4)
      and dominant(traj, HIGH) == "入力",
      f"入力 {in_cost} cu（{p_in}%） / 出力 {out_cost} cu（{p_out}%）")
check("支配要因は単価表を差し替えると入れ替わる（A/B/C）",
      [dominant(traj, t) for t in SENSITIVITY] == ["入力", "入力", "出力"],
      " / ".join(f"{t.label}→{dominant(traj, t)}" for t in SENSITIVITY))
check("出力が支配的になるのは出力単価が 222 cu/トークンを超えてから",
      crossover_out_rate(traj, HIGH) == 222,
      f"入力単価 {HIGH.in_per_token} cu の {222 / HIGH.in_per_token:.1f} 倍")
check("下位モデルで通すと 1/10 になる",
      traj_cost(traj, LOW) == 1301 and traj_cost(traj, HIGH) == 13010,
      f"上位 {traj_cost(traj, HIGH)} cu / 下位 {traj_cost(traj, LOW)} cu")

# --- ⑥ ツール結果は残りのステップ数だけ課金される ---------------------------------
pads = pad_rows()
check("ツール結果を 300 文字太らせると、残りステップ数 × 100 だけ入力が増える",
      [r["増分"] for r in pads[1:]] == [300, 200, 100]
      and [r["理論値"] for r in pads[1:]] == [300, 200, 100],
      " / ".join(f"{r['太らせたツール']}(残り{r['残りステップ']})→+{r['増分']}"
                 for r in pads[1:]))
check("入力の合計は 1,061 → 1,361 / 1,261 / 1,161 になる",
      [r["in"] for r in pads] == [1061, 1361, 1261, 1161],
      f"{[r['in'] for r in pads]}")
check("早いステップの結果ほど高い（同じ 300 文字が 3 : 2 : 1 の重さになる）",
      pads[1]["ステップ別"] == [13, 229, 474, 645]
      and pads[3]["ステップ別"] == [13, 129, 374, 645],
      f"get_policy を太らせた場合 {pads[1]['ステップ別']}")

slim = slim_row()
full_len, slim_len = slim["結果の文字数"]
base_in, slim_in = slim["入力の合計"]
check("ツール結果を実際に短くすると、軌跡を変えずに入力が減る",
      slim_len * 2 < full_len and slim_in < base_in
      and slim["ツール列"][0] == slim["ツール列"][1] and slim["停止理由"][1] == "done",
      f"結果 {full_len} → {slim_len} 文字 / 入力 {base_in} → {slim_in}"
      f"（{base_in - slim_in} 減）")

# --- ⑦ モデル階層 -----------------------------------------------------------------
high = tiered_cost(traj, route_all_high)
tiered = tiered_cost(traj, route_by_role)
threshold = tiered_cost(traj, route_threshold(5_000))
check("整形の1ステップを下位に回すだけで 48.8% 減る",
      (high, tiered) == (13010, 6665)
      and round((high - tiered) / high * 100, 1) == 48.8,
      f"{high} → {tiered} cu")
check("累計 5,000 cu で格下げする動的な振り分けでも同じ額になる",
      threshold == 6665, f"{threshold} cu")
check("階層化しても軌跡は1文字も変わらない（決定的オラクルでの前提）",
      task_success(traj, EXPECTED) and tool_choice_accuracy(traj, EXPECTED) == 1.0
      and precision(traj) == 1.0,
      f"ツール列 {traj.tool_names}")

bad = degraded_trajectory()
check("格下げで挙動が変わると、安くても成功判定に落ちる",
      len(bad.steps) == 5 and task_success(bad, EXPECTED) is False
      and tool_choice_accuracy(bad, EXPECTED) == 1.0 and round(precision(bad), 3) == 0.75,
      f"手数 4 → {len(bad.steps)} / 再現率 1.000 のまま適合率 "
      f"{precision(bad):.3f} / 余計に呼んだのは "
      f"{[n for n in bad.tool_names if n not in EXPECTED.tools]}")

# --- ⑧ 前方一致キャッシュ -----------------------------------------------------------
stable = cacheable_tokens(traj)
broken = cacheable_tokens(traj, unstable_head)
cached_cost = traj_cost(traj, HIGH, cached_in=stable)
check("前方一致で再利用できる入力は 516（新しく払うのは最後のステップと同じ 545）",
      stable == 516 and sum(ins) - stable == 545 == ins[-1],
      f"再利用 {stable} / 新規 {sum(ins) - stable}")
check("先頭に毎回変わる時刻を1行入れるだけで、再利用できる量が 0 になる",
      broken == 0, f"{broken} トークン")
check("キャッシュが効くとコストは 13,010 → 8,366 cu（35.7% 減）",
      cached_cost == 8366 and round((13010 - cached_cost) / 13010 * 100, 1) == 35.7,
      f"入力だけで見ると 10,610 → 5,966 cu（43.8% 減）")

# --- ⑨ 上限：事後判定と見積もり判定 ---------------------------------------------------
lrows = limit_rows()
partial = Trajectory(task_id="TASK-est", task=traj.task, steps=traj.steps[:3])
check("見積もりの式が 13 → 129 → 374 のあと 554 を返す",
      estimate_next_input(partial) == 554 and estimate_next_input(traj) == 722,
      "3手ぶん見たあとの見積もりは 374 + 180 = 554（実際の4手目は 545）")
check("事後判定は上限 520 を 1,061（204.0%）まで超える",
      [(r["事後"]["手数"], r["事後"]["in"], r["事後"]["停止理由"]) for r in lrows]
      == [(3, 516, "budget"), (4, 1061, "done"), (4, 1061, "done"), (4, 1061, "done")],
      "最後の1ステップが最も重いので、直前で通過すると倍払う")
check("見積もり判定なら上限 520 / 1,000 を守れる",
      [(r["見積"]["手数"], r["見積"]["in"], r["見積"]["停止理由"]) for r in lrows]
      == [(3, 516, "budget"), (3, 516, "budget"), (3, 516, "budget"), (4, 1061, "done")],
      "守れた上限: 事後=[1200] / 見積=[520, 1000, 1200]")
check("1ステップが上限を超える設定は、どちらの判定でも守れない",
      lrows[0]["事後"]["in"] == 516 and lrows[0]["見積"]["in"] == 516,
      "上限 400 に対して 516（129.0%）。上限はステップ単価より大きく取る")

s = strictness()
check("Budget は `>`（超えたら止める）。S11 の RunLimits の `>=` と混ぜない",
      s["上限＝合計（Budget の `>`）"] is False and s["上限＝合計−1"] is True,
      f"合計 {s['合計']} と同じ上限では止まらない")

# --- ⑩ 超過時の振る舞い -----------------------------------------------------------
brows = behaviour_rows()
check("上限 10,000 cu で打ち切ると 3手 5,960 cu（report.md は保存済み・報告だけ無い）",
      (brows[0]["手数"], brows[0]["cu"], brows[0]["停止理由"]) == (3, 5960, "budget")
      and "report.md" in brows[0]["成果"],
      f"{brows[0]['cu']} cu / {brows[0]['停止理由']} / 成果: {brows[0]['成果']}")
check("格下げなら 4手 6,665 cu で報告まで完了する（上限内で最も成果が大きい）",
      (brows[1]["手数"], brows[1]["cu"], brows[1]["停止理由"]) == (4, 6665, "done")
      and brows[1]["cu"] <= 10000,
      f"{brows[1]['cu']} cu / {brows[1]['停止理由']}")
check("人に渡すときは引き継ぎ書の5項目がそろう",
      check_handoff(brows[2]["note"]) == []
      and "write_file" in brows[2]["note"] and "最終回答" in brows[2]["note"],
      "済んだ操作に write_file・残っている操作に最終回答（副作用は出ている）")

# --- ⑪ 3層の上限 -------------------------------------------------------------------
costs4 = [(r["シナリオ"], r["cu"]) for r in rows]
plain = daily_rows(costs4)
capped = daily_rows(costs4, per_task_limit=15_000)
check("1タスク上限が無いと1日の上限 50,000 cu を 110.4% まで超える",
      [r["累計"] for r in plain] == [12620, 18730, 24920, 55180]
      and plain[-1]["超過"] is True
      and round(55180 / 50000 * 100, 1) == 110.4,
      f"累計 {[r['累計'] for r in plain]}")
check("1タスク上限 15,000 cu を置くと1日の合計は高々 39,920 cu に収まる",
      [r["累計"] for r in capped] == [12620, 18730, 24920, 39920]
      and all(r["超過"] is False for r in capped),
      f"累計 {[r['累計'] for r in capped]}")
order_a = admit_rows(costs4, 50_000)
order_b = admit_rows(list(reversed(costs4)), 50_000)
check("1タスク上限が無いと、拒否されるタスクが到着順で決まる",
      [r["タスク"] for r in order_a if r["判定"] == "拒否"] == ["同じ検索を繰り返す"]
      and [r["タスク"] for r in order_b if r["判定"] == "拒否"] == ["経費レポート作成"],
      "暴走した1件が先に来ると、正常なタスクが締め出される")
check("1タスク上限を置けば、どちらの到着順でも拒否は出ない",
      all(r["判定"] != "拒否" for r in admit_rows(costs4, 50_000, 15_000))
      and all(r["判定"] != "拒否"
              for r in admit_rows(list(reversed(costs4)), 50_000, 15_000)),
      "1タスク上限は「1件の暴走が他を締め出す」ことを防ぐ層")

cap = capped_runaway()
check("暴走した1件は1タスク上限で実際に抑えられる",
      cap["上限なし"]["cu"] == 30260 and cap["上限あり"]["cu"] <= 15000
      and cap["上限あり"]["手数"] < cap["上限なし"]["手数"]
      and cap["上限あり"]["停止理由"] == "budget",
      f"{cap['上限なし']['手数']}手 {cap['上限なし']['cu']} cu → "
      f"{cap['上限あり']['手数']}手 {cap['上限あり']['cu']} cu")

reset_data()

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション16の検証はすべて成功しました。")
