#!/usr/bin/env python3
"""モデル配布の計画を表にして出力する（セッション7）。

  docker compose exec app python src/session07/plan.py
  docker compose exec app python src/session07/plan.py --quant f16
  docker compose exec app python src/session07/plan.py --registry-mbps 30 \
      --object-store-mbps 200

出力は `reports/session07_delivery.md` にも書き出す（引き継げる成果物）。
**時間はすべて見積りである。** 帯域・ディスク・プロセス起動時間は自分の環境で
測った値に置き換えて使うこと。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.session07.imageplan import (  # noqa: E402
    GGUF_MB, APP_IMAGE_MB, Assumptions, summary_report,
)

SANDBOX = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description="モデル配布の計画を出力する")
    parser.add_argument("--quant", default="q4_k_m", choices=sorted(GGUF_MB))
    parser.add_argument("--replicas", type=int, default=10)
    parser.add_argument("--app-mb", type=float, default=APP_IMAGE_MB)
    parser.add_argument("--registry-mbps", type=float, default=100.0)
    parser.add_argument("--object-store-mbps", type=float, default=100.0)
    parser.add_argument("--disk-read-mbps", type=float, default=284.0)
    parser.add_argument("--process-start-ms", type=float, default=300.0)
    parser.add_argument("--warmup-ms", type=float, default=500.0)
    parser.add_argument("--out", default="reports/session07_delivery.md")
    args = parser.parse_args()

    assumptions = Assumptions(
        registry_mbps=args.registry_mbps,
        object_store_mbps=args.object_store_mbps,
        disk_read_mbps=args.disk_read_mbps,
        process_start_ms=args.process_start_ms,
        warmup_ms=args.warmup_ms,
    )
    report = summary_report(quant=args.quant, assumptions=assumptions,
                           replicas=args.replicas, app_mb=args.app_mb)
    print(report)

    out = SANDBOX / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report + "\n", encoding="utf-8")
    print(f"書き出しました: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
