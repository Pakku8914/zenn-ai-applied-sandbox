#!/usr/bin/env python3
"""HPA を検査する CLI（セッション9）。

クラスタも kubectl も要らない。終了コードで判定できるので CI に置ける。

    python src/session09/lint_hpa.py k8s/hpa.yaml
    python src/session09/lint_hpa.py --plan --explain k8s/hpa.yaml k8s/inference-deployment.yaml
    python src/session09/lint_hpa.py --plan src/session09/bad-hpa.yaml k8s/inference-deployment.yaml

**Deployment のマニフェストも一緒に渡すこと。** そうしないと
`scaleTargetRef` が実在するかを確かめられない（HPA 単独では検証できない）。

終了コード: エラーがあれば 1、なければ 0（`--strict` を付けると警告でも 1）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.session08.budget import FETCH  # noqa: E402
from src.session09.hpa_review import (  # noqa: E402
    explain, load_docs, review_docs, workload_names,
)
from src.session09.scaling import lag_for, plan_capacity  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="推論ワークロード向けの HorizontalPodAutoscaler 検査")
    parser.add_argument("files", nargs="+", help="検査するマニフェスト（YAML）")
    parser.add_argument("--explain", action="store_true",
                        help="指標・behavior・容量計画の内訳も表示する")
    parser.add_argument("--strict", action="store_true", help="警告でも失敗させる")
    parser.add_argument("--plan", action="store_true",
                        help="容量計画と突き合わせる（下限・上限・しきい値）")
    parser.add_argument("--peak-rps", type=float, default=5.0,
                        help="ピークのリクエスト率（既定 5.0）")
    parser.add_argument("--baseline-rps", type=float, default=0.5,
                        help="平常時のリクエスト率（既定 0.5）")
    parser.add_argument("--ramp", type=float, default=0.02,
                        help="立ち上がりの傾き rps/s（既定 0.02）")
    parser.add_argument("--headroom", type=float, default=0.30,
                        help="1インスタンスに残す余裕（既定 0.30）")
    parser.add_argument("--weights-mib", type=float, default=None,
                        help="重みのサイズ MiB（既定は Q4_K_M の 379.4）")
    args = parser.parse_args(argv)

    plan = None
    if args.plan:
        plan = plan_capacity(peak_rps=args.peak_rps, baseline_rps=args.baseline_rps,
                             ramp_rps_per_s=args.ramp, headroom=args.headroom,
                             lag=lag_for(FETCH, args.weights_mib))
        print(f"容量計画: ピーク {plan.peak_rps:.2f} rps → {plan.peak_replicas} 本 / "
              f"minReplicas {plan.min_replicas} / maxReplicas {plan.max_replicas} / "
              f"キュー長 {plan.target_queue_len:.1f} 件/本 / "
              f"スケールの遅れ {plan.lag.total_s:.1f} 秒")
        print()

    loaded = [(path, load_docs(path)) for path in args.files]
    known = workload_names([doc for _, docs in loaded for doc in docs]) or None

    errors = warnings = 0
    for path, docs in loaded:
        print(f"=== {path} ===")
        reviews = review_docs(docs, known=known, plan=plan)
        if not reviews:
            print("  検査対象の HorizontalPodAutoscaler がありません")
            print()
            continue
        for review in reviews:
            if args.explain:
                print(explain(review))
            for finding in review.findings:
                print(f"  {finding}")
            errors += len(review.errors)
            warnings += len(review.warnings)
        print()

    print(f"検出: エラー {errors} 件 / 警告 {warnings} 件")
    if warnings and not errors:
        print("警告は「理由を書けるなら残してよい」ものです。"
              "残す判断をした理由をマニフェストのコメントに書いてください。")
    return 1 if (errors or (args.strict and warnings)) else 0


if __name__ == "__main__":
    sys.exit(main())
