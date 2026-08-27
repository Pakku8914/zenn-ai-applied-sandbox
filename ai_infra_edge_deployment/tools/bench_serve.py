#!/usr/bin/env python3
"""推論サーバのベンチマーク（セッション2・3・4の実測値の出典）。

  python tools/bench_serve.py                       # 既定（並列1と2）
  python tools/bench_serve.py --concurrency 1 2 4 8 # 飽和点を探す
  python tools/bench_serve.py --no-warmup           # ウォームアップ無しの跳ねを見る
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrakit.client import LlamaClient  # noqa: E402
from infrakit.load import run_load  # noqa: E402
from tools.prompts import with_shared_prefix  # noqa: E402

REPORTS = Path(__file__).resolve().parent.parent / "reports"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, nargs="+", default=[1, 2])
    ap.add_argument("--max-tokens", type=int, default=48)
    ap.add_argument("--no-warmup", action="store_true")
    ap.add_argument("--label-prefix", default="serve")
    args = ap.parse_args()

    client = LlamaClient()
    if not client.health():
        print("推論サーバに接続できません。`docker compose up -d` で llama を起動してください。")
        sys.exit(1)

    props = client.props()
    model_path = props.get("model_path") or props.get("default_generation_settings", {}).get("model", "")
    n_ctx = props.get("default_generation_settings", {}).get("n_ctx") or props.get("n_ctx")
    print("=== サーバ設定 ===")
    print(f"モデル       : {Path(str(model_path)).name}")
    print(f"コンテキスト : {n_ctx}")
    print(f"スロット数   : {len(client.slots()) or '不明'}")

    prompts = with_shared_prefix()
    reports = []
    print(f"\n=== 負荷試験（max_tokens={args.max_tokens}"
          f"{' / ウォームアップ無し' if args.no_warmup else ''}）===")
    for concurrency in args.concurrency:
        report = run_load(client, prompts, concurrency=concurrency,
                          max_tokens=args.max_tokens,
                          warmup=0 if args.no_warmup else 2,
                          label=f"{args.label_prefix}_c{concurrency}"
                                f"{'_nowarm' if args.no_warmup else ''}",
                          conditions={"model": Path(str(model_path)).name, "n_ctx": n_ctx,
                                      "slots": len(client.slots())})
        print(report.summary())
        report.to_json()
        reports.append(report)

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"{args.label_prefix}_summary.json").write_text(
        json.dumps([{"label": r.label, "concurrency": r.concurrency, "ttft": r.ttft,
                     "total": r.total, "tps": r.throughput_tps, "rps": r.throughput_rps,
                     "errors": r.errors} for r in reports],
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n-> reports/{args.label_prefix}_summary.json")


if __name__ == "__main__":
    main()
