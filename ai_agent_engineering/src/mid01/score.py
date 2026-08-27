#!/usr/bin/env python3
"""成果物の採点（評価観点の機械化）。

    python src/mid01/score.py

このプロジェクトの評価は「成功したか」では**ない**。
「失敗したときに、受け取った人が動ける1枚を渡せたか」である。
だから4つの検査は、4通りの結果（report / partial / insufficient / handoff）すべてに
同じ形で適用できるようにしてある。

  ① 結果（何を渡すか）が明記されている  … 「たぶん終わった」を許さない
  ② 根拠の節が空でない                  … 出典が無いなら無いと書く
  ③ 次にやることが書かれている          … 受け取った人が動ける
  ④ 書かれた申請IDがすべて根拠にある    … 幻覚を成果物に載せない
"""

from __future__ import annotations

from _paths import setup

ROOT = setup()

from failure_modes import ID_PATTERN  # noqa: E402  (S02)

from analysis import artifact_path, read_artifact  # noqa: E402
from machine import OUTCOME_LABELS  # noqa: E402

CHECKS = (
    "結果（何を渡すか）が明記されている",
    "根拠の節が空でない",
    "次にやることが書かれている",
    "書かれた申請IDがすべて根拠にある",
)


def section(text: str, heading: str) -> list[str]:
    """`## 見出し` の下にある空でない行を返す。節があるだけで空なら空リスト。"""
    lines: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line.strip() == heading
            continue
        if inside and line.strip():
            lines.append(line.strip())
    return lines


def ungrounded_ids(text: str, evidence: str) -> list[str]:
    """文中の識別子のうち、採用した根拠に現れないものを返す。

    判定は文字列の照合だけで行う（モデルを使わない）。だから決定的にテストできる。
    """
    return [found for found in ID_PATTERN.findall(text or "")
            if found not in evidence]


def score_artifact(text: str, outcome: str, evidence: str, final: str = "") -> dict:
    """成果物1枚を採点する。`missing` に落ちた検査の名前が入る。"""
    if outcome not in OUTCOME_LABELS:
        raise ValueError(f"未知の結果です: {outcome!r}")
    passed = [
        f"- 結果: {OUTCOME_LABELS[outcome]}" in text,
        bool(section(text, "## 根拠")),
        bool(section(text, "## 次にやること")),
        not ungrounded_ids(f"{text}\n{final or ''}", evidence),
    ]
    return {
        "passed": sum(passed),
        "total": len(CHECKS),
        "missing": [name for name, ok in zip(CHECKS, passed) if not ok],
    }


def score_run(state, traj) -> dict:
    """走行の結果を採点する。成果物は**ディスクから読む**。

    状態の中の文字列を採点しても「書いたつもり」を検出できない。
    実際に書けたかどうかは、書いた先を読むしかない。
    """
    text = read_artifact(artifact_path(state.outcome))
    evidence = "\n".join(state.materials.values())
    return score_artifact(text, state.outcome, evidence, traj.final or "")


def main() -> None:
    from cases import run_all  # noqa: PLC0415

    print("=== 成果物の採点 ===")
    print("シナリオ | 結果 | 採点 | 落ちた検査")
    for row in run_all():
        score = row["score"]
        print(f"{row['case'].name} | {row['outcome']} | "
              f"{score['passed']}/{score['total']} | "
              f"{'／'.join(score['missing']) or '（なし）'}")


if __name__ == "__main__":
    main()
