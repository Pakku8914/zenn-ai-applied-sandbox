#!/usr/bin/env python3
"""判定に使う計算と、人に渡す1枚（成果物）の生成。

    python src/mid01/analysis.py

ここに置くのは「状態が決まれば出力も決まる」処理だけである。だから何度実行しても
同じ文字列になり、テストできる。モデルに書かせるのは最後の要約1文だけにする
（本文まで書かせると、根拠と食い違ったときに直せない）。
"""

from __future__ import annotations

import re

from _paths import setup

ROOT = setup()

from agentkit.biztools import WORKSPACE  # noqa: E402
from agentkit.clock import FixedClock  # noqa: E402

from machine import (ARTIFACT_PATH, HANDOFF_PATH, OUTCOME_LABELS,  # noqa: E402
                     ResearchState)

MID_DIR = WORKSPACE / "mid01"
CLOCK = FixedClock()

# 「5万円」を先に見る。「10日以内」のような数字に引っかからないよう、単位ごと拾う
MAN_YEN = re.compile(r"(\d+)\s*万円")
YEN = re.compile(r"([\d,]+)\s*円")


def extract_threshold(text: str) -> int | None:
    """規程の本文から判定基準の金額を取り出す。取れなければ None。

    None は「判定できない」を意味する。ここで 0 や既定値を返してはいけない
    （根拠のない基準で判定した報告が、根拠付きの報告と同じ見た目で出てしまう）。
    """
    if not text:
        return None
    hit = MAN_YEN.search(text)
    if hit:
        return int(hit.group(1)) * 10_000
    hit = YEN.search(text)
    if hit:
        return int(hit.group(1).replace(",", ""))
    return None


def find_findings(table: str, threshold: int) -> list[dict]:
    """`find_expenses` の表から「基準額以上なのに submitted のまま」の行を拾う。

    1行の形は
      EXP-0004 | 佐藤 健 | 145000 | 出張旅費 | submitted
    見出し行（「該当 2 件（表示 2 件）」）は EXP- で始まらないので自然に除かれる。
    """
    rows: list[dict] = []
    for line in table.splitlines():
        cols = [c.strip() for c in line.split("|")]
        if len(cols) < 5 or not cols[0].startswith("EXP-") or not cols[2].isdigit():
            continue
        if int(cols[2]) >= threshold and cols[4] == "submitted":
            rows.append({"expense_id": cols[0], "employee": cols[1],
                         "amount": int(cols[2]), "category": cols[3],
                         "status": cols[4]})
    return sorted(rows, key=lambda r: r["expense_id"])


# ---------------------------------------------------------------------------
# 成果物（4通り）。どの終わり方でも、必ず同じ3つの節を持たせる
#   ## 結果 … 何を渡すのか
#   ## 根拠 … どこから言えるのか
#   ## 次にやること … 受け取った人が次に何をするのか
# ---------------------------------------------------------------------------
def _head(st: ResearchState, outcome: str) -> list[str]:
    basis = f"{st.threshold:,} 円以上は事前承認が必要" if st.threshold else "未確認"
    return [
        f"# 経費規程の遵守状況の調査（{OUTCOME_LABELS[outcome]}）",
        "",
        f"- タスク: {st.task_id}",
        f"- 調査時点: {CLOCK.now().isoformat()}",
        f"- 判定基準: {basis}",
        f"- ここまでの手数: {st.llm_calls} 回",
        "",
        "## 結果",
        "",
        f"- 結果: {OUTCOME_LABELS[outcome]}",
    ]


def _evidence(st: ResearchState) -> list[str]:
    lines = ["", "## 根拠", ""]
    if st.sources:
        lines += [f"- {source}" for source in st.sources]
    else:
        lines.append("- （採用できた根拠はありません）")
    if st.notes:
        lines += ["", "参照したが根拠に採用しなかったもの:", ""]
        lines += [f"- {note}" for note in st.notes]
    return lines


def _next_actions(actions: list[str]) -> list[str]:
    return ["", "## 次にやること", "", *actions]


def render_report(st: ResearchState) -> str:
    """根拠付きのレポート（結果 = report）。"""
    lines = _head(st, "report")
    lines.append(f"- 基準額以上で事前承認の記録がない申請: {len(st.findings)} 件")
    lines.append("")
    if st.findings:
        lines += ["| 申請ID | 申請者 | 金額 | 区分 | 状態 |",
                  "| :--- | :--- | --: | :--- | :--- |"]
        lines += [f"| {f['expense_id']} | {f['employee']} | {f['amount']:,} | "
                  f"{f['category']} | {f['status']} |" for f in st.findings]
        actions = [f"- {f['expense_id']}: 事前承認の記録の有無を所属長に確認する"
                   for f in st.findings]
    else:
        lines.append("- 該当なし")
        actions = ["- 追加の対応は不要。翌月の締めのあとに同じ調査を再実行する"]
    return "\n".join(lines + _evidence(st) + _next_actions(actions)) + "\n"


def render_partial(st: ResearchState) -> str:
    """上限に達したときの部分結果（結果 = partial）。

    「途中で止まりました」だけでは受け取った人が動けない。
    どこまで進んだか・何が残っているか・次にどうするかを必ず書く。
    """
    missing = ", ".join(st.missing_sources()) or "なし"
    lines = _head(st, "partial")
    lines += [
        f"- 打ち切りの理由: 手数の上限 {st.max_llm_calls} 回に達した",
        f"- 打ち切った段階: {st.stopped_at or st.state}",
        f"- そろっていない材料: {missing}",
        "- 判定: していない（材料が足りないため）",
    ]
    actions = [
        f"- そろっていない材料（{missing}）を取得してから同じ計画で再実行する",
        f"- 上限を上げる場合は {st.max_llm_calls + 2} 回を目安にする"
        "（収集3手＋報告1手＋余裕）",
    ]
    return "\n".join(lines + _evidence(st) + _next_actions(actions)) + "\n"


def render_insufficient(st: ResearchState) -> str:
    """根拠がそろわないときの申し送り（結果 = insufficient）。

    ここで「該当なし」と書いてはいけない。調べられなかったことと、
    調べたうえで無かったことは別である。
    """
    reason = ("規程から判定基準の金額を読み取れなかった" if st.threshold is None
              else "判定に必要な材料がそろわなかった")
    missing = ", ".join(st.missing_sources()) or "なし"
    lines = _head(st, "insufficient")
    lines += [
        f"- 判定していない理由: {reason}",
        f"- そろっていない材料: {missing}",
        "- 判定: していない（「該当なし」ではない）",
    ]
    actions = [
        "- 判定基準（金額）を経理部に確認する",
        "- 確認できたら、同じ計画のまま再実行する",
    ]
    return "\n".join(lines + _evidence(st) + _next_actions(actions)) + "\n"


def render_handoff(st: ResearchState) -> str:
    """人へ渡すときの引き継ぎメモ（結果 = handoff）。"""
    lines = _head(st, "handoff")
    lines += [
        f"- 引き継ぐ理由: {st.handoff_reason or '（記録なし）'}",
        f"- 止まった段階: {st.stopped_at or st.state}",
        f"- 作成済みの成果物: {st.artifact or 'なし'}",
        "- 判定: していない",
    ]
    actions = [
        "- 引き継ぐ理由を読み、道具側の問題か判断の問題かを切り分ける",
        "- 道具側なら復旧を待って再実行する。判断が必要ならこの場で人が決める",
    ]
    return "\n".join(lines + _evidence(st) + _next_actions(actions)) + "\n"


RENDERERS = {
    "report": render_report,
    "partial": render_partial,
    "insufficient": render_insufficient,
    "handoff": render_handoff,
}


def artifact_text(outcome: str, st: ResearchState) -> str:
    if outcome not in RENDERERS:
        raise ValueError(f"未知の結果です: {outcome!r}（{', '.join(RENDERERS)}）")
    return RENDERERS[outcome](st)


def summary_line(st: ResearchState, outcome: str) -> str:
    """最終回答（1文）。report 以外はモデルに書かせず状態から作る。

    識別子（EXP-0001 など）を入れないのは、根拠の照合を通していない文に
    識別子を混ぜると、それ自体が幻覚の温床になるため。
    """
    missing = ", ".join(st.missing_sources()) or "なし"
    if outcome == "partial":
        return (f"手数の上限 {st.max_llm_calls} 回に達したため打ち切りました。"
                f"ここまでの結果と残りの作業を {ARTIFACT_PATH} に保存しました"
                f"（そろっていない材料: {missing}）。")
    if outcome == "insufficient":
        return (f"判定に必要な根拠がそろわないため、判定していません。"
                f"詳細と次の一手を {ARTIFACT_PATH} に保存しました"
                f"（そろっていない材料: {missing}）。")
    if outcome == "handoff":
        return (f"人の判断が必要なため引き継ぎます。理由: {st.handoff_reason}"
                f" 引き継ぎメモを {HANDOFF_PATH} に保存しました。")
    raise ValueError(f"report は最終回答をモデルが書きます: {outcome!r}")


# ---------------------------------------------------------------------------
# 成果物の置き場所（副作用は作業領域の中だけ）
# ---------------------------------------------------------------------------
def artifact_path(outcome: str) -> str:
    """結果に応じた成果物のパス。引き継ぎだけは人向けの別ファイルにする。"""
    return HANDOFF_PATH if outcome == "handoff" else ARTIFACT_PATH


def clear_artifacts() -> None:
    """前回の走行の成果物を消す。前の実行を採点しないため。"""
    for name in ("report.md", "handoff.md"):
        path = MID_DIR / name
        if path.exists():
            path.unlink()


def artifacts_on_disk() -> list[str]:
    """実際に残ったファイル。副作用は軌跡ではなくデータ側で数える。"""
    if not MID_DIR.exists():
        return []
    return sorted(path.name for path in MID_DIR.glob("*.md"))


def read_artifact(path: str) -> str:
    target = WORKSPACE / path
    return target.read_text(encoding="utf-8") if target.exists() else ""


def main() -> None:
    print("=== 規程から判定基準を取り出す ===")
    samples = [
        "経費精算: 領収書を添付し、支出日から10日以内に申請する。1件5万円以上は事前承認が必要。",
        "会議室予約: 連続利用は4時間まで。10名以上の会議は大会議室を優先する。",
        "",
    ]
    for text in samples:
        print(f"{extract_threshold(text)!r} <- {text[:40] or '（空）'}")

    print()
    print("=== 表から該当行を拾う ===")
    table = ("該当 2 件（表示 2 件）\n"
             "EXP-0004 | 佐藤 健 | 145000 | 出張旅費 | submitted\n"
             "EXP-0002 | 高橋 涼 | 68000 | 接待交際費 | submitted")
    for row in find_findings(table, 50_000):
        print(row)


if __name__ == "__main__":
    main()
