#!/usr/bin/env python3
"""セッション8：成果物の組み立てと採点（決定的）。

「複数体にすると成果物がどう変わるか」を測るには、成果物を**採点できる形**に
しておく必要がある。文章の良し悪しではなく、「必要な事実が載っているか」で採点する
（成果物の採点はセッション5と同じ考え方）。

集計の対象は `list_expenses` が返す全件とする（期間の絞り込みは本章の主題ではない）。
違反の判定はセッション6と同じ規則を使う：**基準額以上なのに承認を経ていない申請**。

`agentkit` は1行も変更していない。足りない部分はこの層で足している。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.clock import FixedClock  # noqa: E402

# 表示順を固定する（辞書の並び順に成果物を依存させない＝出力を決定的にする）
CATEGORY_ORDER = ("交通費", "出張旅費", "接待交際費", "備品")

# 引き継ぎで渡すときに残す列。判断に使わない列は渡さない（ペイロードも設計対象）
EXPENSE_FIELDS = ("id", "amount", "category", "status")


# ---------------------------------------------------------------------------
# ツール結果 → 事実（facts）
# ---------------------------------------------------------------------------
def parse_expense_table(text: str) -> list[dict]:
    """`list_expenses` の出力表を行の辞書に戻す。

    ツール結果は文字列である。**次の判断に使う形へ直すのは呼ぶ側の仕事**
    （セッション4で扱ったツール結果の設計の続き）。
    """
    rows: list[dict] = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 6 or parts[0] == "expense_id":
            continue
        rows.append({"id": parts[0], "employee": parts[1], "amount": int(parts[2]),
                     "category": parts[3], "status": parts[4], "created_at": parts[5]})
    return rows


def extract_threshold(policy_text: str) -> int | None:
    """規程の本文から金額基準を取り出す（「1件5万円以上は事前承認が必要」）。"""
    m = re.search(r"(\d+)万円以上", policy_text)
    return int(m.group(1)) * 10_000 if m else None


def aggregate(rows: list[dict]) -> dict[str, int]:
    """区分ごとの合計。並び順は CATEGORY_ORDER で固定する。"""
    sums: dict[str, int] = {}
    for r in rows:
        sums[r["category"]] = sums.get(r["category"], 0) + r["amount"]
    ordered = {c: sums[c] for c in CATEGORY_ORDER if c in sums}
    for c in sorted(k for k in sums if k not in CATEGORY_ORDER):
        ordered[c] = sums[c]
    return ordered


def find_violations(rows: list[dict], threshold: int) -> list[str]:
    """基準額以上なのに承認を経ていない申請（セッション6と同じ判定）。"""
    return [r["id"] for r in rows
            if r["amount"] >= threshold and r["status"] == "submitted"]


def analyze(facts: dict) -> dict:
    """事実から決定的に導ける値だけを作る（集計係の仕事）。

    モデルに聞かない。同じ入力なら必ず同じ答えになる計算だからである
    （セッション6の「決定的に決まる判断はモデルに聞かない」の続き）。
    """
    out: dict = {}
    rows = facts.get("expenses") or []
    if rows:
        out["by_category"] = aggregate(rows)
        out["total"] = sum(r["amount"] for r in rows)
        out["count"] = len(rows)
    threshold = facts.get("threshold")
    if rows and threshold:
        out["violations"] = find_violations(rows, threshold)
    return out


def derived(facts: dict) -> dict:
    """溜まった事実に、導ける値を足したもの。成果物はここから組み立てる。"""
    return {**facts, **analyze(facts)}


# ---------------------------------------------------------------------------
# 事実 → 成果物
# ---------------------------------------------------------------------------
def render_report(facts: dict, clock=None) -> str:
    """レポート本文を事実から組み立てる。

    モデルが書いた文章をそのまま成果物にしない（セッション6の `__REPORT__` と同じ）。
    **引き継がれなかった項目は「無かったこと」として現れる**。これがこの章の主題である。
    """
    clock = clock or FixedClock()
    facts = derived(facts)
    lines = [f"# 経費レポート（{clock.today()} 時点）", ""]

    lines.append("## 区分別の合計")
    by_category = facts.get("by_category") or {}
    if by_category:
        lines += [f"- {name}: {amount:,} 円" for name, amount in by_category.items()]
    else:
        lines.append("- （区分別の内訳は引き継がれませんでした）")

    lines += ["", "## 総額"]
    total, count = facts.get("total"), facts.get("count")
    if total is None:
        lines.append("- （総額は引き継がれませんでした）")
    else:
        lines.append(f"- {total:,} 円" + (f"（{count} 件）" if count else ""))

    lines += ["", "## 規程違反の疑い"]
    violations, threshold = facts.get("violations"), facts.get("threshold")
    if violations is None:
        lines.append("- （申請一覧または判定基準が引き継がれず、判定していません）")
    elif not violations:
        lines.append("- なし")
    else:
        head = (f"- 基準額 {threshold:,} 円以上で未承認の申請: {len(violations)} 件"
                if threshold else f"- 未承認の申請: {len(violations)} 件")
        lines.append(head)
        lines += [f"  - {v}" for v in violations]
    return "\n".join(lines) + "\n"


def violations_count(facts: dict) -> int | None:
    """通知に載せる違反件数。件数だけ渡された場合と一覧を渡された場合の両方を扱う。"""
    if isinstance(facts.get("violations_count"), int):
        return facts["violations_count"]
    if isinstance(facts.get("violations"), list):
        return len(facts["violations"])
    return None


def render_notice(facts: dict) -> str:
    """経理部への通知文。渡されなかったことは書けない（書いたら幻覚になる）。"""
    facts = derived(facts)
    parts = [f"月次レポートを {facts.get('report_path') or '（保存先不明）'} に保存しました。"]
    total = facts.get("total")
    if total is not None:
        parts.append(f"総額は {total:,} 円です。")
    count = violations_count(facts)
    if count is None:
        parts.append("規程違反の件数は引き継がれていないため記載できません。")
    else:
        parts.append(f"規程違反の疑いは {count} 件です。")
    return "".join(parts)


# ---------------------------------------------------------------------------
# 採点
# ---------------------------------------------------------------------------
def expected_facts() -> dict:
    """採点の正解を業務データから決定的に作る。

    正解を手で書き写すと、データを作り直したときに黙ってずれる。
    ツールの出力から導いておけば、採点基準とデータが必ず一致する。
    """
    from agentkit.biztools import get_policy, list_expenses

    rows = parse_expense_table(list_expenses("all"))
    threshold = extract_threshold(get_policy("経費精算"))
    base = {"expenses": rows, "threshold": threshold}
    return {**base, **analyze(base)}


def score(report_text: str, notices: list[dict]) -> dict:
    """成果物を4項目で採点する。

    「動いた」「レポートが出た」では合否を判定できない。
    **必要な事実が載っているか**を機械的に見る。
    通知の中身はプロセスの外（`data/messages.jsonl`）で数える
    （副作用の回数はデータ側で数える。セッション6の規約）。
    """
    exp = expected_facts()          # 正解は業務データから決定的に導く
    wanted = len(exp["violations"])
    checks = {
        "区分別の合計が4区分そろっている":
            all(f"{name}: {amount:,} 円" in report_text
                for name, amount in exp["by_category"].items()),
        "総額が正しい": f"{exp['total']:,} 円" in report_text,
        "規程違反2件が注記されている":
            bool(exp["violations"]) and all(v in report_text for v in exp["violations"]),
        "通知に違反件数が入っている":                   # ← プロセスの外を見る
            any(f"規程違反の疑いは {wanted} 件です。" in (n.get("body") or "")
                for n in notices),
    }
    return {"checks": checks, "passed": sum(checks.values()), "total": len(checks),
            "missing": [k for k, ok in checks.items() if not ok]}


def render_expected() -> str:
    """採点の正解（本文に載せる数値の出どころ）を表示する。"""
    exp = expected_facts()
    lines = [f"判定基準（規程から）: {exp['threshold']:,} 円以上は事前承認が必要"]
    for name, amount in exp["by_category"].items():
        lines.append(f"  {name}: {amount:,} 円")
    lines.append(f"  総額: {exp['total']:,} 円（{exp['count']} 件）")
    lines.append(f"  規程違反の疑い: {', '.join(exp['violations'])}"
                 f"（{len(exp['violations'])} 件）")
    return "\n".join(lines)


if __name__ == "__main__":
    print(render_expected())
    print()
    print(render_report(expected_facts()), end="")
    print()
    print(render_notice({**expected_facts(), "report_path": "session08/report.md"}))
