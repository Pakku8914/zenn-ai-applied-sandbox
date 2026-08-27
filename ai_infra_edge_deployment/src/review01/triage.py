#!/usr/bin/env python3
"""一次切り分け：観測から原因の候補を返す（復習1・問題5）。

判定の順序が方針そのものである。

  1. 条件が揃っているか（セッション2）  → 揃っていなければそこで止める
  2. 入口で断っていないか（セッション5） → 429 は相手が速い / 503 はこちらが手一杯
  3. 時間の分解（セッション4・セッション3）→ キュー待ち / プリフィル / デコード

条件の確認を最後に回すと、比較してはいけない2本のレポートに対して原因を
推定してしまう。**先に「その数字は比べてよいのか」を判定する。**

  docker compose exec app python src/review01/triage.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.session02.metrics import comparable  # noqa: E402
from src.session04.serving_config import Budget, diagnose, queue_wait_ms  # noqa: E402

# `metrics.COMPARE_KEYS` は `n_ctx` を見るが、`sweep.py` が書き出す条件は
# `n_ctx_per_slot` という名前である。**キー名が違えば比較されない**ので、
# 自分のレポートに合わせて明示的に渡す。
COMPARE_KEYS = ("max_tokens", "warmup", "model", "n_ctx_per_slot", "slots")

# 候補ごとの「次にやること」。必ず1つだけにする。2つ同時に動かすと、
# 効いたのがどちらか分からなくなる。
NEXT_ACTION = {
    "比較不能": "条件を揃えて測り直す（揃っていない項目だけを合わせる）",
    "入口・レート制限": "そのキーの rate と burst を、上限スループットの配分から見直す",
    "入口・容量": "max_inflight と max_queue を上流のスロット数に合わせ、期限を付ける",
    "キュー待ち": "同時実行を飽和点の手前まで下げる（`-np` を上げるのは最後）",
    "プリフィル": "入力の長さを削るか、受け入れ判定で長すぎる入力を断る",
    "デコード": "量子化形式を測り直すか、出力トークン数の上限を下げる",
    "目標内": "何もしない。条件つきのレポートを残して次に備える",
}


@dataclass(frozen=True)
class Observation:
    """1回の測定。`conditions` は `LoadReport.conditions` をそのまま入れる。"""

    label: str
    ttft_p50_ms: float
    tpot_p50_ms: float
    total_p50_ms: float = 0.0
    errors: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    conditions: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Finding:
    """原因の候補1件。根拠を持たない候補は報告しない。"""

    label: str
    evidence: str
    next_action: str


def triage(obs: Observation, *, baseline_ttft_ms: float, budget: Budget,
           against: dict | None = None,
           compare_keys: tuple[str, ...] = COMPARE_KEYS) -> list[Finding]:
    """原因の候補を、根拠つきで返す。

    baseline_ttft_ms : **同じプロンプト集を並列1で測った TTFT**。
                       条件の違う数字を渡すと、待ちとプリフィルを誤診する。
    budget           : SLO から決めた目標（TTFT と TPOT）。関数に埋め込まない。
    against          : 比較相手のレポートの `conditions`。None なら条件確認を省く。
    """
    if against is not None:
        gaps = comparable(obs.conditions, against, keys=compare_keys)
        if gaps:
            return [Finding("比較不能",
                            f"条件が揃っていない項目: {', '.join(gaps)}",
                            NEXT_ACTION["比較不能"])]

    findings: list[Finding] = []

    # --- 入口（セッション5）。誰の問題かで分ける -----------------------------
    n429 = obs.status_counts.get("429", 0)
    if n429 > 0:
        findings.append(Finding(
            "入口・レート制限", f"429 が {n429} 件（相手が速い）",
            NEXT_ACTION["入口・レート制限"]))
    n503 = obs.status_counts.get("503", 0)
    if n503 > 0:
        findings.append(Finding(
            "入口・容量", f"503 が {n503} 件（こちらが手一杯）",
            NEXT_ACTION["入口・容量"]))

    # --- 時間の分解（セッション4 の diagnose をそのまま使う）-----------------
    for label in diagnose(obs.ttft_p50_ms, obs.tpot_p50_ms, budget, baseline_ttft_ms):
        if label == "キュー待ち":
            wait = queue_wait_ms(obs.ttft_p50_ms, baseline_ttft_ms)
            evidence = (f"TTFT p50 {obs.ttft_p50_ms:.0f}ms − 基準 "
                        f"{baseline_ttft_ms:.0f}ms = 待ち {wait:.0f}ms"
                        f"（目標 {budget.ttft_ms:.0f}ms）")
        elif label == "プリフィル":
            evidence = (f"TTFT p50 {obs.ttft_p50_ms:.0f}ms が目標 "
                        f"{budget.ttft_ms:.0f}ms を超え、待ちは基準 "
                        f"{baseline_ttft_ms:.0f}ms 以下")
        else:
            evidence = (f"TPOT p50 {obs.tpot_p50_ms:.2f}ms が目標 "
                        f"{budget.tpot_ms:.0f}ms を超えている")
        findings.append(Finding(label, evidence, NEXT_ACTION[label]))

    if not findings:
        findings.append(Finding(
            "目標内",
            f"TTFT p50 {obs.ttft_p50_ms:.0f}ms / TPOT p50 "
            f"{obs.tpot_p50_ms:.2f}ms はどちらも目標内",
            NEXT_ACTION["目標内"]))
    return findings


def report(findings: list[Finding]) -> str:
    """引き継げる形（Markdown の表）で返す。"""
    lines = ["| 候補 | 根拠 | 次にやること |", "| :--- | :--- | :--- |"]
    for f in findings:
        lines.append(f"| {f.label} | {f.evidence} | {f.next_action} |")
    return "\n".join(lines)


# 2026-08-15 実測の数字を使った確認用のケース（aarch64 / CPU 2コア /
# メモリ 5.8GB / Python 3.12.13 / llama.cpp `-t 2`）。
BASE_CONDITIONS = {"max_tokens": 48, "warmup": 2, "model": "qwen05b-q4_k_m.gguf",
                   "n_ctx_per_slot": 1024, "slots": 2}
DEFAULT_BUDGET = Budget(ttft_ms=300.0, tpot_ms=40.0)

# (観測, 基準の TTFT, 目標, 比較相手の条件)
CASES: tuple[tuple[Observation, float, Budget, dict | None], ...] = (
    (Observation("A 条件が違うレポートを比べた", 155.0, 19.19, 1034.0,
                 conditions=BASE_CONDITIONS),
     155.0, DEFAULT_BUDGET, {**BASE_CONDITIONS, "max_tokens": 24}),
    (Observation("B 並列4（スロット数の2倍）の実測", 1772.0, 36.15, 3379.0),
     155.0, DEFAULT_BUDGET, None),
    (Observation("C f16 で TPOT の目標を 20ms にした", 124.0, 26.54, 1353.0),
     124.0, Budget(ttft_ms=300.0, tpot_ms=20.0), None),
    (Observation("D 429 が返っている", 155.0, 19.19, 1034.0, errors=5,
                 status_counts={"429": 5}),
     155.0, DEFAULT_BUDGET, None),
    (Observation("E 503 が返り TTFT も悪化", 1772.0, 36.15, 3379.0, errors=3,
                 status_counts={"503": 3}),
     155.0, DEFAULT_BUDGET, None),
    (Observation("F 並列1・目標内", 155.0, 19.19, 1034.0),
     155.0, DEFAULT_BUDGET, None),
)


if __name__ == "__main__":
    for obs, baseline, budget, against in CASES:
        findings = triage(obs, baseline_ttft_ms=baseline, budget=budget,
                          against=against)
        print(f"### {obs.label}")
        print(f"候補: {' / '.join(f.label for f in findings)}")
        print(report(findings))
        print()
