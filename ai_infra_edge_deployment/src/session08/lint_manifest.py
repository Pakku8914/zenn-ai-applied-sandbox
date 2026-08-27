#!/usr/bin/env python3
"""推論マニフェストを検査する CLI（セッション8）。

クラスタも kubectl も要らない。終了コードで判定できるので CI に置ける。

    python src/session08/lint_manifest.py k8s/inference-deployment.yaml
    python src/session08/lint_manifest.py --explain k8s/inference-deployment.yaml
    python src/session08/lint_manifest.py --strict src/session08/bad-probes.yaml

終了コード: エラーがあれば 1、なければ 0（`--strict` を付けると警告でも 1）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.session08.budget import Overhead  # noqa: E402
from src.session08.manifest import (  # noqa: E402
    ReviewInputs, explain, load_docs, review_docs,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="推論ワークロード向けの Kubernetes マニフェスト検査")
    parser.add_argument("files", nargs="+", help="検査するマニフェスト（YAML）")
    parser.add_argument("--explain", action="store_true",
                        help="数字の内訳（メモリ要求・起動と停止の予算）も表示する")
    parser.add_argument("--strict", action="store_true",
                        help="警告でも失敗させる")
    parser.add_argument("--max-tokens", type=int, default=512,
                        help="1リクエストで許す最長の生成トークン数（既定 512）")
    parser.add_argument("--fixed-overhead-mib", type=float, default=256.0,
                        help="メモリ要求に足す固定の上乗せ（既定 256）")
    parser.add_argument("--margin", type=float, default=0.20,
                        help="重み＋KVキャッシュに対する余裕（既定 0.20）")
    args = parser.parse_args(argv)

    inputs = ReviewInputs(
        max_tokens=args.max_tokens,
        overhead=Overhead(margin=args.margin, fixed_mib=args.fixed_overhead_mib))

    errors = warnings = 0
    for path in args.files:
        print(f"=== {path} ===")
        reviews = review_docs(load_docs(path), inputs)
        if not reviews:
            print("  検査対象のワークロード（Deployment / StatefulSet）がありません")
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
