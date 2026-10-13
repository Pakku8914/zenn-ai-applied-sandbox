"""3つの評価をまとめて回し、基準（baseline）と比べる（セッション12）。合否に使うのは決定的な指標だけ。

    docker compose exec api python -m src.session12.evaluate --update-baseline   # 基準を作る
    docker compose exec api python -m src.session12.evaluate                     # 基準と比べる（悪化があれば終了コード 1）
    docker compose exec api python -m src.session12.evaluate --skip-latency      # 遅延を測らない（速い）

終了コード：0 回帰なし／1 回帰あり／2 基準がない。遅延（環境依存）は表示するだけで、終了コードに影響しない。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass

from kondate.settings import get_settings
from src.session12 import eval_cer, eval_extract, eval_latency
from src.session12.eval_extract import OUT, write_json
from src.session12.matching import summarize

REPORT = OUT / "report.json"
BASELINE = OUT / "baseline.json"


@dataclass(frozen=True)
class Rule:
    better: str                  # "higher"（大きいほど良い）か "lower"（小さいほど良い）
    tolerance: float             # 基準からこの幅を超えて悪くなったら回帰
    limit: float | None = None   # 基準に関係なく、これより悪ければ失敗


# 合否に使う指標。ここに無い指標（遅延）は、どれだけ変わっても回帰にしない
RULES = {
    "extraction.precision": Rule("higher", 0.0),
    "extraction.recall": Rule("higher", 0.0),
    "extraction.field_accuracy": Rule("higher", 0.0),
    "extraction.exact_match_rate": Rule("higher", 0.0),
    "cer.weighted_strict": Rule("lower", 0.01, limit=0.15),
    "cer.weighted_relaxed": Rule("lower", 0.01, limit=0.15),
}


def build_report(extraction: dict, cer_row: dict, latency: dict | None) -> dict:
    deterministic = {f"extraction.{k}": extraction[k]
                     for k in ("precision", "recall", "field_accuracy", "exact_match_rate")}
    deterministic["cer.weighted_strict"] = cer_row["cer_weighted"]
    deterministic["cer.weighted_relaxed"] = cer_row["cer_weighted_relaxed"]
    environment = {}
    for name, s in (latency or {}).items():
        environment[f"latency.{name}.p50_ms"] = s["p50_ms"]
        environment[f"latency.{name}.p95_ms"] = s["p95_ms"]
    return {"deterministic": deterministic, "environment": environment}


def find_regressions(current: dict, baseline: dict, rules: dict[str, Rule] = RULES) -> list[str]:
    now, before = current["deterministic"], baseline["deterministic"]
    found = []
    for key, rule in rules.items():
        if key not in now:
            found.append(f"{key}：今回の結果にありません")
            continue
        value = now[key]
        sign = 1 if rule.better == "higher" else -1     # 「良くなった向き」を正にそろえる
        if rule.limit is not None and sign * (value - rule.limit) < 0:
            word = "下限 {} を下回りました" if rule.better == "higher" else "上限 {} を超えました"
            found.append(f"{key}：{value} が{word.format(rule.limit)}")
        old = before.get(key)
        if old is not None and round(sign * (value - old), 6) < -rule.tolerance:
            found.append(f"{key}：{old} → {value}（悪化。許容幅 {rule.tolerance}）")
    return found


def latency_notes(current: dict, baseline: dict) -> list[str]:
    before = baseline.get("environment", {})
    return [f"{key}：{before[key]} → {value}（参考。合否に使わない）" if key in before else f"{key}：{value}（参考）"
            for key, value in current["environment"].items()]


def show(report: dict) -> None:
    for key, value in report["deterministic"].items():
        print(f"[決定的] {key} = {value}")
    for key, value in report["environment"].items():
        print(f"[環境依存] {key} = {value}")


def main() -> int:
    p = argparse.ArgumentParser(description="評価をまとめて回し、基準と比べる")
    p.add_argument("--update-baseline", action="store_true", help="いまの結果を基準として保存する")
    p.add_argument("--skip-latency", action="store_true", help="遅延を測らない")
    p.add_argument("--repeat", type=int, default=eval_latency.MIN_FOR_P95)
    a = p.parse_args()
    s = get_settings()

    results = asyncio.run(eval_extract.run_cases(eval_extract.mock_cases()))
    extraction = summarize(score for score, _ in results)
    clips = asyncio.run(eval_cer.synthesize_all(eval_cer.SENTENCES))
    cer_row = eval_cer.evaluate_config(clips, s.whisper_model, s.whisper_compute_type, s.whisper_beam_size,
                                       s.whisper_cpu_threads)
    latency = None if a.skip_latency else asyncio.run(eval_latency.run(eval_latency.TARGETS, a.repeat))
    report = build_report(extraction, cer_row, latency)
    write_json(REPORT, report)
    show(report)
    print(f"→ {REPORT}")

    if a.update_baseline:
        write_json(BASELINE, report)
        print(f"基準を保存しました：{BASELINE}")
        return 0
    if not BASELINE.exists():
        print("基準がありません。先に --update-baseline で作ってください")
        return 2
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    for line in latency_notes(report, baseline):
        print(line)
    found = find_regressions(report, baseline)
    for line in found:
        print(f"回帰：{line}")
    print(f"回帰なし（決定的な指標 {len(RULES)} 件を基準と比較）" if not found else f"回帰 {len(found)} 件")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
