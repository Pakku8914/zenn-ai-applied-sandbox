#!/usr/bin/env python3
"""診断レポートを軌跡から生成する（S02〜S05 の合わせ技）。

    docker compose exec app python src/review01/report.py

障害報告に手で書くと、書く人によって観点が抜ける。レポートを軌跡から生成すると
「症状・証拠・原因・手当て・最終回答の信用」が必ず揃う。エージェントの運用では、
この5行を毎回同じ形で残せることが、直せることと同じくらい重要である。
"""

from __future__ import annotations

from _paths import setup

ROOT = setup()

from failure_modes import classify  # noqa: E402  (src/session02)

from diagnose import TREATMENT, cause_label, diagnose, is_trustworthy_done, untrusted_reasons  # noqa: E402


def diagnose_report(case) -> str:
    """1本の軌跡から5行の診断レポート（Markdown）を作る。"""
    kwargs = {"registry": case.registry, "allowed_tools": case.allowed}
    traj = case.traj
    modes = classify(traj, allowed_tools=set(case.allowed), registry=case.registry)
    causes = diagnose(traj, needed_steps=case.needed_steps, **kwargs)
    reasons = untrusted_reasons(traj, **kwargs)
    trusted = is_trustworthy_done(traj, **kwargs)
    treatment = ", ".join(dict.fromkeys(TREATMENT[cause] for cause in causes))
    return "\n".join([
        f"### {case.label}",
        f"- 症状: 停止理由 {traj.stop_reason} / 手数 {len(traj.steps)} / "
        f"ツール呼び出し {len(traj.tool_names)}",
        f"- 失敗モード: {', '.join(modes) or '検出なし'}",
        f"- 原因: {cause_label(causes, trusted)}",
        f"- 手当て: {treatment or '手当てなし'}",
        f"- 最終回答: {'信用してよい' if trusted else '信用できない'}"
        f"（{', '.join(reasons) or '裏取りできた'}）",
    ])


def report_all(cases) -> str:
    return "\n\n".join(diagnose_report(case) for case in cases)


def main() -> None:
    import traces

    print("## 復習01 診断レポート\n")
    print(report_all(traces.build_cases()))


if __name__ == "__main__":
    main()
