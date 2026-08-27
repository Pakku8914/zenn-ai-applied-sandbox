#!/usr/bin/env python3
"""人に渡す1枚（実行報告と引き継ぎ書）の生成。

    python src/mid02/writeup.py     # 2種類の雛形を表示する

ここに置くのは「状態が決まれば出力も決まる」処理だけである。だから何度実行しても
同じ文字列になり、テストできる。**報告文はモデルに書かせない。**
副作用の記録は、書いた本人（モデル）ではなくデータから作る。

もう1つの約束は、書き出す前に必ず `mask_secrets()`（S12）を通すことである。
引き継ぎ書もログも長く残る。**あとで消せない場所に機密を書かない。**
"""

from __future__ import annotations

import shutil

from _paths import setup

ROOT = setup()

from agentkit.biztools import WORKSPACE  # noqa: E402
from agentkit.clock import FixedClock  # noqa: E402
from defenses import mask_secrets  # noqa: E402  (S12)
from policy import MODE_LABEL  # noqa: E402  (S10)

from flow import (ARTIFACT_PATH, HANDOFF_PATH, OUTCOME_LABELS,  # noqa: E402
                  RUNBOOK_DOUBLE_PATH, RUNBOOK_STALLED_PATH)
from ledger import snapshot, summary_lines  # noqa: E402

MID_DIR = WORKSPACE / "mid02"
CLOCK = FixedClock()

NEXT_ACTIONS = {
    "report": [
        "- 予約・申請・連絡の3点がデータに残っていることを、受け取った人が1度だけ確認する",
        "- 申請の承認者は、監査ログの `approved` 行と申請の金額が一致していることを見る",
    ],
    "partial": [
        f"- 承認が滞っている場合は {RUNBOOK_STALLED_PATH} の手順に従う",
        "- 打ち消した操作は「やっていない」状態に戻っている。同じ計画で再実行できる",
        "- 打ち消せなかった操作（送信）は、受け取った人が訂正の連絡を出す",
    ],
    "insufficient": [
        "- そろっていない材料を取得してから、同じ計画で再実行する",
        "- 副作用は1件も出していない。データを直す作業は不要",
    ],
    "handoff": [
        f"- 承認が滞っている場合は {RUNBOOK_STALLED_PATH} の手順に従う",
        f"- 二重実行が疑われる場合は {RUNBOOK_DOUBLE_PATH} の手順に従う",
        "- 実行されたか分からない操作は、**再実行する前に**データを照合する",
    ],
}


def artifact_path(outcome: str) -> str:
    """結果に応じた成果物のパス。引き継ぎだけは人向けの別ファイルにする。"""
    return ARTIFACT_PATH if outcome == "report" else HANDOFF_PATH


def read_artifact(path: str) -> str:
    target = WORKSPACE / path
    return target.read_text(encoding="utf-8") if target.exists() else ""


def clear_workspace() -> None:
    """前の走行の成果物と生成物を消す（前の実行を採点しないため）。

    runbook は走行の産物ではないので消さない。
    """
    if not MID_DIR.exists():
        return
    for path in sorted(MID_DIR.iterdir()):
        if path.name.startswith("runbook_"):
            continue
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink()


def _head(st, outcome: str, extra: list[str]) -> list[str]:
    basis = (f"{st.threshold:,} 円以上は事前承認が必要" if st.threshold else "未確認")
    return [
        f"# 部門報告会の準備（{OUTCOME_LABELS[outcome]}）",
        "",
        f"- タスク: {st.task_id}",
        f"- 実行時点: {CLOCK.now().isoformat()}",
        f"- 結果: {OUTCOME_LABELS[outcome]}",
        f"- 判定基準: {basis}",
        f"- 手数: {st.llm_calls} 回",
        *extra,
    ]


def _effects_table(st) -> list[str]:
    lines = ["", "## 実行した操作", "",
             "| 操作 | 内容 | 段階 | 承認 | 記録 |",
             "| :--- | :--- | :--- | :--- | :--- |"]
    if not st.effects:
        lines.append("| （なし） | — | — | — | — |")
        return lines
    for effect in st.effects:
        args = ", ".join(f"{k}={effect['args'][k]}" for k in sorted(effect["args"]))
        approvers = ", ".join(effect.get("approved_by") or []) or "—"
        lines.append(f"| {effect['tool']} | {args[:60]} | "
                     f"{MODE_LABEL.get(effect.get('mode', 'auto'), '—')} | {approvers} | "
                     f"{effect.get('ref') or '—'} |")
    return lines


def _summary_section(st) -> list[str]:
    lines = ["", "## 集計（隔離環境で計算）", ""]
    if st.summary_available and st.summary:
        lines += [f"    {line}" for line in st.summary.splitlines()]
        lines += ["", f"- 参照: {st.summary_ref or '（なし）'}"]
    else:
        lines.append("- 集計は付けていません（隔離実行が使えませんでした）。"
                     "報告の判断はこの集計に依存していません。")
    return lines


def _ledger_section() -> list[str]:
    return ["", "## データ側で数えた副作用", "", *summary_lines(snapshot())]


def _list_section(title: str, items: list[str]) -> list[str]:
    lines = ["", f"## {title}", ""]
    lines += [f"- {item}" for item in items] if items else ["- （なし）"]
    return lines


def report_text(st) -> str:
    """すべて実行できたときの実行報告（結果 = report）。"""
    lines = _head(st, "report", [])
    lines += _effects_table(st)
    lines += _summary_section(st)
    lines += _ledger_section()
    lines += _list_section("次にやること", NEXT_ACTIONS["report"])
    return mask_secrets("\n".join(lines) + "\n")


def handoff_text(st) -> str:
    """止まったときの引き継ぎ書（結果 = partial / insufficient / handoff）。

    5つの欄を必ず埋める（S11 の引き継ぎ書と同じ考え方）。空欄は「なし」と書く。
    書いていない欄があると、受け取った人は最初から全部確認するしかなくなる。
    """
    outcome = st.outcome if st.outcome in OUTCOME_LABELS else "handoff"
    remaining = [f"{e['tool']}: {e.get('ref') or '記録なし'}"
                 for e in st.effects if not e.get("compensated")]
    lines = _head(st, outcome, [
        f"- 止まった段階: {st.stopped_at or st.state}",
        f"- 止まった理由: {st.handoff_reason or '（記録なし）'}",
    ])
    lines += _list_section("済んでいて取り消していない操作", remaining)
    lines += _list_section("打ち消した操作", list(st.compensated))
    lines += _list_section("打ち消せなかった操作", list(st.uncompensated))
    lines += _list_section("実行されたか分からない操作", list(st.uncertain))
    lines += _list_section("遮断した試み（越境の疑い）", list(st.blocked_calls))
    lines += _list_section("計画外の提案", list(st.offplan))
    lines += _ledger_section()
    lines += _list_section("次にやること", NEXT_ACTIONS.get(outcome, NEXT_ACTIONS["handoff"]))
    return mask_secrets("\n".join(lines) + "\n")


def artifact_body(st) -> str:
    return report_text(st) if st.outcome == "report" else handoff_text(st)


def summary_line(st) -> str:
    """最終回答（1文）。モデルには書かせない。"""
    snap = snapshot()
    if st.outcome == "report":
        return (f"予約・申請・連絡の3点を実行しました（越境 {snap['越境']} 件 / "
                f"同じ冪等キーの申請 {snap['二重実行']} 組）。"
                f"実行報告を {ARTIFACT_PATH} に保存しました。")
    if st.outcome == "partial":
        return (f"副作用を出したあとに止まりました。打ち消した操作 {len(st.compensated)} 件 / "
                f"打ち消せなかった操作 {len(st.uncompensated)} 件。"
                f"引き継ぎ書を {HANDOFF_PATH} に保存しました。")
    if st.outcome == "insufficient":
        return (f"材料がそろわないため、副作用を1件も出していません。"
                f"詳細を {HANDOFF_PATH} に保存しました。")
    return (f"人の判断が必要なため引き継ぎます。理由: {st.handoff_reason} "
            f"引き継ぎ書を {HANDOFF_PATH} に保存しました。")


class _Demo:
    """雛形を表示するためだけの最小の状態（本物は ops_agent.OpsState）。"""

    task_id = "TASK-M02-demo"
    state = "waiting"
    stopped_at = "waiting"
    outcome = "partial"
    threshold = 50_000
    llm_calls = 4
    summary = "件数=6 合計=285400 5万円以上=3"
    summary_ref = "mid02/out/TASK-M02-demo/summary.csv"
    summary_available = True
    effects = [{"tool": "book_room", "args": {"room": "うみかぜ", "start": "10:00"},
                "mode": "notify", "ref": "うみかぜ 10:00", "approved_by": [],
                "compensated": True}]
    compensated = ["book_room: うみかぜ の 10:00 の予約を 1 件取り消しました。"]
    uncompensated: list = []
    uncertain: list = []
    blocked_calls: list = []
    offplan: list = []
    handoff_reason = "承認されませんでした（理由: 参加者名簿の添付がありません）。"


def main() -> None:
    demo = _Demo()
    print("=== 引き継ぎ書の雛形 ===")
    print(handoff_text(demo))
    demo.outcome = "report"
    print("=== 実行報告の雛形 ===")
    print(report_text(demo))


if __name__ == "__main__":
    main()
