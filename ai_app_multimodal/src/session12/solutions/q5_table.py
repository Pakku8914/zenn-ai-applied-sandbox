"""問題5：設定ごとの CER を Markdown の比較表にする。加重 CER（厳密）が最も小さい行に ◎ を付ける。

    docker compose exec api python -m src.session12.solutions.q5_table                 # small・int8 の beam 1 と 5
    docker compose exec api python -m src.session12.solutions.q5_table --beams 1 5 --models small base

同じ CER なら beam の小さい（＝速い）設定を選ぶ。表は out/s12/cer_table.md にも書く。
"""

from __future__ import annotations

import argparse
import asyncio
import itertools

from src.session12 import eval_cer
from src.session12.eval_extract import OUT

HEADER = [
    "| 選択 | model | compute | beam | 加重(厳密) | 加重(ゆれ吸収) | 平均(厳密) | 平均(ゆれ吸収) |",
    "| :-: | :-- | :-- | --: | --: | --: | --: | --: |",
]


def markdown_table(rows: list[dict]) -> str:
    ordered = sorted(rows, key=lambda r: (r["cer_weighted"], r["beam"]))
    lines = list(HEADER)
    for n, r in enumerate(ordered):
        mark = "◎" if n == 0 else ""
        lines.append(f"| {mark} | {r['model']} | {r['compute_type']} | {r['beam']} | {r['cer_weighted']:.3f}"
                     f" | {r['cer_weighted_relaxed']:.3f} | {r['cer_mean']:.3f} | {r['cer_mean_relaxed']:.3f} |")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="CER の比較表を作る")
    p.add_argument("--models", nargs="+", default=["small"])
    p.add_argument("--beams", nargs="+", type=int, default=[1, 5])
    a = p.parse_args()
    clips = asyncio.run(eval_cer.synthesize_all(eval_cer.SENTENCES))
    rows = [eval_cer.evaluate_config(clips, m, "int8", b, 2) for m, b in itertools.product(a.models, a.beams)]
    table = markdown_table(rows)
    print(table)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "cer_table.md").write_text(table + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
