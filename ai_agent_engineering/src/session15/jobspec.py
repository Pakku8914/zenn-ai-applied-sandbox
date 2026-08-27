#!/usr/bin/env python3
"""セッション15：ジョブの定義（並行実行の題材）。

    python src/session15/jobspec.py

章の中でしか使わないシナリオはコードの近くに置く（セッション6・8・11と同じ方針）。
本章で要るのは「**手数の違うジョブが混ざった現実的なワークロード**」である。
すべて決定的なので、何度流しても同じ軌跡・同じ手数になる。

作業領域はジョブごとに分ける。並行実行では、同じ `workspace/report.md` に
複数のワーカーが書くと最後の1つだけが残る。**分けるのはモデルではなく実装の責任**
であり、ツールの側で閉じ込める（セッション12の最小権限と同じ考え方）。
"""

from __future__ import annotations

import contextlib
import io
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.biztools import DATA, WORKSPACE, build_registry, read_file, write_file  # noqa: E402
from agentkit.tools import Tool, ToolRegistry  # noqa: E402

# レポートの本文。セッション13と同じく「中身の検査」で使うので語を固定する
REPORT_BODY = ("# 2026年8月 経費レポート\n"
               "- 申請 6 件 / 合計 285,400 円\n"
               "- 5万円以上: 3 件（事前承認の対象）\n"
               "- 規程違反の注記: EXP-0002 / EXP-0004 / EXP-0005\n")

# --- 型ごとのタスクとシナリオ（turns の数＝手数）-----------------------------
POLICY_TASK = "経費精算で事前承認が必要になる金額を教えてください"
POLICY_TURNS = {"name": "s15_policy", "turns": [
    {"thought": "規程を引く。",
     "calls": [{"name": "get_policy", "args": {"topic": "経費精算"}}]},
    {"thought": "条文に金額が書いてあった。",
     "final": "1件5万円以上の経費は事前承認が必要です。"},
]}

LIST_TASK = "未処理の経費申請を一覧にしてください"
LIST_TURNS = {"name": "s15_list", "turns": [
    {"thought": "先に規程を確認する。",
     "calls": [{"name": "get_policy", "args": {"topic": "経費精算"}}]},
    {"thought": "未処理の申請を取る。",
     "calls": [{"name": "list_expenses", "args": {"status": "submitted"}}]},
    {"thought": "一覧にできた。",
     "final": "未処理の経費申請を一覧にまとめました。"},
]}

REPORT_TASK = "2026年8月の経費レポートを作成してください"
REPORT_TURNS = {"name": "s15_report", "turns": [
    {"thought": "規程を確認する。",
     "calls": [{"name": "get_policy", "args": {"topic": "経費精算"}}]},
    {"thought": "申請の一覧を取る。",
     "calls": [{"name": "list_expenses", "args": {"status": "all"}}]},
    {"thought": "レポートを作業領域に保存する。",
     "calls": [{"name": "write_file",
                "args": {"path": "report.md", "content": REPORT_BODY}}]},
    {"thought": "保存できた。",
     "final": "report.md にレポートを保存しました。"},
]}

SEARCH_TASK = "経費精算の手順書を調べて要点を教えてください"
SEARCH_TURNS = {"name": "s15_search", "turns": [
    {"thought": "手順書を検索する。",
     "calls": [{"name": "search_docs", "args": {"query": "経費精算", "limit": 1}}]},
    {"thought": "規程の条文でも裏を取る。",
     "calls": [{"name": "get_policy", "args": {"topic": "経費精算"}}]},
    {"thought": "要点をまとめる。",
     "final": "支出日から10日以内の申請と、5万円以上の事前承認が要点です。"},
]}

# 社外連絡。旧構成は下書きを保存するだけ、新構成は送信してしまう（段階リリースの題材）
SEND_TASK = "取引先への月次連絡文を用意してください"
SEND_OLD_TURNS = {"name": "s15_send_old", "turns": [
    {"thought": "社外連絡の規程を確認する。",
     "calls": [{"name": "get_policy", "args": {"topic": "社外連絡"}}]},
    {"thought": "下書きを保存して所属長の確認に回す。",
     "calls": [{"name": "write_file",
                "args": {"path": "draft.md",
                         "content": "# 月次のご連絡\n平素より格別のご高配を賜り厚く御礼申し上げます。\n"}}]},
    {"thought": "下書きができた。",
     "final": "下書きを用意しました。所属長の確認をお願いします。"},
]}
SEND_NEW_TURNS = {"name": "s15_send_new", "turns": [
    {"thought": "社外連絡の規程を確認する。",
     "calls": [{"name": "get_policy", "args": {"topic": "社外連絡"}}]},
    {"thought": "そのまま送ってしまう（承認を経ていない）。",
     "calls": [{"name": "send_message",
                "args": {"to": "external@example.com",
                         "body": "平素より格別のご高配を賜り厚く御礼申し上げます。"}}]},
    {"thought": "送った。",
     "final": "下書きを用意しました。所属長の確認をお願いします。"},
]}

# 止まらないジョブ（打ち切りの題材）。同じ検索を延々と繰り返す
RUNAWAY_TASK = "経費精算について分かるまで調べ続けてください"
_LOOP = {"name": "search_docs", "args": {"query": "経費精算", "limit": 1}}
RUNAWAY_TURNS = {"name": "s15_runaway",
                 "turns": [{"thought": "もう一度調べる。", "calls": [_LOOP]} for _ in range(8)]}

KINDS: dict[str, tuple[str, dict, int]] = {
    "policy": (POLICY_TASK, POLICY_TURNS, 2),
    "list": (LIST_TASK, LIST_TURNS, 3),
    "report": (REPORT_TASK, REPORT_TURNS, 4),
    "search": (SEARCH_TASK, SEARCH_TURNS, 3),
    "send": (SEND_TASK, SEND_OLD_TURNS, 3),
    "runaway": (RUNAWAY_TASK, RUNAWAY_TURNS, 8),
}


@dataclass(frozen=True)
class Job:
    """キューに積む1件。ジョブは「タスク＋どう応答するか」で決まる。"""

    job_id: str
    kind: str

    @property
    def task(self) -> str:
        return KINDS[self.kind][0]

    @property
    def scenario(self) -> dict:
        return KINDS[self.kind][1]

    @property
    def steps(self) -> int:
        """完走に必要な手数（＝LLM 呼び出し回数）。"""
        return KINDS[self.kind][2]


# --- ワークロード -----------------------------------------------------------
WORKLOAD_KINDS = ("policy", "list", "report", "search",
                  "policy", "list", "report", "search")


def workload() -> list[Job]:
    """本章の基本ワークロード。8件・のべ24ステップ。"""
    return [Job(f"TASK-{151 + i}", kind) for i, kind in enumerate(WORKLOAD_KINDS)]


def total_steps(jobs: list[Job]) -> int:
    return sum(job.steps for job in jobs)


def strategy_jobs() -> list[Job]:
    """レート制限の作法を比べる用。手数をそろえた4件（3ステップ×4）。"""
    return [Job(f"TASK-{141 + i}", "list") for i in range(4)]


def crash_jobs() -> list[Job]:
    """ワーカーが落ちる実験用。落ちる側（4ステップ）と後続（2ステップ）。"""
    return [Job("TASK-161", "report"), Job("TASK-162", "policy")]


def isolation_jobs() -> list[Job]:
    """1件だけ止まらないジョブを混ぜたワークロード。"""
    return [Job("TASK-171", "policy"), Job("TASK-172", "runaway"), Job("TASK-173", "list")]


# --- ジョブごとの作業領域 ---------------------------------------------------
def build_job_tools(slot: str) -> ToolRegistry:
    """作業領域を `workspace/session15/{slot}/` に閉じ込めたツール一式を返す。

    `agentkit` は1行も変更しない。`write_file` / `read_file` を差し替えるだけで、
    モデルから見える引数は同じ（`report.md`）のまま、実際の書き込み先が分かれる。
    """
    base = f"session15/{slot}"
    registry = build_registry()
    registry = registry.subset([n for n in registry.names()
                                if n not in ("write_file", "read_file")])
    registry.register(Tool(
        "write_file",
        "作業領域にファイルを書きます。レポートの下書きなどに使います。",
        {"type": "object",
         "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
         "required": ["path", "content"]},
        lambda path, content: write_file(f"{base}/{path}", content),
        idempotent=True, tags=("write",)))
    registry.register(Tool(
        "read_file",
        "作業領域のファイルを読みます。作業領域の外は読めません。",
        {"type": "object", "properties": {"path": {"type": "string"}},
         "required": ["path"]},
        lambda path: read_file(f"{base}/{path}"), tags=("read",)))
    return registry


def artifact_text(slot: str, name: str = "report.md") -> str:
    path = WORKSPACE / "session15" / slot / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


# --- 後始末（副作用を出す演習は前後で必ず戻す）------------------------------
_make_data = None


def reset_data() -> None:
    """業務データを初期状態に戻す（セッション12・13と同じ作法）。"""
    global _make_data
    if _make_data is None:
        sys.path.insert(0, str(ROOT / "tools"))
        import make_data  # noqa: PLC0415

        _make_data = make_data
    with contextlib.redirect_stdout(io.StringIO()):
        _make_data.main()


def jsonl_count(name: str) -> int:
    path = DATA / f"{name}.jsonl"
    if not path.exists():
        return 0
    return sum(1 for line in path.open(encoding="utf-8") if line.strip())


def clear_workspace() -> None:
    """本章が作った作業領域を消す（前回の残骸を成果物と数えないため）。"""
    shutil.rmtree(WORKSPACE / "session15", ignore_errors=True)


def main() -> None:
    jobs = workload()
    print("=== 基本ワークロード（8件）===")
    print("job_id | 型 | 手数 | タスク")
    for job in jobs:
        print(f"{job.job_id} | {job.kind} | {job.steps} | {job.task}")
    print(f"\nのべ手数（LLM 呼び出し）= {total_steps(jobs)} 回")
    print("※ 手数はシナリオで決まっている。何度流しても同じである。")


if __name__ == "__main__":
    main()
