#!/usr/bin/env python3
"""容量計画を出す CLI（セッション9）。

推論サーバもクラスタも要らない。**入力を変えて何度でも数え直せる**ことが要点で、
「前提が変わったら数え直す」を手作業にしないための道具である。

    python src/session09/plan.py                          # 既定の前提
    python src/session09/plan.py --lag                    # 遅れの内訳だけ
    python src/session09/plan.py --weights-mib 4700       # 8B 級に載せ替えたら
    python src/session09/plan.py --out reports/capacity_plan.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.session08.budget import BAKED, FETCH, VOLUME  # noqa: E402
from src.session09.scaling import Slo, lag_for, plan_capacity  # noqa: E402

METHODS = {"fetch": FETCH, "volume": VOLUME, "baked": BAKED}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="推論サービスの容量計画")
    parser.add_argument("--peak-rps", type=float, default=5.0)
    parser.add_argument("--baseline-rps", type=float, default=0.5)
    parser.add_argument("--ramp", type=float, default=0.02,
                        help="立ち上がりの傾き rps/s（既定 0.02）")
    parser.add_argument("--headroom", type=float, default=0.30)
    parser.add_argument("--slots", type=int, default=2, help="-np に渡す値")
    parser.add_argument("--ttft-p95-slo", type=float, default=1000.0)
    parser.add_argument("--total-p95-slo", type=float, default=3000.0)
    parser.add_argument("--weights-mib", type=float, default=None,
                        help="重みのサイズ MiB（既定は Q4_K_M の 379.4）")
    parser.add_argument("--method", choices=sorted(METHODS), default="fetch",
                        help="重みの配り方（セッション7の3方式）")
    parser.add_argument("--stabilization", type=float, default=0.0,
                        help="scaleUp の安定化ウィンドウ（秒）")
    parser.add_argument("--title", default="みなと商事 ヘルプデスク回答 API")
    parser.add_argument("--lag", action="store_true", help="遅れの内訳だけ表示する")
    parser.add_argument("--out", help="Markdown を書き出すパス")
    args = parser.parse_args(argv)

    lag = lag_for(METHODS[args.method], args.weights_mib,
                  stabilization_s=args.stabilization)
    plan = plan_capacity(peak_rps=args.peak_rps, baseline_rps=args.baseline_rps,
                         ramp_rps_per_s=args.ramp, headroom=args.headroom,
                         slots=args.slots, lag=lag,
                         slo=Slo(args.ttft_p95_slo, args.total_p95_slo))

    if args.lag:
        print(lag.explain())
        print(f"  minReplicas を 0 にすると、最初の利用者はこの {lag.total_s:.1f} 秒"
              f"（TTFT の SLO の {plan.slo_multiple:.1f} 倍）を待つ")
        return 0

    body = plan.markdown(args.title)
    print(body)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body + "\n", encoding="utf-8")
        print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
