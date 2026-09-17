"""評価ハーネスを 1 回まわしてレポートを出力する。

    python run_eval.py                 # 記録再生で評価（APIキー不要・無料・毎回同じ結果）
    python run_eval.py --live          # 実 API で評価（APIキー必要）
    python run_eval.py --tag ガードレール  # 特定タグのケースだけ評価
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app import answer
from evalkit.checks import run_rule_checks
from evalkit.client import AnthropicClient, RecordedClient
from evalkit.dataset import filter_by_tag, load_dataset
from evalkit.judge import judge_pointwise
from evalkit.report import CaseResult, render_markdown, summarize

BASE_DIR = Path(__file__).resolve().parent
DATASET = BASE_DIR / "datasets" / "faq_v1.jsonl"
CASSETTE = BASE_DIR / "recordings" / "faq_v1.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="評価ハーネスの実行")
    parser.add_argument("--live", action="store_true", help="実 API を使う（APIキー必要）")
    parser.add_argument("--tag", default=None, help="このタグのケースだけ評価する")
    parser.add_argument("--threshold", type=int, default=4, help="judge の合格しきい値（既定 4）")
    parser.add_argument("--no-judge", action="store_true", help="ルールベース検査だけ実行する")
    args = parser.parse_args()

    cases = load_dataset(DATASET)
    if args.tag:
        cases = filter_by_tag(cases, args.tag)
        if not cases:
            print(f"タグ '{args.tag}' に該当するケースがありません")
            return 1

    if args.live:
        app_client = AnthropicClient()
        judge_client = AnthropicClient()
    else:
        # 記録再生。アプリと judge の応答を同じカセットから読み出す
        app_client = RecordedClient(CASSETTE)
        judge_client = RecordedClient(CASSETTE)

    results: list[CaseResult] = []
    for case in cases:
        response = answer(app_client, case.input)
        checks = run_rule_checks(case, response.text)
        verdict = None
        if not args.no_judge:
            verdict = judge_pointwise(judge_client, case.input, response.text, case.rubric)
        results.append(CaseResult(case=case, response=response, checks=checks, verdict=verdict))

    summary = summarize(results, judge_threshold=args.threshold)
    print(render_markdown(summary, title=f"評価レポート（{'live' if args.live else 'replay'}）"))

    # CI では合格率をそのまま終了コードに反映させる（Session 9 で扱う）
    return 0 if summary.pass_rate == 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
