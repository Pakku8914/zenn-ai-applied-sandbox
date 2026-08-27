"""負荷生成と集計（セッション2・4の参照実装）。

測定条件を必ずレポートに含める。条件の書かれていない数字は比較できない。
"""

from __future__ import annotations

import json
import statistics
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPORTS = Path(__file__).resolve().parent.parent / "reports"


def percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "max": 0.0}
    s = sorted(values)
    return {
        "p50": statistics.median(s),
        # 20件未満で p95 を出しても意味がないが、値は返す（章で件数の必要性を扱う）
        "p95": s[max(int(len(s) * 0.95) - 1, 0)],
        "max": s[-1],
    }


@dataclass
class LoadReport:
    label: str
    n: int = 0
    concurrency: int = 1
    ttft: dict[str, float] = field(default_factory=dict)
    total: dict[str, float] = field(default_factory=dict)
    tpot: dict[str, float] = field(default_factory=dict)
    throughput_rps: float = 0.0
    throughput_tps: float = 0.0
    errors: int = 0
    conditions: dict = field(default_factory=dict)

    def to_json(self, path: str | Path | None = None) -> Path:
        p = Path(path) if path else REPORTS / f"load_{self.label}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    def summary(self) -> str:
        return (f"{self.label:<26} n={self.n:>3} 並列={self.concurrency:>2} "
                f"TTFT p50={self.ttft.get('p50', 0):>7.0f}ms p95={self.ttft.get('p95', 0):>7.0f}ms "
                f"総時間 p50={self.total.get('p50', 0):>7.0f}ms "
                f"{self.throughput_tps:>6.1f} tok/s エラー={self.errors}")


def run_load(client, prompts: list[str], concurrency: int = 1, repeats: int = 1,
             max_tokens: int = 64, warmup: int = 2, label: str = "",
             conditions: dict | None = None) -> LoadReport:
    """プロンプト集を指定の同時実行数で流す。

    warmup を 0 にすると初回のモデルロードとページキャッシュの影響で数字が跳ねる
    （セッション2でその差を実測する）。
    """
    import time

    for i in range(warmup):
        client.generate(prompts[i % len(prompts)], max_tokens=8)

    jobs = [prompts[i % len(prompts)] for i in range(len(prompts) * repeats)]
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(lambda p: client.generate(p, max_tokens=max_tokens), jobs))
    elapsed = time.perf_counter() - started

    ok = [r for r in results if r.ok]
    report = LoadReport(
        label=label or f"c{concurrency}",
        n=len(results), concurrency=concurrency,
        ttft=percentiles([r.ttft_ms for r in ok]),
        total=percentiles([r.total_ms for r in ok]),
        tpot=percentiles([r.tpot_ms for r in ok]),
        throughput_rps=len(ok) / elapsed if elapsed else 0.0,
        throughput_tps=sum(r.tokens_out for r in ok) / elapsed if elapsed else 0.0,
        errors=len(results) - len(ok),
        conditions={"max_tokens": max_tokens, "warmup": warmup, "repeats": repeats,
                    **(conditions or {})},
    )
    return report
