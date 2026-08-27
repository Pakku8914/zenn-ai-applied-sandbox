#!/usr/bin/env python3
"""Dockerfile を静的に検査する（セッション7）。

  docker compose exec app python src/session07/lint_image.py Dockerfile
  docker compose exec app python src/session07/lint_image.py src/session07/Dockerfile.slim
  docker compose exec app python src/session07/lint_image.py \
      --allow-weights src/session07/Dockerfile.baked

問題が1件でもあれば終了コード 1 を返す（CI に載せられる形）。
`--allow-weights` は「重みをイメージに焼くのは意図どおり」と宣言するスイッチ。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.session07.imageplan import lint_dockerfile  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Dockerfile の静的検査")
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--allow-weights", action="store_true",
                        help="重みをイメージに入れることを許可する（方式①）")
    args = parser.parse_args()

    total = 0
    for raw in args.paths:
        path = Path(raw)
        if not path.exists():
            print(f"=== {raw} ===")
            print("  ファイルがありません")
            total += 1
            continue
        findings = lint_dockerfile(path.read_text(encoding="utf-8"),
                                  allow_weights=args.allow_weights)
        print(f"=== {raw} ===")
        if not findings:
            print("  問題は見つかりませんでした")
        for finding in findings:
            print(f"  {finding}")
        total += len(findings)

    print(f"\n合計 {total} 件")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
