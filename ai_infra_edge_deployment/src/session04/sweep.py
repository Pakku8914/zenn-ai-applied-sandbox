#!/usr/bin/env python3
"""同時実行を振って飽和点を探し、引き継げるレポートを書き出す（セッション4）。

    # 測る（設定を変えるたびに --label を変える）
    python src/session04/sweep.py --label np2 --concurrency 1 2 4 8

    # 設定変更の前後を比べる
    python src/session04/sweep.py --compare np1 np2

出力:
    reports/sweep_{label}.json   機械が読む用
    reports/sweep_{label}.md     人に渡す用（測定条件つき）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from infrakit.client import LlamaClient  # noqa: E402
from infrakit.load import run_load  # noqa: E402
from src.session04.serving_config import (  # noqa: E402
    SweepRow, find_saturation, markdown_table, queue_wait_ms,
)
from tools.prompts import with_shared_prefix  # noqa: E402

REPORTS = Path(__file__).resolve().parents[2] / "reports"


def server_conditions(client: LlamaClient) -> dict:
    """測定条件をサーバから取る。**条件の書かれていない数字は比較できない。**"""
    props = client.props()
    settings = props.get("default_generation_settings", {})
    model = props.get("model_path") or settings.get("model", "")
    n_ctx = settings.get("n_ctx") or props.get("n_ctx")
    slots = len(client.slots())
    return {"model": Path(str(model)).name, "n_ctx_per_slot": n_ctx, "slots": slots,
            "total_ctx": (n_ctx * slots) if (n_ctx and slots) else None}


def sweep(client: LlamaClient, concurrency: list[int], max_tokens: int,
          label: str, n_prompts: int) -> tuple[list[SweepRow], dict]:
    prompts = with_shared_prefix()[:n_prompts]
    conditions = {**server_conditions(client), "max_tokens": max_tokens,
                  "requests": len(prompts)}
    rows: list[SweepRow] = []
    for c in concurrency:
        report = run_load(client, prompts, concurrency=c, max_tokens=max_tokens,
                          label=f"sweep_{label}_c{c}", conditions=conditions)
        report.to_json()
        if report.errors:
            print(f"エラーが {report.errors} 件ありました（並列 {c}）")
        rows.append(SweepRow(c, report.ttft["p50"], report.total["p50"],
                             report.throughput_tps))
        print(report.summary())
    return rows, conditions


def write_report(rows: list[SweepRow], conditions: dict, label: str) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    payload = {"label": label, "conditions": conditions,
               "saturation_at": find_saturation(rows),
               "rows": [{"concurrency": r.concurrency, "ttft_p50_ms": r.ttft_p50_ms,
                         "total_p50_ms": r.total_p50_ms,
                         "throughput_tps": r.throughput_tps} for r in rows]}
    (REPORTS / f"sweep_{label}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    body = (f"# 同時実行スイープ: {label}\n\n"
            + markdown_table(rows, conditions) + "\n")
    (REPORTS / f"sweep_{label}.md").write_text(body, encoding="utf-8")
    print(f"\n-> reports/sweep_{label}.json / reports/sweep_{label}.md")


def load_rows(label: str) -> tuple[list[SweepRow], dict]:
    data = json.loads((REPORTS / f"sweep_{label}.json").read_text(encoding="utf-8"))
    rows = [SweepRow(r["concurrency"], r["ttft_p50_ms"], r["total_p50_ms"],
                     r["throughput_tps"]) for r in data["rows"]]
    return rows, data["conditions"]


def compare(before_label: str, after_label: str) -> None:
    """設定変更の前後を1つの表にする。これが引き継げる成果物になる。"""
    before, cond_b = load_rows(before_label)
    after, cond_a = load_rows(after_label)
    print(f"変更前 ({before_label}): {cond_b}")
    print(f"変更後 ({after_label}): {cond_a}\n")
    print("| 並列 | TTFT p50 前 | TTFT p50 後 | tok/s 前 | tok/s 後 |")
    print("| --: | --: | --: | --: | --: |")
    after_by_c = {r.concurrency: r for r in after}
    for r in sorted(before, key=lambda x: x.concurrency):
        a = after_by_c.get(r.concurrency)
        if a is None:
            continue
        print(f"| {r.concurrency} | {r.ttft_p50_ms:.0f} ms | {a.ttft_p50_ms:.0f} ms | "
              f"{r.throughput_tps:.1f} | {a.throughput_tps:.1f} |")
    print(f"\n飽和点: 変更前 {find_saturation(before)} / 変更後 {find_saturation(after)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, nargs="+", default=[1, 2, 4])
    ap.add_argument("--max-tokens", type=int, default=24)
    ap.add_argument("--prompts", type=int, default=20, help="使うプロンプト件数")
    ap.add_argument("--label", default="default")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    args = ap.parse_args()

    if args.compare:
        compare(*args.compare)
        return

    client = LlamaClient()
    if not client.health():
        print("推論サーバに接続できません。`docker compose up -d llama` を実行してください。")
        sys.exit(1)

    rows, conditions = sweep(client, args.concurrency, args.max_tokens,
                             args.label, args.prompts)
    write_report(rows, conditions, args.label)

    base = sorted(rows, key=lambda r: r.concurrency)[0]
    worst = sorted(rows, key=lambda r: r.concurrency)[-1]
    point = find_saturation(rows)
    print(f"\n飽和点: {point if point is not None else '検出されず（刻みを細かくしてください）'}")
    print(f"最大同時実行でのキュー待ち（近似）: "
          f"{queue_wait_ms(worst.ttft_p50_ms, base.ttft_p50_ms):.0f} ms")


if __name__ == "__main__":
    main()
