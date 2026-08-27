#!/usr/bin/env python3
"""最終プロジェクト・成果物⑤：トレースの設計。

    python src/final/tracing.py

「ログを出しています」は設計ではない。引き継ぐ人に渡すべきなのは、次の4つを
**決めきった宣言**である。

  ① 何を1区間（スパン）とするか … task → step → llm / tool の3階層
  ② 何を相関IDとして必ず残すか … task_id / span_id / parent_id / call_id
  ③ どの粒度で保存するか       … 伏せ字にすると再生できなくなる区間が出る
  ④ どれを残し、どれを捨てるか … 失敗は全件、正常は間引く（テールベース）

スパンの木は S14 の実装（`src/session14/spanlog.py`）をそのまま使う。
`agentkit` は1行も変更しない。
"""

from __future__ import annotations

from final_paths import setup

ROOT = setup()

from spanlog import (UNITS_A, ancestors, census, counts_by_kind,  # noqa: E402
                     find_by_call_id, render_tree, spans_from_trajectory)

# --- ② 相関ID（どの粒度でも落とさない）--------------------------------------
CORRELATION_IDS = ("task_id", "span_id", "parent_id", "call_id")
CORRELATION_NOTE = "相関IDはどの粒度でも落とさない（削るのは中身であって手がかりではない）"

# --- ③ 粒度（出典：S14 の実測。同じ1件を4通りに記録して数えた）---------------
GRAIN_NOTE = "追跡可能性と情報漏洩リスクは交換関係にある"
GRAINS: tuple[tuple[str, str, int, str, str], ...] = (
    # 粒度, 1スパンあたりの項目, 機密が残ったレコード数, 再生, 保存期間（運用の宣言）
    ("要約のみ", "相関ID＋kind＋name＋ms＋ok＋result_len", 0, "できない", "90日"),
    ("引数のハッシュ付き", "＋args_hash", 0, "できない（応答が無い）", "30日"),
    ("全文（無加工）", "＋args＋result＋thought", 2, "できる", "残さない"),
    ("全文（伏せ字）", "＋伏せ字を通した args＋result＋thought", 0,
     "できない（伏せた区間から先）", "7日"),
)
DEFAULT_GRAIN = "全文（伏せ字）"

# --- ④ サンプリング（出典：S14 の実測。8件のうち失敗は5件）-------------------
SAMPLING = (
    ("全件保存", "8/8", "5/5", 0),
    ("一律 1/2（到着順）", "4/8", "2/5", 3),
    ("テールベース（失敗は全件・正常は 1/2）", "7/8", "5/5", 0),
)
SAMPLING_CHOICE = "テールベース（失敗は全件・正常は 1/2）"

# 例に使う相関ID（正常系の3手目、レポートを書いた呼び出し）
SAMPLE_CALL_ID = "expense_report-3-0"

# --- 引き継いだ人が最初にやる3手 ---------------------------------------------
FIRST_MOVES = (
    ("① 1件を特定する", "task_id で軌跡とスパンを引く",
     "traces/{task_id}.jsonl と traces/session14/{task_id}.spans.jsonl"),
    ("② 位置を決める", "call_id からスパンを引き、親をたどって根まで並べる",
     "`find_by_call_id()` → `ancestors()`"),
    ("③ 手元で起こす", "軌跡からカセットを作り、記録した call_id のまま再生する",
     "`ReplayClient`（`FixtureClient` は ID を作り直すので2手目で止まる）"),
)


def span_stats(traj) -> dict:
    """1件の軌跡からスパンの木を作り、形と所要を返す。"""
    spans = spans_from_trajectory(traj, UNITS_A)
    kinds = counts_by_kind(spans)
    return {"task_id": traj.task_id, "spans": spans, "count": len(spans),
            "kinds": kinds, "ms": spans[0].ms, "census": census(spans),
            "steps": len(traj.steps), "stop_reason": traj.stop_reason}


def locate(traj, call_id: str) -> dict:
    """相関ID から1件の中の位置を決める（引き継ぎ後に最初に使う手順）。"""
    spans = spans_from_trajectory(traj, UNITS_A)
    hits = find_by_call_id(spans, call_id)
    if not hits:
        raise KeyError(f"call_id {call_id} を持つスパンがありません。")
    return {"hits": len(hits), "span_id": hits[0].span_id, "name": hits[0].name,
            "path": ancestors(spans, hits[0].span_id)}


def render_grains_md() -> str:
    lines = ["| 粒度 | 1スパンあたりの項目 | 機密が残ったレコード | 再生 | 保存期間 |",
             "| :--- | :--- | --: | :--- | :--- |"]
    for grain, fields, secrets, replay, keep in GRAINS:
        mark = "（既定）" if grain == DEFAULT_GRAIN else ""
        lines.append(f"| {grain}{mark} | {fields} | {secrets} | {replay} | {keep} |")
    return "\n".join(lines)


def render_sampling_md() -> str:
    lines = ["| 方式 | 保存 | 失敗の保存 | 取りこぼした失敗 |",
             "| :--- | :--- | :--- | --: |"]
    for plan, kept, kept_fail, lost in SAMPLING:
        mark = "（採用）" if plan == SAMPLING_CHOICE else ""
        lines.append(f"| {plan}{mark} | {kept} | {kept_fail} | {lost} |")
    return "\n".join(lines)


def trace_design_md(ok_traj, bad_traj) -> str:
    ok, bad = span_stats(ok_traj), span_stats(bad_traj)
    write = locate(ok_traj, SAMPLE_CALL_ID)
    tree = render_tree(ok["spans"])
    return "\n".join([
        "# トレースの設計：みなと商事オペレーション代行エージェント",
        "",
        "## 1. 何を1区間（スパン）とするか",
        "",
        "task → step → llm / tool の3階層にします。軌跡（`Trajectory`）には "
        "`call_id`・ツール結果・`usage` が残っているので、"
        "**スパンは軌跡から後で投影できます**。走行中に別の記録を持つ必要はありません。",
        "",
        "```text",
        *tree,
        "```",
        "",
        f"- 正常系の1件（{ok['task_id']}）: {ok['census']} 所要 {ok['ms']}ms",
        f"- 失敗した1件（{bad['task_id']}）: {bad['census']} 所要 {bad['ms']}ms"
        f"（停止理由 {bad['stop_reason']}）",
        "- 所要は「回数 × 宣言単価」で出します。**実時間を測るとトレースが再現しません**"
        "（同じ入力でも毎回違う値になります）",
        "",
        "## 2. 相関ID",
        "",
        f"- 必ず残す: {' / '.join(f'`{name}`' for name in CORRELATION_IDS)}",
        f"- {CORRELATION_NOTE}",
        f"- 例: `call_id={SAMPLE_CALL_ID}`（{write['name']} の呼び出し）は "
        f"{write['span_id']} に一意に決まります（該当 {write['hits']} 件）。"
        f"親をたどると {' → '.join(write['path'])}",
        "",
        "## 3. 記録の粒度",
        "",
        render_grains_md(),
        "",
        f"- 既定は「{DEFAULT_GRAIN}」です",
        f"- {GRAIN_NOTE}。伏せ字にすると、伏せた区間から先が再生できなくなります",
        "- 全文（無加工）を長期保存しません。トレースは軌跡より長く残り、"
        "より多くの人が見るからです",
        "- 機密が残ったレコード数は S14 の実測値（同じ1件を4通りに記録して数えたもの）です",
        "",
        "## 4. サンプリング",
        "",
        render_sampling_md(),
        "",
        f"- 採用: {SAMPLING_CHOICE}",
        "- 一律に間引くと**失敗から先に消えます**。失敗は全件・正常だけ間引くと決めれば、"
        "保存量を減らしても診断能力は落ちません",
        "",
        "## 5. 引き継いだ人が最初にやる3手",
        "",
        "| 手順 | やること | 使うもの |",
        "| :--- | :--- | :--- |",
        *[f"| {label} | {what} | {how} |" for label, what, how in FIRST_MOVES],
        "",
    ])


def main() -> None:
    from evalspec import by_name, reset_data, run_case  # noqa: PLC0415

    reset_data()
    ok = run_case(by_name("expense_report"))
    bad = run_case(by_name("max_steps_loop"))
    print(trace_design_md(ok, bad))
    reset_data()


if __name__ == "__main__":
    main()
