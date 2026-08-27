#!/usr/bin/env python3
"""容量計画：同時実行数と必要インスタンス数を数える（中間プロジェクト1）。

推論サーバもクラスタも要らない。掛け算と割り算しかないが、道具にしてあるのは
**前提が変わったときに手で数え直すと必ずどこかを直し忘れる**からである。

数え方は次の順で、順序が方針そのものである。

    ① SLO を満たす動作点を選ぶ（rps が最大の点ではない）
    ② その点の rps にヘッドルームを掛ける  → 1インスタンスの能力
    ③ ピーク ÷ 1インスタンスの能力（切り上げ） → 必要な本数
    ④ 重み ＋ KVキャッシュ ＋ 上乗せ         → 1本あたりのメモリ要求

**必ず切り上げる。** 2.53 本を 2 本に切り下げると、ピーク時に確実に飽和する。
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.session08.budget import (  # noqa: E402
    MemoryBudget, Overhead, budget_for, grace_required_s, max_request_seconds,
)
from src.mid01.slo import (  # noqa: E402
    DEFAULT_SLOS, MAX_TOKENS, MEASURED, Point, Slo, satisfies, saturation_of,
)

DEFAULT_TITLE = "みなと商事 ヘルプデスク回答 API"
DEFAULT_MODEL_FILE = "qwen05b-q4_k_m.gguf"
PRESTOP_S = 15.0
"""`lifecycle.preStop` の待ち（セッション8のマニフェストの値）。"""


@dataclass(frozen=True)
class Demand:
    """需要（前提値。要件として与えられる値であり実測ではない）。"""

    peak_rps: float
    baseline_rps: float


@dataclass(frozen=True)
class Plan:
    """容量計画。すべての数字が入力から導かれる。"""

    demand: Demand
    point: Point
    slots: int
    total_ctx: int
    headroom: float
    memory: MemoryBudget
    model_file: str = DEFAULT_MODEL_FILE
    title: str = DEFAULT_TITLE
    max_tokens: int = MAX_TOKENS

    # --- 1インスタンスの能力 ------------------------------------------------
    @property
    def per_instance_rps(self) -> float:
        """安全に任せられる rps。測った rps をそのまま使ってはいけない。"""
        return self.point.throughput_rps * (1.0 - self.headroom)

    # --- 本数 ---------------------------------------------------------------
    @property
    def peak_instances(self) -> int:
        return math.ceil(self.demand.peak_rps / self.per_instance_rps)

    @property
    def baseline_instances(self) -> int:
        if self.demand.baseline_rps <= 0:
            return 0
        return math.ceil(self.demand.baseline_rps / self.per_instance_rps)

    @property
    def total_concurrency(self) -> int:
        """ピーク時にサーバ側で同時に走る本数（＝入口で許す上限の根拠）。"""
        return self.peak_instances * self.slots

    # --- メモリ -------------------------------------------------------------
    @property
    def ctx_per_slot(self) -> int:
        return self.total_ctx // self.slots

    @property
    def memory_per_instance_mib(self) -> int:
        return self.memory.rounded_mib()

    @property
    def total_memory_mib(self) -> int:
        return self.peak_instances * self.memory_per_instance_mib

    # --- 停止の猶予 ---------------------------------------------------------
    @property
    def max_request_s(self) -> float:
        """1リクエストが最長どれだけ走るか（セッション8の式）。"""
        return max_request_seconds(self.max_tokens)

    @property
    def grace_required_s(self) -> float:
        return grace_required_s(PRESTOP_S, self.max_request_s)

    # --- 説明 ---------------------------------------------------------------
    def memory_formula(self) -> str:
        m = self.memory
        return (f"({m.weights_mib:.1f} + {m.kv_mib:.1f}) × "
                f"{1.0 + m.overhead.margin:.2f} + {m.overhead.fixed_mib:.1f} = "
                f"{m.required_mib:.1f} MiB")

    def explain(self) -> str:
        p, d = self.point, self.demand
        return "\n".join([
            f"容量計画（{self.title}）",
            f"  採用した動作点  : 並列 {p.concurrency}（TTFT p95 "
            f"{p.ttft_p95_ms:.0f} ms / 総時間 p95 {p.total_p95_ms:.0f} ms / "
            f"{p.throughput_rps} rps）",
            f"  1インスタンス   : {p.throughput_rps} rps × "
            f"(1 − {self.headroom:.2f}) = {self.per_instance_rps:.2f} rps",
            f"  ピーク {d.peak_rps:.2f} rps : {d.peak_rps:.2f} ÷ "
            f"{self.per_instance_rps:.2f} = "
            f"{d.peak_rps / self.per_instance_rps:.2f} → {self.peak_instances} 本",
            f"  平常 {d.baseline_rps:.2f} rps   : {d.baseline_rps:.2f} ÷ "
            f"{self.per_instance_rps:.2f} = "
            f"{d.baseline_rps / self.per_instance_rps:.2f} → "
            f"{self.baseline_instances} 本",
            f"  同時実行の合計  : {self.peak_instances} 本 × {self.slots} "
            f"スロット = {self.total_concurrency}",
            f"  メモリ / 本     : {self.memory.explain()}",
            f"  メモリ合計      : {self.peak_instances} 本 × "
            f"{self.memory_per_instance_mib} MiB = {self.total_memory_mib} MiB",
        ])

    def markdown(self, slos: tuple[Slo, ...] = DEFAULT_SLOS,
                 points: tuple[Point, ...] = MEASURED) -> str:
        """引き継げる形（Markdown）。**前提と再計算手順を必ず含める。**"""
        d, p, m = self.demand, self.point, self.memory
        saturation = saturation_of(points)
        rows = "\n".join(
            f"| {q.concurrency} | {q.ttft_p95_ms:,.0f} ms | "
            f"{q.total_p95_ms:,.0f} ms | {q.tpot_p50_ms} ms | "
            f"{q.throughput_rps} | {_verdict(q, p, saturation, slos)} |"
            for q in sorted(points, key=lambda x: x.concurrency))
        slo_text = " / ".join(s.describe() for s in slos)
        fastest = max(points, key=lambda x: x.throughput_rps)
        ttft_target = slos[0].target_ms
        doubled = budget_for(self.model_file, self.total_ctx * 2)
        doubled_text = doubled.quantity() if doubled else "再計算が必要"
        return f"""# 容量計画：{self.title}

## 1. 前提（変わったら数え直す入力）

| 入力 | 値 | 出どころ |
| :--- | --: | :--- |
| ピークのリクエスト率 | {d.peak_rps} rps | 前提値（要件） |
| 平常時のリクエスト率 | {d.baseline_rps} rps | 前提値（要件） |
| ヘッドルーム | {self.headroom * 100:.0f}% | 運用の判断（下の理由を参照） |
| 1インスタンスの並列スロット数 | {self.slots} | -np {self.slots} |
| 全体のコンテキスト長 | {self.total_ctx:,} トークン | -c {self.total_ctx}（1スロット {self.ctx_per_slot}） |
| 出力上限 | {self.max_tokens} トークン | SLO 定義と測定条件に一致 |
| SLO | {slo_text} | 01-slo.md |
| 重みのサイズ | {m.weights_mib} MiB | 2026-08-15 実測（{self.model_file}） |

ヘッドルーム {self.headroom * 100:.0f}% の理由: 実測 {p.throughput_rps} rps は理想条件（同じ長さのプロンプト・
ウォームアップ済み・他の負荷なし）での値である。入力長のばらつき、
ロールアウト中に 1 本抜ける状況、測定自体のぶれ（同一条件で 2 倍程度）を
吸収する余白として {self.headroom * 100:.0f}% を取った。20% では入れ替え中に飽和する。

## 2. 動作点（実測から選ぶ）

| 並列 | TTFT p95 | 総時間 p95 | TPOT p50 | rps | SLO |
| --: | --: | --: | --: | --: | :--- |
{rows}

採用理由: SLO を満たす中で最も rps が高い点。rps だけで選ぶと並列 {fastest.concurrency}（{fastest.throughput_rps} rps）に
なるが、その点は TTFT p95 が目標の {fastest.ttft_p95_ms / ttft_target:.1f} 倍で体感が壊れている。
**rps の最大ではなく「SLO を満たす中での最大」を採る。**

## 3. 数え方

| 段 | 計算 | 結果 |
| :--- | :--- | --: |
| 1インスタンスの能力 | {p.throughput_rps} rps × (1 − {self.headroom:.2f}) | {self.per_instance_rps:.2f} rps |
| ピークに必要な本数 | {d.peak_rps:.2f} ÷ {self.per_instance_rps:.2f} = {d.peak_rps / self.per_instance_rps:.2f}（切り上げ） | {self.peak_instances} 本 |
| 平常時に必要な本数 | {d.baseline_rps:.2f} ÷ {self.per_instance_rps:.2f} = {d.baseline_rps / self.per_instance_rps:.2f}（切り上げ） | {self.baseline_instances} 本 |
| 同時実行の合計 | {self.peak_instances} 本 × {self.slots} スロット | {self.total_concurrency} |
| メモリ / 本 | {self.memory_formula()}（64 MiB 単位で切り上げ） | {self.memory.quantity()} |
| メモリ合計（ピーク時） | {self.peak_instances} 本 × {self.memory_per_instance_mib} MiB | {self.total_memory_mib:,} MiB |

切り上げの理由: {d.peak_rps / self.per_instance_rps:.2f} 本を {self.peak_instances - 1} 本に切り下げると、ピーク時に必ず飽和する。
KVキャッシュ {m.kv_mib:.1f} MiB の内訳: 12,288 バイト/トークン × {self.total_ctx:,} トークン。
コンテキストを倍にすると {m.kv_mib * 2:.1f} MiB になり、メモリ要求は {doubled_text} に上がる。

検証環境との差: 本書の検証環境はメモリ 5.8GB・CPU 2 コアで、ゲートウェイと
測定クライアントも同居する。**{self.peak_instances} 本は計画上の数字であり、演習では 1 本しか
立てない。** 計画と検証環境を混同しないこと。

## 4. マニフェストに反映する値

| 対象 | 現在 | 計画 | 根拠 |
| :--- | --: | --: | :--- |
| Deployment の replicas | 2 | {self.peak_instances} | ピーク {d.peak_rps:.2f} ÷ {self.per_instance_rps:.2f} = {d.peak_rps / self.per_instance_rps:.2f} の切り上げ |
| requests.memory / limits.memory | {self.memory.quantity()} | {self.memory.quantity()} | {self.memory_formula()} |
| requests.cpu / limits.cpu | 2 | 2 | -t 2 と揃える（超えると切り替えの分だけ遅くなる） |
| コンテナ引数 -c | {self.total_ctx} | {self.total_ctx} | 1スロット {self.ctx_per_slot}。長い入力は受け入れ判定で断る |
| コンテナ引数 -np | {self.slots} | {self.slots} | 飽和点の手前で実測した点 |
| terminationGracePeriodSeconds | 60 | 60 | preStop {PRESTOP_S:.0f} + 生成の最長 {self.max_request_s:.1f} + 余裕 5 = {self.grace_required_s:.1f} 秒に収まる |
| ゲートウェイの MAX_INFLIGHT | 4 | {self.slots} | 上流の並列スロット数に合わせる |

replicas の変更は 2 → {self.peak_instances} の 1 箇所だけである。**現在の 2 は根拠の無い数字**
だった（セッション8で書いた初期値）。反映後は
src/session08/lint_manifest.py --explain で検査し、エラー 0 件を確認する。

## 5. 前提が変わったときの再計算手順

1. src/session04/sweep.py で同時実行を振って測り直す（1・スロット数・2倍以上）
2. SLO（01-slo.md）を満たす中で最も rps が高い点を動作点に採る
3. その点の rps にヘッドルームを掛け、1インスタンスの能力を出す
4. ピーク ÷ 1インスタンスの能力 を切り上げて本数を出す
5. src/session08/budget.py でメモリ要求を出し直す（重みとコンテキストが変わると動く）
6. マニフェストを直し、src/session08/lint_manifest.py で検査する
7. 01-slo.md の「見直す条件」に該当していないかを確認する
"""


def _verdict(q: Point, adopted: Point, saturation: int | None,
             slos: tuple[Slo, ...]) -> str:
    ok = "満たす" if satisfies(q, slos) else "満たさない"
    if saturation is not None and q.concurrency == saturation:
        return f"{ok}（飽和点）"
    if q.concurrency == adopted.concurrency:
        return f"{ok}（採用）"
    return ok


def plan_for(demand: Demand, point: Point, slots: int = 2,
             total_ctx: int = 2048, headroom: float = 0.30,
             model_file: str = DEFAULT_MODEL_FILE, title: str = DEFAULT_TITLE,
             max_tokens: int = MAX_TOKENS,
             overhead: Overhead | None = None) -> Plan:
    """容量計画を組み立てる。入力の妥当性はここで弾く。"""
    if demand.peak_rps <= 0:
        raise ValueError("peak_rps は正の数を指定してください")
    if demand.baseline_rps < 0:
        raise ValueError("baseline_rps は 0 以上を指定してください")
    if not 0.0 <= headroom < 1.0:
        raise ValueError("headroom は 0 以上 1 未満で指定してください")
    if slots < 1:
        raise ValueError("slots は 1 以上を指定してください")
    if total_ctx < slots:
        raise ValueError("total_ctx は slots 以上を指定してください")
    if point.throughput_rps <= 0:
        raise ValueError("動作点の rps は正の数でなければなりません")
    memory = budget_for(model_file, total_ctx, overhead)
    if memory is None:
        raise ValueError(f"重みのサイズが分からないモデルです: {model_file}")
    return Plan(demand=demand, point=point, slots=slots, total_ctx=total_ctx,
                headroom=headroom, memory=memory, model_file=model_file,
                title=title, max_tokens=max_tokens)


__all__ = ["DEFAULT_MODEL_FILE", "DEFAULT_TITLE", "PRESTOP_S", "Demand", "Plan",
           "plan_for"]
