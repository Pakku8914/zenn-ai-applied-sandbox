#!/usr/bin/env python3
"""セッション14 練習問題の参照解。**先に自分で書いてから読むこと。**

    python src/session14/ex_observe.py

判定は `src/session14/verify_practice.py` が行う。自分の実装で判定したい場合は、
この中の関数を自分のものに差し替えるだけでよい。
"""

from __future__ import annotations

import json

from breakdown import kind_totals, step_rows, token_shape  # noqa: E402
from failtags import (all_traces, root_step, sampling_rows, symptom_ranking,  # noqa: E402
                      symptoms, verdict)
from redaction import (FULL, FULL_MASKED, HASHED, LEAK_TASK, SUMMARY,  # noqa: E402
                       args_digest, cleanup, mask_trajectory, record_for, run_leak,
                       secret_hits)
from replay import (exception_name, make_cassette, replay_with_fixture,  # noqa: E402
                    replay_with_recorded_ids, same_trajectory, save_cassette)
from spanlog import (UNITS_A, UNITS_B, ancestors, census, counts_by_kind,  # noqa: E402
                     find_by_call_id, reset_data, run_case, spans_from_trajectory)

from agentkit.biztools import WORKSPACE, build_registry  # noqa: E402

INCIDENT_FILE = "s14_incident.md"
REQUIRED_SECTIONS = ("## 症状", "## 影響", "## 相関ID", "## 原因のステップ",
                     "## 再現手順", "## 記録の粒度", "## 恒久対策")

_TRACES = None


def traces():
    """8件の軌跡を1回だけ走らせて使い回す（副作用を増やさないため）。"""
    global _TRACES
    if _TRACES is None:
        _TRACES = all_traces()
    return _TRACES


# --- 問題1 ------------------------------------------------------------------
def span_census() -> dict[str, dict[str, int]]:
    """2件のスパン数と種別内訳を出す。"""
    out = {}
    for scenario, label, max_steps in (("expense_report", "経費レポート作成", 8),
                                       ("max_steps_loop", "同じ検索を繰り返す", 6)):
        spans = spans_from_trajectory(run_case(scenario, label, max_steps))
        row = counts_by_kind(spans)
        row["total"] = len(spans)
        row["ms"] = spans[0].ms
        out[f"TASK-{scenario}"] = row
    return out


# --- 問題2 ------------------------------------------------------------------
def lookup_call(call_id: str = "expense_report-3-0") -> dict:
    """相関ID から1件を引き、根までの経路を返す。"""
    spans = spans_from_trajectory(run_case("expense_report", "経費レポート作成"))
    hits = find_by_call_id(spans, call_id)
    span = hits[0]
    return {"hits": len(hits), "span_id": span.span_id, "name": span.name,
            "parent_id": span.parent_id, "path": ancestors(spans, span.span_id)}


# --- 問題3 ------------------------------------------------------------------
def grain_secrets() -> dict[str, int]:
    """粒度ごとに「機密が残ったレコード」を数える。"""
    spans = spans_from_trajectory(run_leak())
    out = {grain: secret_hits([record_for(s, grain) for s in spans])
           for grain in (SUMMARY, HASHED, FULL, FULL_MASKED)}
    cleanup()
    return out


# --- 問題4 ------------------------------------------------------------------
def unit_flip() -> dict[str, str]:
    """単価表を差し替えると、内訳の1位が入れ替わることを示す。"""
    traj = run_case("expense_report", "経費レポート作成")
    return {"A": kind_totals(traj, UNITS_A)["top"], "B": kind_totals(traj, UNITS_B)["top"],
            "A_total": kind_totals(traj, UNITS_A)["total"],
            "B_total": kind_totals(traj, UNITS_B)["total"],
            "steps": [row["ms"] for row in step_rows(traj, UNITS_A)],
            "monotonic": token_shape(traj)["monotonic"], "peak": token_shape(traj)["peak"]}


# --- 問題5 ------------------------------------------------------------------
def root_steps() -> dict[str, str]:
    """8件それぞれの「原因のステップ」を返す。"""
    return {t.task_id: root_step(t) for t in traces()}


# --- 問題6 ------------------------------------------------------------------
def replay_failure() -> dict:
    """記録した1件を再生する。FixtureClient と ReplayClient の差を出す。"""
    task, scenario, max_steps = "同じ検索を繰り返す", "max_steps_loop", 6
    original = run_case(scenario, task, max_steps)
    cassette = make_cassette(task, original, build_registry().specs())
    save_cassette("s14_max_steps_loop", cassette)
    fixture = replay_with_fixture(task, "s14_max_steps_loop", max_steps=max_steps)
    replayed = replay_with_recorded_ids(task, cassette, max_steps=max_steps)
    return {"cassette": len(cassette),
            "fixture_steps": len(fixture.steps), "fixture_stop": fixture.stop_reason,
            "fixture_exc": exception_name(fixture),
            "replay_steps": len(replayed.steps), "replay_stop": replayed.stop_reason,
            "flags": same_trajectory(original, replayed)}


# --- 問題7 ------------------------------------------------------------------
def symptom_top() -> tuple[str, int]:
    rows = symptom_ranking(traces())
    return rows[0]["symptom"], rows[0]["count"]


# --- 問題8 ------------------------------------------------------------------
def sampling_summary() -> list[dict]:
    return sampling_rows(traces())


# --- 問題9 ------------------------------------------------------------------
def masked_replay() -> dict:
    """伏せ字にした記録からは、伏せた区間から先が再生できないことを示す。"""
    tools = build_registry("manager")
    original = run_leak()
    masked = mask_trajectory(original)
    out = {}
    for label, traj in (("無加工", original), ("伏せ字", masked)):
        cassette = make_cassette(LEAK_TASK, traj, tools.specs())
        replayed = replay_with_recorded_ids(LEAK_TASK, cassette,
                                            tools=build_registry("manager"), max_steps=6,
                                            task_id="TASK-s14_leak_replay")
        out[label] = {"steps": len(replayed.steps), "stop": replayed.stop_reason}
    cleanup()
    return out


# --- 問題10 -----------------------------------------------------------------
def write_incident_report() -> str:
    """障害報告テンプレートを、実際のトレースから埋めて書き出す。"""
    traj = next(t for t in traces() if t.task_id == "TASK-max_steps_loop")
    spans = spans_from_trajectory(traj)
    tool_ids = [s.attrs["call_id"] for s in spans if s.kind == "tool"]
    sample = json.dumps(record_for(spans[3], HASHED), ensure_ascii=False)
    text = "\n".join([
        f"# 障害報告: {traj.task_id}",
        "",
        "## 症状",
        f"- {'／'.join(symptoms(traj))}（判定: {verdict(traj)}）",
        f"- 停止理由 {traj.stop_reason} / 手数 {len(traj.steps)} / {census(spans)}",
        "",
        "## 影響",
        "- 副作用なし（読み取り系のツールだけを呼んでいる）。利用者には結果が返っていない。",
        "",
        "## 相関ID",
        f"- task_id: {traj.task_id}",
        f"- ツール呼び出しの call_id: {tool_ids[0]} … {tool_ids[-1]}（{len(tool_ids)} 件）",
        "",
        "## 原因のステップ",
        f"- {root_step(traj)}（同じ引数の呼び出しが3回目に達した地点）",
        "",
        "## 再現手順",
        "1. `python src/session14/replay.py` でカセットを作る",
        "2. `ReplayClient` で再生すると、同じ軌跡・同じ停止理由が再現する",
        "",
        "## 記録の粒度",
        f"- 引数のハッシュ付きで記録した1レコード: {sample}",
        "",
        "## 恒久対策",
        "- 同じ (ツール名, 引数) が3回続いたら打ち切る（S03 の停止条件に追加する）",
        "- 症状「同じ操作の反復」を頻度表に載せ、次の週に減っているかを見る",
        "",
    ])
    path = WORKSPACE / INCIDENT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def incident_report_missing() -> list[str]:
    """必須の見出しのうち、書かれていないものを返す。"""
    path = WORKSPACE / INCIDENT_FILE
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return [s for s in REQUIRED_SECTIONS if s not in text]


def main() -> None:
    reset_data()
    print("問題1 スパンの数:", span_census())
    print("問題2 相関ID:", lookup_call())
    print("問題3 粒度ごとの機密:", grain_secrets())
    print("問題4 単価表の入れ替え:", unit_flip())
    print("問題5 原因のステップ:", root_steps())
    print("問題6 再生:", replay_failure())
    print("問題7 症状の1位:", symptom_top())
    print("問題8 サンプリング:", sampling_summary())
    print("問題9 伏せ字と再生:", masked_replay())
    write_incident_report()
    print("問題10 障害報告の不足見出し:", incident_report_missing() or "なし")
    print(f"引数のハッシュの桁数: {len(args_digest({'topic': '経費精算'}))}")
    reset_data()


if __name__ == "__main__":
    main()
