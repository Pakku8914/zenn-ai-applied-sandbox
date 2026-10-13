"""問題6：閉ループ検査の結果を基準（baseline）として保存し、次回から「基準より悪くなったか」も見る。

    docker compose exec api python -m src.session08.solutions.q6_baseline --update   # 基準を作る
    docker compose exec api python -m src.session08.solutions.q6_baseline            # 基準と比べる
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from src.session08.loopback_check import CASES, Outcome, run_cases

BASELINE = Path("out/s08/loopback_baseline.json")
TOLERANCE = 0.02     # 1文 18 文字なら 1 文字の誤り（0.0556）で引っかかる幅


def to_baseline(outcomes: list[Outcome]) -> dict[str, float]:
    return {o.case.text: o.score for o in outcomes}


def regressions(outcomes: list[Outcome], baseline: dict[str, float], tolerance: float = TOLERANCE) -> list[str]:
    found = []
    for o in outcomes:
        if not o.passed:
            found.append(f"上限超え：{o.case.text}（CER {o.score} > {o.case.max_cer}）")
        before = baseline.get(o.case.text)
        if before is not None and o.score > before + tolerance:
            found.append(f"基準より悪化：{o.case.text}（{before} → {o.score}）")
    return found


def main() -> int:
    p = argparse.ArgumentParser(description="閉ループ検査を基準と比べる")
    p.add_argument("--update", action="store_true", help="いまの結果を基準として保存する")
    a = p.parse_args()

    outcomes = asyncio.run(run_cases(CASES))
    if a.update:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(to_baseline(outcomes), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"基準を保存しました：{BASELINE}（{len(outcomes)} 件）")
        return 0
    if not BASELINE.exists():
        print("基準がありません。先に --update で作ってください")
        return 2
    found = regressions(outcomes, json.loads(BASELINE.read_text(encoding="utf-8")))
    for line in found:
        print(line)
    print("回帰なし" if not found else f"回帰 {len(found)} 件")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
