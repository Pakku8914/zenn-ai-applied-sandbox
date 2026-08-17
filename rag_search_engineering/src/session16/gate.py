#!/usr/bin/env python3
"""切り替えの合格判定（ゲート）。

「新しい方が良さそう」ではなく、事前に決めた合格ラインで判定する。
使う数値は本書がすでに測ったもの（tools/eval_matrix.py・tools/bench_rerank.py の出力）。
2026-08-15 実測 / aarch64 / CPU 2コア / メモリ 5.8GB / Python 3.12.13。

    python src/session16/gate.py
"""

from __future__ import annotations

# 現行（基準線）
BASELINE = {"name": "現行 dense / fixed", "recall10": 0.783, "added_ms": 0.0}

# 候補。added_ms は現行に上乗せされる検索時間の中央値
CANDIDATES = [
    {"name": "候補A dense / heading（チャンク方式の変更）", "recall10": 0.747, "added_ms": 0.0},
    {"name": "候補B dense -> rerank（候補50）", "recall10": 0.818, "added_ms": 1571.0},
    {"name": "候補C dense -> rerank（候補20）", "recall10": 0.798, "added_ms": 709.0},
]


def judge(candidate: dict, budget_ms: float, baseline: dict = BASELINE) -> dict:
    """精度とレイテンシの両方を満たしたときだけ合格にする。"""
    delta = round(candidate["recall10"] - baseline["recall10"], 3)
    accuracy_ok = delta >= 0.0
    latency_ok = candidate["added_ms"] <= budget_ms
    return {
        "name": candidate["name"],
        "delta": delta,
        "added_ms": candidate["added_ms"],
        "accuracy_ok": accuracy_ok,
        "latency_ok": latency_ok,
        "passed": accuracy_ok and latency_ok,
    }


def run(budget_ms: float) -> list[dict]:
    return [judge(c, budget_ms) for c in CANDIDATES]


def adopt(results: list[dict]) -> str | None:
    """合格した候補のうち、最も精度が高いものを採用する。"""
    passed = [r for r in results if r["passed"]]
    if not passed:
        return None
    return max(passed, key=lambda r: r["delta"])["name"]


def main() -> None:
    for budget in (500.0, 2000.0):
        print(f"=== レイテンシ予算 {budget:.0f} ms（基準線 Recall@10={BASELINE['recall10']}）===")
        print("  候補                                      Recall差   追加ms  精度  遅延  総合")
        results = run(budget)
        for r in results:
            print(f"  {r['name']:<40} {r['delta']:+.3f} {r['added_ms']:>8.0f}"
                  f"   {'OK' if r['accuracy_ok'] else 'NG'}    "
                  f"{'OK' if r['latency_ok'] else 'NG'}   "
                  f"{'合格' if r['passed'] else '見送り'}")
        print(f"  採用: {adopt(results) or '（なし。現行を維持する）'}\n")

    print("同じ候補でも、予算が変われば判定が変わる。")
    print("先に予算と合格ラインを決めてから測ること（測ってから線を引くと必ず通る）。")


if __name__ == "__main__":
    main()
