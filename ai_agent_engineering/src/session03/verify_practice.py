#!/usr/bin/env python3
"""セッション3の練習問題の自己検証。

自作ループ（`src/session03/my_agent.py`）が仕様どおりかを機械判定する。
1つでも満たさなければ非0で終了するので、出力を読んで判断する必要はない。

  docker compose exec app python src/session03/verify_practice.py
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.loop import Budget  # noqa: E402
from agentkit.models import Trajectory  # noqa: E402
from my_agent import (  # noqa: E402
    MIXED_CALLS,
    ONE_STEP,
    PARALLEL_READS,
    MyReActAgent,
    choose_on_limit,
    recommend_max_steps,
    render_trace,
    summarize_jsonl,
)

if not (ROOT / "data" / "expenses.jsonl").exists():
    print("data/ が未生成です。先に `python tools/make_data.py` を実行してください。")
    sys.exit(1)

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def raises_value_error(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    return False


def build(scenario, **kwargs) -> MyReActAgent:
    return MyReActAgent(ScriptedClient(scenario), build_registry(), **kwargs)


# --- 停止条件①完了 ---------------------------------------------------------
a = build(ONE_STEP).run("承認は必要ですか", task_id="TASK-a")
check("1ステップで完了する", a.stop_reason == "done" and len(a.steps) == 1,
      f"stop_reason={a.stop_reason} steps={len(a.steps)}")
check("最終回答が入っている", a.final == "1件5万円以上の経費は事前承認が必要です。")
check("ツールを1つも呼んでいない", a.tool_names == [], str(a.tool_names))

# --- 失敗結果を渡してループが続く ------------------------------------------
b = build("book_room_conflict").run("会議室を押さえてください", task_id="TASK-b")
check("3ステップで完了する", b.stop_reason == "done" and len(b.steps) == 3,
      f"stop_reason={b.stop_reason} steps={len(b.steps)}")
check("同じツールを2回呼んで回復している", b.tool_names == ["book_room", "book_room"],
      str(b.tool_names))
b_results = [r for s in b.steps for r in s.results]
check("1手目が失敗している", not b_results[0].ok, (b_results[0].error or "")[:24])
check("失敗の内容が次の行動の手がかりを含む", "別の時間帯" in (b_results[0].error or ""))

# --- 停止条件②上限（失敗として返す）---------------------------------------
c = build("max_steps_loop", max_steps=3).run("規程を調べてください", task_id="TASK-c")
check("上限で止まる", c.stop_reason == "max_steps", f"stop_reason={c.stop_reason}")
check("上限を超えてステップを積まない", len(c.steps) == 3, f"steps={len(c.steps)}")
check("上限到達を成功として返さない", c.final is None)

# --- 上限到達時に部分結果を返す --------------------------------------------
d = build("max_steps_loop", max_steps=3, on_limit="partial").run(
    "規程を調べてください", task_id="TASK-d")
check("部分結果でも停止理由は max_steps のまま", d.stop_reason == "max_steps",
      f"stop_reason={d.stop_reason}")
check("部分結果に未完了である旨が入る", "【未完了】" in (d.final or ""))
check("部分結果にここまでの呼び出しが並ぶ", (d.final or "").count("search_docs") == 3,
      f"{(d.final or '').count('search_docs')} 件")

# --- 上限到達時に人間へ渡す ------------------------------------------------
e = build("max_steps_loop", max_steps=3, on_limit="handoff").run(
    "規程を調べてください", task_id="TASK-e")
check("引き継ぎでも停止理由は max_steps のまま", e.stop_reason == "max_steps",
      f"stop_reason={e.stop_reason}")
check("引き継ぎメモに手数と上限が入る",
      "【要対応】" in (e.final or "") and "手数: 3 / 上限: 3" in (e.final or ""))

# --- 停止条件③予算 ---------------------------------------------------------
f = build("max_steps_loop", max_steps=8, budget=Budget(max_tool_calls=2)).run(
    "規程を調べてください", task_id="TASK-f")
check("予算上限で止まる", f.stop_reason == "budget", f"stop_reason={f.stop_reason}")
check("予算は超過に気づいた時点で止まる", len(f.steps) == 3, f"steps={len(f.steps)}")


# --- 停止条件④エラー -------------------------------------------------------
class BrokenClient:
    """必ず失敗する LLM。停止条件 error を確かめるために使う。"""

    def respond(self, messages, tools):
        raise RuntimeError("接続が切れました")


g = MyReActAgent(BrokenClient(), build_registry()).run("規程を調べてください", task_id="TASK-g")
check("LLM の失敗で error になる", g.stop_reason == "error", f"stop_reason={g.stop_reason}")
check("失敗の理由が最終回答に残る", "RuntimeError" in (g.final or ""))
check("失敗時にステップを捏造しない", len(g.steps) == 0, f"steps={len(g.steps)}")

# --- 決定性 ---------------------------------------------------------------
h1 = build("expense_report").run("経費レポートを作ってください", task_id="TASK-h")
h2 = build("expense_report").run("経費レポートを作ってください", task_id="TASK-h")
check("2回実行して軌跡が一致する",
      h1.tool_names == h2.tool_names and h1.final == h2.final
      and h1.total_tokens == h2.total_tokens)
check("正常系のツールの並びが期待どおり",
      h1.tool_names == ["get_policy", "list_expenses", "write_file"], str(h1.tool_names))

# --- 会話履歴の組み立て ---------------------------------------------------
messages = build(ONE_STEP).build_messages("経費レポートを作ってください", h1)
uses = [c["id"] for m in messages if isinstance(m["content"], list)
        for c in m["content"] if c.get("type") == "tool_use"]
results = [c["tool_use_id"] for m in messages if isinstance(m["content"], list)
           for c in m["content"] if c.get("type") == "tool_result"]
check("tool_use と tool_result の id が対応する", uses == results and len(uses) == 3,
      f"{len(uses)} 組")
check("先頭がタスクの user メッセージ",
      messages[0]["role"] == "user" and messages[0]["content"] == "経費レポートを作ってください")

# --- 並列と直列 -----------------------------------------------------------
p_serial = build(PARALLEL_READS, parallel=False).run("材料を集めて", task_id="TASK-i1")
p_par = build(PARALLEL_READS, parallel=True).run("材料を集めて", task_id="TASK-i2")
check("並列でも軌跡が直列と一致する",
      p_serial.tool_names == p_par.tool_names and p_serial.final == p_par.final)
check("結果の順序が呼び出しの順序と一致する",
      [r.call_id for r in p_par.steps[0].results]
      == [c.call_id for c in p_par.steps[0].calls])
check("並列で呼んだことが軌跡に残る", p_par.steps[0].usage.get("batch") == "parallel",
      str(p_par.steps[0].usage.get("batch")))
mixed = build(MIXED_CALLS, parallel=True).run("下書きを作って", task_id="TASK-j")
check("書き込みが混ざったら直列に落ちる", mixed.steps[0].usage.get("batch") == "serial",
      str(mixed.steps[0].usage.get("batch")))

# --- 軌跡の保存・読み込み・要約 -------------------------------------------
out = ROOT / "traces" / "s03_practice.jsonl"
h1.to_jsonl(out)
summary = summarize_jsonl(out)
check("要約が手数とツールを再現する",
      summary["steps"] == 4
      and summary["tools"] == ["get_policy", "list_expenses", "write_file"],
      str(summary["tools"]))
check("要約が停止理由と完了状態を持つ",
      summary["stop_reason"] == "done" and summary["completed"] is True)
check("要約のトークン量が元の軌跡と一致する",
      summary["input_tokens"] == h1.total_tokens["input"])
loaded = Trajectory.from_jsonl(out)
check("保存・読み込みで思考も残る", all(s.thought for s in loaded.steps))
out.unlink(missing_ok=True)

# --- 軌跡の表示 -----------------------------------------------------------
text = render_trace(b)
check("表示に停止理由と手数が出る", "stop_reason=done 手数=3" in text)
check("表示に失敗したツールとその理由が出る",
      "NG book_room: みなと の 10:00 は既に予約されています。" in text)

# --- 上限の決め方と振る舞いの選び方 ---------------------------------------
check("上限は深さ＋余裕＋報告で決まる", recommend_max_steps(3) == 6,
      f"recommend_max_steps(3)={recommend_max_steps(3)}")
check("深さ0は受け付けない", raises_value_error(lambda: recommend_max_steps(0)))
check("副作用があるものは人間に渡す",
      choose_on_limit(has_side_effect=True, partial_is_useful=True,
                      retry_is_cheap=True) == "handoff")
check("調査系は部分結果を返す",
      choose_on_limit(has_side_effect=False, partial_is_useful=True,
                      retry_is_cheap=True) == "partial")
check("やり直しが安いものは失敗として返す",
      choose_on_limit(has_side_effect=False, partial_is_useful=False,
                      retry_is_cheap=True) == "fail")

# --- 手で組んだ軌跡の往復（問題1）-----------------------------------------
manual = subprocess.run([sys.executable, str(HERE / "ex_trajectory.py")],
                        cwd=ROOT, capture_output=True, text=True)
check("手で組んだ軌跡が往復する", manual.returncode == 0, f"returncode={manual.returncode}")
check("問題1の出力が期待どおり",
      manual.stdout.strip() == "手数=1 ツール=['get_policy'] 停止理由=done",
      manual.stdout.strip())
if manual.returncode != 0:
    print(manual.stderr)

# --- 本文の実行例が本文どおりに動く ---------------------------------------
demo = subprocess.run([sys.executable, str(HERE / "loop_demo.py")],
                      cwd=ROOT, capture_output=True, text=True)
check("loop_demo.py が正常終了する", demo.returncode == 0, f"returncode={demo.returncode}")
EXPECTED_LINES = (
    "=== C 上限に達する — on_limit='fail'（失敗として返す） ===",
    "=== F 読み取り3本を並列で呼ぶ（軌跡は直列と一致する） ===",
    "task_id=TASK-oneshot stop_reason=done 手数=1",
    "NG book_room: みなと の 10:00 は既に予約されています。",
    "task_id=TASK-limit-fail stop_reason=max_steps 手数=3",
    "  final: None",
    "【未完了】3 ステップの上限に達したため中断しました。",
    "- step 0 search_docs: 成功 / [DOC-0001] 経費精算手順書",
    "【要対応】上限に達したため人間に引き継ぎます。",
    "呼んだツール: search_docs, search_docs, search_docs",
    "  step 0: get_policy, list_expenses, search_docs  [parallel]",
    "直列と並列でツールの並びが一致: True",
)
missing = [line for line in EXPECTED_LINES if line not in demo.stdout]
check("本文の出力例と実際の出力が一致する", not missing, f"欠けている行: {len(missing)}")
if missing or demo.returncode != 0:
    for line in missing:
        print(f"    欠け: {line}")
    print(demo.stdout)
    print(demo.stderr)

# --- pytest による軌跡テスト ----------------------------------------------
if importlib.util.find_spec("pytest") is None:
    print("SKIP pytest が入っていないため軌跡テストの実行を飛ばします")
else:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(HERE / "test_my_agent.py"),
         "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True)
    check("pytest による軌跡テストが通る", proc.returncode == 0,
          f"returncode={proc.returncode}")
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション3の演習の検証はすべて成功しました。")
