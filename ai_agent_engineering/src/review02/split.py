#!/usr/bin/env python3
"""復習02：同じタスクを 単体 / オーケストレータ / ハンドオフ で走らせて比べる。

    docker compose exec app python src/review02/split.py

比べるのは4つである。

  手数（＝LLM 呼び出し回数）        … 分けると増える（引き継ぎのための1手が増える）
  1体が持つツールの最大数          … 分けると減る（権限が絞れる）
  最長の履歴（1本の軌跡の手数）    … 分けると短くなる（溢れにくくなる）
  副作用の回数（bookings の行数）  … 渡し方を間違えると 0 になる（成果が出ない）

モデルの応答は `ScriptedClient` で固定してある。つまりここで見るのは
「文脈が落ちたときにモデルがどう振る舞うか」を固定して再現したものであり、
実モデルが毎回こう振る舞うという主張ではない。
"""

from __future__ import annotations

import json

from _paths import setup

ROOT = setup()

from agentkit.biztools import WORKSPACE, build_registry  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.loop import ReActAgent  # noqa: E402
from agentkit.multi import Handoff, Orchestrator  # noqa: E402
from durability import bookings_rows, reset_data  # noqa: E402 (S06)

READ_TOOLS = ["get_policy", "list_expenses", "search_docs"]
WRITE_TOOLS = ["write_file", "book_room"]
SOLO_TOOLS = READ_TOOLS + WRITE_TOOLS

SOLO_TASK = ("経費精算の規程を確認し、規程違反の疑いがある申請を洗い出して"
             "レポートに保存し、報告会の会議室を予約してください")
RESEARCH_TASK = "経費精算の規程を確認し、規程違反の疑いがある申請を洗い出してください"
ARRANGE_TASK = "洗い出しの結果をレポートに保存し、報告会の会議室を予約してください"

# レポート本文。モデルの文章に依存させず、固定の文字列を書かせる（S06 と同じ方針）
REPORT = ("# 四半期の棚卸し（自動生成）\n\n"
          "- 規程違反の疑い: EXP-0002 / EXP-0004\n"
          "- 判定基準: 1件 50,000 円以上は事前承認が必要\n")

# 手配担当が知っていなければならない3項目。引き継ぎで残るかを数える
NEEDED = ("5万円以上は事前承認", "10:00 は予約済み", "EXP-0004")

# 構造化して渡す引き継ぎ情報（キーと値で渡す）
HANDOFF_CONTEXT = {
    "規程": "1件5万円以上は事前承認が必要",
    "埋まっている枠": "みなと の 10:00 は予約済み",
    "違反の疑い": ["EXP-0002", "EXP-0004"],
}

# 調査担当の最終回答（自由文）。これだけを渡すと何が落ちるかを測る
RESEARCHER_FINAL = ("規程を確認し、規程違反の疑いがある申請を洗い出しました。"
                    "EXP-0002 と EXP-0004 が該当します。"
                    "予約は空いている枠でお願いします。")

SOLO = {"name": "review02_solo", "turns": [
    {"thought": "まず経費精算の規程を読む。",
     "calls": [{"name": "get_policy", "args": {"topic": "経費精算"}}]},
    {"thought": "申請一覧と関連文書は互いに独立なのでまとめて取る。",
     "calls": [{"name": "list_expenses", "args": {"status": "all"}},
               {"name": "search_docs", "args": {"query": "経費 規程", "limit": 2}}]},
    {"thought": "洗い出した結果をレポートに保存する。",
     "calls": [{"name": "write_file",
                "args": {"path": "review02/solo_report.md", "content": REPORT}}]},
    {"thought": "10:00 は埋まっていると分かっているので 11:00 で押さえる。",
     "calls": [{"name": "book_room",
                "args": {"room": "みなと", "start": "11:00", "minutes": 60}}]},
    {"thought": "すべて終わった。",
     "final": "EXP-0002 と EXP-0004 をレポートに整理し、みなと 11:00 を予約しました。"},
]}

RESEARCHER = {"name": "review02_researcher", "turns": [
    {"thought": "まず経費精算の規程を読む。",
     "calls": [{"name": "get_policy", "args": {"topic": "経費精算"}}]},
    {"thought": "申請一覧と関連文書をまとめて取る。",
     "calls": [{"name": "list_expenses", "args": {"status": "all"}},
               {"name": "search_docs", "args": {"query": "経費 規程", "limit": 2}}]},
    {"thought": "洗い出しが終わった。手配担当へ渡す。", "final": RESEARCHER_FINAL},
]}

# 構造化された引き継ぎを受け取った手配担当（埋まっている枠を知っている）
ARRANGER_OK = {"name": "review02_arranger_ok", "turns": [
    {"thought": "引き継ぎ情報のとおりレポートを保存する。",
     "calls": [{"name": "write_file",
                "args": {"path": "review02/orch_report.md", "content": REPORT}}]},
    {"thought": "10:00 は埋まっていると聞いているので 11:00 にする。",
     "calls": [{"name": "book_room",
                "args": {"room": "みなと", "start": "11:00", "minutes": 60}}]},
    {"thought": "完了。", "final": "レポートを保存し、みなと 11:00 を予約しました。"},
]}

# 自由文だけを受け取った手配担当（埋まっている枠を知らない）
ARRANGER_BLIND = {"name": "review02_arranger_blind", "turns": [
    {"thought": "申し送りのとおりレポートを保存する。",
     "calls": [{"name": "write_file",
                "args": {"path": "review02/handoff_report.md", "content": REPORT}}]},
    {"thought": "報告会はいつも 10:00 なので、みなとの 10:00 を押さえる。",
     "calls": [{"name": "book_room",
                "args": {"room": "みなと", "start": "10:00", "minutes": 60}}]},
    {"thought": "埋まっていた。大会議室の 13:00 なら空いているだろう。",
     "calls": [{"name": "book_room",
                "args": {"room": "大会議室", "start": "13:00", "minutes": 60}}]},
    {"thought": "空いている枠が分からない。",
     "final": "レポートは保存しましたが、会議室は確保できませんでした。"
              "空いている枠を教えてください。"},
]}


def report_ok(path: str) -> bool:
    """レポートに判断の結論（対象の申請ID）が入っているか。"""
    target = WORKSPACE / path
    if not target.exists():
        return False
    text = target.read_text(encoding="utf-8")
    return all(fact in text for fact in ("EXP-0002", "EXP-0004"))


def _prepare(*paths: str) -> None:
    """前回の実行を持ち込まない（データを戻し、レポートを消す）。"""
    reset_data()
    for path in paths:
        (WORKSPACE / path).unlink(missing_ok=True)


def _row(name: str, trajectories: list, tool_sets: list, report_path: str) -> dict:
    return {
        "構成": name,
        "体の数": len(tool_sets),
        "手数": sum(len(t.steps) for t in trajectories),
        "ツール呼び出し": sum(len(t.tool_names) for t in trajectories),
        "1体のツール最大": max(len(t) for t in tool_sets),
        "履歴の本数": len(trajectories),
        "最長の履歴": max(len(t.steps) for t in trajectories),
        "レポート": report_ok(report_path),
        "予約の行数": bookings_rows(),
    }


def run_solo() -> dict:
    """単体構成。1体が全部のツールを持ち、1本の履歴に全部積む。"""
    path = "review02/solo_report.md"
    _prepare(path)
    registry = build_registry().subset(SOLO_TOOLS)
    agent = ReActAgent(ScriptedClient(SOLO), registry, max_steps=8)
    traj = agent.run(SOLO_TASK, task_id="TASK-R02-S")
    return _row("単体", [traj], [SOLO_TOOLS], path)


def run_orchestrator() -> dict:
    """オーケストレータ構成。親が構造化した引き継ぎを子に配る。"""
    path = "review02/orch_report.md"
    _prepare(path)
    registry = build_registry()
    workers = {
        "researcher": ReActAgent(ScriptedClient(RESEARCHER),
                                 registry.subset(READ_TOOLS), max_steps=6),
        "arranger": ReActAgent(ScriptedClient(ARRANGER_OK),
                               registry.subset(WRITE_TOOLS), max_steps=6),
    }
    orchestrator = Orchestrator(workers)
    plan = [Handoff("researcher", RESEARCH_TASK),
            Handoff("arranger", ARRANGE_TASK, dict(HANDOFF_CONTEXT))]
    trajectories = orchestrator.run_sequence(plan, task_id_prefix="TASK-R02-O")
    return _row("オーケストレータ", trajectories, [READ_TOOLS, WRITE_TOOLS], path)


def run_handoff() -> dict:
    """ハンドオフ構成。前段の最終回答（自由文）だけを次に渡す。"""
    path = "review02/handoff_report.md"
    _prepare(path)
    registry = build_registry()
    researcher = ReActAgent(ScriptedClient(RESEARCHER),
                            registry.subset(READ_TOOLS), max_steps=6)
    arranger = ReActAgent(ScriptedClient(ARRANGER_BLIND),
                          registry.subset(WRITE_TOOLS), max_steps=6)
    first = researcher.run(RESEARCH_TASK, task_id="TASK-R02-H01")
    second = arranger.run(ARRANGE_TASK + "\n\n# 前段からの申し送り\n" + (first.final or ""),
                          task_id="TASK-R02-H02")
    return _row("ハンドオフ", [first, second], [READ_TOOLS, WRITE_TOOLS], path)


def compare() -> list[dict]:
    rows = [run_solo(), run_orchestrator(), run_handoff()]
    reset_data()
    return rows


def handoff_loss() -> dict:
    """引き継ぎで何が落ちるか。渡す文字列の中に必要な項目が残っているかを数える。"""
    structured = json.dumps(HANDOFF_CONTEXT, ensure_ascii=False)
    return {"必要な項目": list(NEEDED),
            "自由文": [k for k in NEEDED if k in RESEARCHER_FINAL],
            "構造化": [k for k in NEEDED if k in structured]}


def mark(flag: bool) -> str:
    return "○" if flag else "×"


def main() -> None:
    print("=== 同じタスクを3つの構成で走らせる ===")
    print("構成 | 体の数 | 手数 | 呼び出し | 1体のツール最大 | 履歴の本数 | "
          "最長の履歴 | レポート | 予約の行数")
    for row in compare():
        print(f"{row['構成']} | {row['体の数']} | {row['手数']} | "
              f"{row['ツール呼び出し']} | {row['1体のツール最大']} | "
              f"{row['履歴の本数']} | {row['最長の履歴']} | "
              f"{mark(row['レポート'])} | {row['予約の行数']}")

    loss = handoff_loss()
    print()
    print(f"=== 引き継ぎで落ちる文脈（{len(loss['必要な項目'])} 項目のうち何が残るか）===")
    print(f"自由文で渡す: {loss['自由文']} → {len(loss['自由文'])}/{len(NEEDED)}")
    print(f"構造化して渡す: {loss['構造化']} → {len(loss['構造化'])}/{len(NEEDED)}")


if __name__ == "__main__":
    main()
