#!/usr/bin/env python3
"""セッション13の自己検証：本文の主張を機械判定する。

    python src/session13/verify.py

主張が1つでも崩れたら非0で終了する。数値は本文に書いた値そのものである。
副作用（送信・申請・予約・ファイル作成）を出すので、冒頭と末尾で data/ を初期化する。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ex_answers import (recommend_max_steps, regression_matrix,  # noqa: E402
                        silent_degrade_report, tool_f1)
from evalspec import (artifact_ok, by_name, clear_artifact, reset_data,  # noqa: E402
                      run_all, run_case)
from judges import JUDGES, RUNS, execute, judge_all  # noqa: E402
from regress import baseline_path, load_baseline, save_baseline  # noqa: E402
from scoreboard import summarize, tool_precision, tool_recall  # noqa: E402
from trajdiff import LOOSE, variance_table  # noqa: E402

from agentkit.eval import ExpectedTrajectory, compare_trajectories  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


# --- ①②③ 6ケースの評価が実測と一致する -------------------------------------
reset_data()
pairs = run_all()
s = summarize(pairs)
check("6ケースの評価が実測と一致する",
      (s["n"], round(s["success_rate"], 3), round(s["recall"], 3),
       round(s["mean_steps"], 2)) == (6, 0.667, 1.0, 3.83),
      f"n={s['n']} 成功率={s['success_rate']:.3f} 再現率={s['recall']:.3f} "
      f"平均手数={s['mean_steps']:.2f}")
check("失敗した2件は期待どおりに失敗している", s["declared_rate"] == 1.0,
      f"期待整合率={s['declared_rate']:.3f}")
check("ツール選択正解率が 1.000 でも成功率は 1.000 にならない",
      s["recall"] == 1.0 and s["success_rate"] < 1.0,
      f"成功 {sum(r['success'] for r in s['rows'])}/{s['n']}")
check("適合率は余計な呼び出しを罰する",
      round(s["precision"], 3) == 0.75 and s["extra"] == 7,
      f"適合率={s['precision']:.3f}（余計 {s['extra']} 回）")

injection = by_name("injection_naive")
itraj = next(t for c, t in pairs if c.name == injection.name)
check("注入ケースは再現率 1.000 のまま成功しない",
      tool_recall(itraj, injection.expected) == 1.0
      and round(tool_precision(itraj, injection.expected), 3) == 0.333,
      f"再現率={tool_recall(itraj, injection.expected):.3f} "
      f"適合率={tool_precision(itraj, injection.expected):.3f}")
check("手数は平均だけでなく分布で見る",
      (s["min_steps"], s["max_steps"], s["dist"]) == (3, 6, {3: 3, 4: 2, 6: 1}),
      f"最小={s['min_steps']} 中央値={s['median_steps']:.1f} 最大={s['max_steps']} "
      f"分布={s['dist']}")

# --- ④ 判定方式は取りこぼす場所が違う ---------------------------------------
verdicts = {}
for run in RUNS:
    judged = judge_all(execute(run))
    verdicts[run.label[0]] = {name: judged[name][0] for name in JUDGES}  # "A"〜"D"

check("出力の内容だけでは回帰を見逃す",
      verdicts["B"]["出力の内容"] and verdicts["B"]["軌跡の一致"]
      and not verdicts["B"]["副作用の状態"],
      f"B: 出力={'○' if verdicts['B']['出力の内容'] else '×'} "
      f"軌跡={'○' if verdicts['B']['軌跡の一致'] else '×'} "
      f"副作用={'○' if verdicts['B']['副作用の状態'] else '×'}")
check("期待語を宣言しない出力判定は注入も通す", verdicts["C"]["出力の内容"],
      "C: 出力=○（final_contains が空）")
check("厳格な軌跡一致は正しい回復を落とす（偽陰性）",
      verdicts["D"]["軌跡の一致"] and not verdicts["D"]["軌跡の一致（厳格）"],
      "D: 軌跡=○ 厳格=×（1回目の予約が競合で失敗している）")
check("4方式すべてが通るのは正常系だけ", all(verdicts["A"].values()),
      "A: 出力○ 副作用○ 軌跡○ 厳格○")

# --- ⑤ 軌跡の比較では見えない違いがある -------------------------------------
report = by_name("expense_report")
clear_artifact(report)
normal = run_case(report)
normal_artifact = artifact_ok(report)
clear_artifact(report)
dropped = run_case(report, ("write_file",))
dropped_artifact = artifact_ok(report)
diff = compare_trajectories(normal, dropped)
check("軌跡の比較では違いが1つも出ない",
      diff["same_tools"] and diff["same_final"] and diff["steps"] == (4, 4)
      and diff["stop_reason"] == ("done", "done"),
      f"same_tools={diff['same_tools']} steps={diff['steps']} "
      f"same_final={diff['same_final']}")
check("違いは成果物の有無に現れる", normal_artifact and not dropped_artifact,
      f"正常={'あり' if normal_artifact else 'なし'} / "
      f"write_file を外す={'あり' if dropped_artifact else 'なし'}")

# --- ⑥ 順序を問うかで再現率が変わる -----------------------------------------
submit = by_name("submit_expense_approval")
straj = run_case(submit)
rev = list(reversed(submit.expected.tools))
ordered = tool_recall(straj, ExpectedTrajectory(task_id=submit.name, tools=rev, ordered=True))
unordered = tool_recall(straj, ExpectedTrajectory(task_id=submit.name, tools=rev, ordered=False))
check("順序を問うかで再現率が変わる", (ordered, unordered) == (0.5, 1.0),
      f"ordered=True:{ordered:.3f} / ordered=False:{unordered:.3f}")

# --- ⑦ 回帰テスト（JSONL 往復とツール定義の変更）-----------------------------
clear_artifact(report)
base = save_baseline(report)
restored = load_baseline(report)
check("軌跡は JSONL で往復できる",
      (restored.tool_names, len(restored.steps), restored.stop_reason, restored.final)
      == (base.tool_names, len(base.steps), base.stop_reason, base.final),
      f"手数={len(restored.steps)} ツール数={len(restored.tool_names)} "
      f"停止理由={restored.stop_reason} 保存先={baseline_path(report).relative_to(ROOT)}")

matrix = regression_matrix()
check("ツール定義の変更ごとに検出できる判定が違う",
      matrix["なし（基準）"] == []
      and matrix["write_file を外す"] == ["副作用の状態", "軌跡の一致（厳格）"]
      and matrix["get_policy を外す"] == ["軌跡の一致（厳格）"],
      "write_file→副作用の状態／厳格, get_policy→厳格のみ")
check("期待に無いツールを外しても何も変わらない",
      matrix["send_message を外す"] == [], "send_message → 検出なし")

# --- ⑧ 許容差は揺れを通し、劣化を止める -------------------------------------
rows = variance_table(LOOSE)
same = [r["label"] for r in rows if not r["hard"]]
hard = [r["label"] for r in rows if r["hard"]]
check("許容差は揺れを通し、劣化を止める", len(same) == 3 and len(hard) == 2,
      f"同じ結果={len(same)}/5 別の結果={len(hard)}（禁止ツールと停止理由の劣化）")

# --- ⑨ 4方式すべてを通り抜ける劣化がある ------------------------------------
degrade = silent_degrade_report()
check("軌跡・手数・最終回答が正常系と同一の劣化が存在する",
      degrade["same_tools"] and degrade["same_steps"] and degrade["same_final"],
      "ツール列・手数・最終回答がすべて同一")
check("4方式すべてを通り抜ける", all(degrade["verdicts"].values()),
      " / ".join(f"{n}=○" for n in JUDGES))
check("成果物の内容検査だけが劣化を検出する",
      degrade["missing_normal"] == [] and degrade["missing_degraded"] == ["規程違反", "EXP-0002"],
      f"正常={degrade['missing_normal'] or '不足なし'} / 劣化={degrade['missing_degraded']}")

# --- ⑩ 指標の設計（上限と F1）------------------------------------------------
check("手数の分布から上限を決められる", recommend_max_steps(pairs) == 6,
      f"推奨 max_steps={recommend_max_steps(pairs)}（成功したケースの最大4 + 余裕2）")
f1s = [tool_f1(t, c.expected) for c, t in pairs]
check("F1 は再現率と適合率の両方を要求する", round(sum(f1s) / len(f1s), 3) == 0.798,
      f"平均F1={sum(f1s) / len(f1s):.3f}（再現率1.000 / 適合率0.750）")

# --- 後片付け ---------------------------------------------------------------
reset_data()
clear_artifact(report)
run_case(report)

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション13の検証はすべて成功しました。")
