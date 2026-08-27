#!/usr/bin/env python3
"""セッション14：記録の粒度 — 何を記録し、何を記録しないか。

    python src/session14/redaction.py

S12 で見たとおり、機密は送信されなくても漏れる。**軌跡・ログ・トレース・エラー
メッセージが複製**だからである。トレースは軌跡より長く残り、より多くの人が見るので、
S12 の伏せ字はそのままトレースにも要る。

一方で、伏せ字にすると**再生できなくなる区間が出る**。追跡可能性と情報漏洩リスクは
交換関係にあり、粒度はその交換をどこで切るかの設計である。ここでは同じ1件を
4通りに記録し、機密の残存と再生可否を実際に測る。

`agentkit` は1行も変更しない。使うのは既存の `agentkit.trace.redact`（キー名で落とす層）
と、S12 の `mask_secrets`（値の中の機密を伏せる層）である。
"""

from __future__ import annotations

import hashlib
import json

from spanlog import (UNITS_A, Trajectory, reset_data, run_case,  # noqa: E402
                     census, spans_from_trajectory)

from agentkit.biztools import WORKSPACE, build_registry  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.models import Step, ToolCall, ToolResult  # noqa: E402
from agentkit.trace import redact  # noqa: E402
from defenses import mask_secrets  # noqa: E402  （S12：値の中の機密を伏せる）
from replay import (make_cassette, replay_with_recorded_ids)  # noqa: E402

SUMMARY = "要約のみ"
HASHED = "引数のハッシュ付き"
FULL = "全文（無加工）"
FULL_MASKED = "全文（伏せ字）"

NOTE_FILE = "s14_note.md"

# 機密がトレースに入る最短経路。役職が manager なので住所と評価が返る（S12 の権限）。
LEAK_SCENARIO = {
    "name": "s14_leak",
    "turns": [
        {"thought": "担当者の連絡先を確認する。",
         "calls": [{"name": "get_employee", "args": {"employee_id": "EMP-002"}}]},
        {"thought": "確認した内容を作業メモに残す。",
         "calls": [{"name": "write_file",
                    "args": {"path": NOTE_FILE,
                             "content": "担当者: 鈴木 彩 / 住所: 東京都品川区2-2-2 / "
                                        "連携キー: sk-minato-0001"}}]},
        {"thought": "メモを保存したので完了する。", "final": "作業メモを保存しました。"},
    ],
}
LEAK_TASK = "EMP-002 の連絡先を確認して作業メモに残す"


# ---------------------------------------------------------------------------
# 2つの層（キー名で落とす / 値の中を伏せる）
# ---------------------------------------------------------------------------
def mask_values(value):
    """値の中に入った機密を伏せる（S12 の `mask_secrets` を再帰的にかける）。"""
    if isinstance(value, dict):
        return {k: mask_values(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_values(v) for v in value]
    if isinstance(value, str):
        return mask_secrets(value)
    return value


def args_digest(args: dict) -> str:
    """引数の指紋。**同じ引数か**は判定できるが、元には戻せない。"""
    blob = json.dumps(args, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# 粒度ごとのレコード
# ---------------------------------------------------------------------------
def record_for(span, grain: str) -> dict:
    """1スパンを指定の粒度で1レコードにする。

    **相関ID（span_id / parent_id / task_id / call_id）はどの粒度でも落とさない。**
    削るのは中身であって、追跡の手がかりではない。
    """
    rec = {"span_id": span.span_id, "parent_id": span.parent_id, "task_id": span.task_id,
           "kind": span.kind, "name": span.name, "ms": span.ms}
    if span.kind == "task":
        rec["stop_reason"] = span.attrs.get("stop_reason")
    if span.kind == "llm":
        rec["in"] = span.attrs.get("in", 0)
        rec["out"] = span.attrs.get("out", 0)
        if grain in (FULL, FULL_MASKED):
            thought = span.attrs.get("thought", "")
            rec["thought"] = mask_secrets(thought) if grain == FULL_MASKED else thought
    if span.kind == "tool":
        rec["call_id"] = span.attrs["call_id"]
        rec["ok"] = span.attrs["ok"]
        rec["result_len"] = span.attrs["result_len"]
        if grain in (HASHED, FULL, FULL_MASKED):
            rec["args_hash"] = args_digest(span.attrs["args"])
        if grain in (FULL, FULL_MASKED):
            args = redact(span.attrs["args"])          # ①キー名で落とす
            result = span.attrs["result"]
            if grain == FULL_MASKED:                    # ②値の中の機密を伏せる（S12）
                args = mask_values(args)
                result = mask_secrets(result)
            rec["args"] = args
            rec["result"] = result
    return rec


def secret_hits(records: list[dict]) -> int:
    """機密が残ったレコードの件数。データ側の値と照合するので取りこぼしが少ない。"""
    from defenses import first_secret  # noqa: PLC0415

    return sum(1 for r in records
               if first_secret(json.dumps(r, ensure_ascii=False)) is not None)


# ---------------------------------------------------------------------------
# 伏せ字にすると再生できなくなる区間が出る
# ---------------------------------------------------------------------------
def mask_trajectory(traj: Trajectory) -> Trajectory:
    """機密を伏せた軌跡の写しを返す（S12 の `redact_trajectory` と同じ考え方）。"""
    out = Trajectory(task_id=traj.task_id, task=mask_secrets(traj.task),
                     final=mask_secrets(traj.final) if traj.final else traj.final,
                     stop_reason=traj.stop_reason)
    for s in traj.steps:
        out.steps.append(Step(
            index=s.index, thought=mask_secrets(s.thought),
            calls=[ToolCall(c.call_id, c.name, mask_values(dict(c.args))) for c in s.calls],
            results=[ToolResult(r.call_id, r.ok, mask_secrets(r.content),
                                mask_secrets(r.error) if r.error else r.error)
                     for r in s.results],
            usage=dict(s.usage)))
    return out


def run_leak() -> Trajectory:
    """機密がトレースに入る1件を走らせる（manager 権限で社員情報を引く）。"""
    return run_case("s14_leak", LEAK_TASK, 6,
                    llm=ScriptedClient(LEAK_SCENARIO), tools=build_registry("manager"),
                    task_id="TASK-s14_leak")


def replay_result(traj: Trajectory) -> str:
    """この軌跡から作ったカセットで再生できるか。"""
    tools = build_registry("manager")
    cassette = make_cassette(LEAK_TASK, traj, tools.specs())
    out = replay_with_recorded_ids(LEAK_TASK, cassette, tools=build_registry("manager"),
                                   max_steps=6, task_id="TASK-s14_leak_replay")
    verb = "できる" if out.stop_reason == traj.stop_reason and len(out.steps) == len(traj.steps) \
        else "できない"
    return f"{verb}（手数={len(out.steps)} 停止理由={out.stop_reason}）"


def grain_rows() -> list[dict]:
    traj = run_leak()
    spans = spans_from_trajectory(traj, UNITS_A)
    masked_traj = mask_trajectory(traj)
    replay_full = replay_result(traj)
    replay_masked = replay_result(masked_traj)
    unavailable = "できない（応答が記録されていない）"
    plan = (
        (SUMMARY, "相関ID＋kind＋name＋ms＋ok＋result_len", "できない", unavailable),
        (HASHED, "＋args_hash", "できる", unavailable),
        (FULL, "＋args＋result＋thought", "できる", replay_full),
        (FULL_MASKED, "＋伏せ字を通した args＋result＋thought", "できる", replay_masked),
    )
    rows = []
    for grain, fields, args_match, replayable in plan:
        records = [record_for(s, grain) for s in spans]
        rows.append({"grain": grain, "fields": fields, "secrets": secret_hits(records),
                     "args_match": args_match, "replay": replayable,
                     "census": census(spans), "steps": len(traj.steps),
                     "task_id": traj.task_id})
    return rows


def cleanup() -> None:
    path = WORKSPACE / NOTE_FILE
    if path.exists():
        path.unlink()


def main() -> None:
    reset_data()

    print("=== キー名で落とす層（agentkit.trace.redact）===")
    sample = {"employee_id": "EMP-002", "api_key": "sk-minato-0001",
              "note": "住所は東京都品川区2-2-2"}
    dumps = lambda d: json.dumps(d, ensure_ascii=False)  # noqa: E731
    print(f"入力: {dumps(sample)}")
    print(f"キー名で落とす: {dumps(redact(sample))}")
    print(f"値も伏せる（S12）: {dumps(mask_values(redact(sample)))}")
    print("→ キー名で落とす層は、値の中に入った機密を落とせない。両方の層が要る。")

    rows = grain_rows()
    print("\n=== 記録の粒度（同じ1件を4通りに記録する）===")
    print(f"軌跡: {rows[0]['task_id']} 手数={rows[0]['steps']} {rows[0]['census']}")
    print("粒度 | 1スパンあたりの項目 | 機密が残ったレコード | 引数の同一判定 | 再生")
    for r in rows:
        print(f"{r['grain']} | {r['fields']} | {r['secrets']} | {r['args_match']} | {r['replay']}")
    print("→ 伏せ字にすると、伏せた区間から先が再生できなくなる。"
          "追跡可能性と情報漏洩リスクは交換関係にある。")

    print("\n=== 引数のハッシュで分かること・分からないこと ===")
    a, b = {"employee_id": "EMP-002"}, {"employee_id": "EMP-003"}
    print(f"同じ引数 → 同じハッシュ: {args_digest(a) == args_digest(dict(a))}")
    print(f"1文字違う引数 → 別のハッシュ: {args_digest(a) != args_digest(b)}")
    print("ハッシュから元の引数は復元できない（＝同じ操作の反復は数えられるが、再生はできない）")

    print("\n=== 相関IDは、どの粒度でも削らない ===")
    spans = spans_from_trajectory(run_leak(), UNITS_A)
    tool_span = next(s for s in spans if s.kind == "tool")
    print(f"要約のみのレコードの項目: {list(record_for(tool_span, SUMMARY))}")
    print(f"うち相関ID: span_id={tool_span.span_id} parent_id={tool_span.parent_id} "
          f"call_id={tool_span.attrs['call_id']}")

    cleanup()
    reset_data()


if __name__ == "__main__":
    main()
