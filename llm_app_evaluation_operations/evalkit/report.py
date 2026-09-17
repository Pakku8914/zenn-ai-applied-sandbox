"""評価結果の集計とレポート出力。

「合格率が上がった」だけでは判断できない。どのタグで落ちたのか、コストは
いくらかかったのか、judge が壊れていないか、まで出せて初めて意思決定に使える。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from evalkit.checks import CheckResult, all_passed
from evalkit.client import LLMResponse
from evalkit.dataset import EvalCase
from evalkit.judge import JudgeVerdict


@dataclass
class CaseResult:
    """1 ケースの評価結果。"""

    case: EvalCase
    response: LLMResponse
    checks: list[CheckResult]
    verdict: JudgeVerdict | None = None

    @property
    def rules_passed(self) -> bool:
        return all_passed(self.checks)

    def passed(self, judge_threshold: int = 4) -> bool:
        """ルール検査に通り、judge 点がしきい値以上なら合格。"""
        if not self.rules_passed:
            return False
        if self.verdict is None:
            return True
        return self.verdict.parsed and self.verdict.score >= judge_threshold

    def failure_reasons(self) -> list[str]:
        reasons = [f"{c.name}: {c.detail}" for c in self.checks if not c.passed]
        if self.verdict is not None and not self.verdict.parsed:
            reasons.append("judge: 出力パース失敗")
        return reasons


@dataclass
class Summary:
    """データセット全体の集計値。"""

    total: int
    passed: int
    pass_rate: float
    avg_judge_score: float | None
    judge_parse_failures: int
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    per_tag: dict[str, tuple[int, int]] = field(default_factory=dict)
    failures: list[tuple[str, list[str]]] = field(default_factory=list)


def summarize(results: list[CaseResult], judge_threshold: int = 4) -> Summary:
    """CaseResult のリストから集計値を作る。"""
    if not results:
        raise ValueError("集計対象の結果が空です")

    passed_flags = [r.passed(judge_threshold) for r in results]
    scores = [r.verdict.score for r in results if r.verdict is not None and r.verdict.parsed]

    per_tag: dict[str, tuple[int, int]] = {}
    for result, ok in zip(results, passed_flags, strict=True):
        for tag in result.case.tags:
            hit, total = per_tag.get(tag, (0, 0))
            per_tag[tag] = (hit + (1 if ok else 0), total + 1)

    return Summary(
        total=len(results),
        passed=sum(passed_flags),
        pass_rate=sum(passed_flags) / len(results),
        avg_judge_score=mean(scores) if scores else None,
        judge_parse_failures=sum(
            1 for r in results if r.verdict is not None and not r.verdict.parsed
        ),
        total_cost_usd=sum(r.response.cost_usd() for r in results),
        total_input_tokens=sum(r.response.input_tokens for r in results),
        total_output_tokens=sum(r.response.output_tokens for r in results),
        per_tag=dict(sorted(per_tag.items())),
        failures=[
            (r.case.id, r.failure_reasons())
            for r, ok in zip(results, passed_flags, strict=True)
            if not ok
        ],
    )


def render_markdown(summary: Summary, title: str = "評価レポート") -> str:
    """CI の PR コメントにそのまま貼れる Markdown を組み立てる。"""
    lines = [
        f"## {title}",
        "",
        f"- 合格: **{summary.passed} / {summary.total}**（合格率 {summary.pass_rate:.1%}）",
    ]
    if summary.avg_judge_score is not None:
        lines.append(f"- judge 平均点: **{summary.avg_judge_score:.2f}** / 5.00")
    if summary.judge_parse_failures:
        lines.append(f"- :warning: judge 出力のパース失敗: {summary.judge_parse_failures} 件")
    lines += [
        f"- トークン: 入力 {summary.total_input_tokens:,} / 出力 {summary.total_output_tokens:,}",
        f"- 概算コスト: ${summary.total_cost_usd:.4f}",
        "",
        "### タグ別の合格率",
        "",
        "| タグ | 合格 / 件数 | 合格率 |",
        "| :--- | :---------- | :----- |",
    ]
    for tag, (hit, total) in summary.per_tag.items():
        lines.append(f"| {tag} | {hit} / {total} | {hit / total:.0%} |")

    if summary.failures:
        lines += ["", "### 失敗したケース", ""]
        for case_id, reasons in summary.failures:
            lines.append(f"- `{case_id}`: {'; '.join(reasons) or '判定点がしきい値未満'}")
    else:
        lines += ["", "失敗したケースはありません。"]

    return "\n".join(lines) + "\n"
