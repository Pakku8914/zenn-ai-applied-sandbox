#!/usr/bin/env python3
"""ハイブリッド基盤の「系」を1つの入力から数え直す（最終プロジェクト）。

    python src/final/design.py            # 前提から台数・メモリ・単価まで
    python src/final/design.py --trace    # しきい値を振ったときの連鎖
    python src/final/design.py --edge     # エッジ側の予算と OTA の数字

**新しい計算は1つも無い。** セッション9〜16 と中間プロジェクトの計算を、
1つの入力から順につないだだけである。つないだことで初めて見えるのは
「エッジ側のしきい値がクラウド側の台数を決める」という結合である。

数値の3分類（セッション11 からの規律。混ぜてはいけない）:
  ① 実測値   : 本書の測定結果（測定条件つきで引用する）
  ② 物理計算 : 定数から一意に決まるもの（往復の下限・配布時間・KVキャッシュ）
  ③ 前提値   : 読者が入れるもの（件数・ピーク倍率・固定費・しきい値）

金額はすべて**相対単位**である（インスタンス1時間の値段を 1 と置く）。
本書は特定クラウドの価格を書かない（最も速く陳腐化するため）。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, replace
from pathlib import Path

SANDBOX = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SANDBOX))

from infrakit.cost import SelfHosted  # noqa: E402
from src.mid01.capacity import Demand, Plan, plan_for  # noqa: E402
from src.mid01.slo import (  # noqa: E402
    DEFAULT_SLOS, MEASURED, MEASURED_CONDITIONS, Point, operating_point,
)
from src.mid02.hybrid import DEMO_MARGINS, THRESHOLDS, route  # noqa: E402
from src.session11.edge_budget import (  # noqa: E402
    Footprint, MemoryBudget, fits, kv_mb, rtt_floor_ms,
)
from src.session15.fleet import (  # noqa: E402
    CLIENT_TIMEOUT_S, DEVICE_COUNT, FP32_MB, INT8_MB, LINE_MBPS, OBSERVE_HOURS,
    STAGE_FRACTIONS, max_parallel_for_timeout, plan_elapsed_hours, stage_plan,
    transfer_seconds,
)

TITLE = "みなと商事 ハイブリッド推論基盤"

SECONDS_PER_MONTH = 30 * 24 * 3600
"""③ 前提値：1か月を30日として数える（セッション16 と同じ）。"""

HEADROOM = 0.30
"""③ 前提値：1本に任せる rps の余白（セッション9・10 と同じ 30%）。"""

REQUESTS_PER_DEVICE_HOUR = 2.0
"""③ 前提値：端末1台が1時間に出す一次判定の件数。"""

RUNTIME_CLASSIFIER_MB = 50.0
"""③ 前提値：分類器だけの実行時メモリ（セッション11）。"""

RUNTIME_LLM_MB = 150.0
"""③ 前提値：言語モデルの実行時メモリ（セッション11）。"""

GGUF_Q4_K_M_MB = 379.4
"""① 実測：Q4_K_M の重み（2026-08-15）。"""

SEQ_LEN = 2048
"""③ 前提値：想定系列長（セッション11 と同じ）。"""

PRESTOP_S = 15.0
"""③ 前提値：`lifecycle.preStop` の待ち（セッション8 のマニフェスト）。"""

# ③ 前提値：セッション11 の共通端末。数値を変えると章をまたいだ比較が壊れる
DEVICES: dict[str, MemoryBudget] = {
    "端末A": MemoryBudget(total_mb=4096, os_reserved_mb=1024, other_apps_mb=1536),
    "端末B": MemoryBudget(total_mb=2048, os_reserved_mb=768, other_apps_mb=512),
    "端末C": MemoryBudget(total_mb=8192, os_reserved_mb=1024, other_apps_mb=1024),
    "端末D": MemoryBudget(total_mb=1024, os_reserved_mb=256, other_apps_mb=128),
}

# --- 振り分けの行き先（3分岐にするのが要点）---------------------------------
HANDOFF_EDGE = "エッジで完結"
HANDOFF_CLOUD = "クラウドへ引き継ぐ"
HANDOFF_QUEUE = "保留キューに積む"


def handoff(margin: float, threshold: float, online: bool) -> str:
    """1件をどう扱うか。**回線断のときの行き先を先に決めておく。**

    決めていないと、回線が切れているあいだ「難しい件」だけが静かに落ちる。
    落ちたことは誰も気づかない（成功したように見える）ので、いちばん危ない。

    区分に落とせない件を**既定の区分に寄せてはいけない**（中間プロジェクト2の
    結論）。寄せると形式違反が表から消え、リスクが見えなくなる。
    """
    if margin >= threshold:
        return HANDOFF_EDGE
    return HANDOFF_CLOUD if online else HANDOFF_QUEUE


# ---------------------------------------------------------------------------
# 設計（前提の一覧そのもの）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Design:
    """基盤の設計。**ここを1つ変えると、下の派生値が全部数え直される。**

    すべて ③前提値 である（①実測値は `point` から、②物理計算は
    `rtt_floor_ms` などから入ってくる）。
    """

    edge_requests_per_month: float = 1_440_000.0  # 端末1,000台 × 2件/時 × 24h × 30日
    send_ratio: float = 0.15                      # しきい値から決まる（design_for）
    threshold: float = 0.10                       # 送信率の出どころとして持つ
    hq_peak_rps: float = 2.0                      # 本社側のピーク
    hq_baseline_rps: float = 0.4                  # 本社側の平常
    peak_factor: float = 3.0                      # ピークが平均の何倍か（**未実測**）
    cache_hit_rate: float = 0.30                  # 応答キャッシュのヒット率
    hourly_cost: float = 1.0                      # インスタンス1時間の値段（相対単位）
    edge_fixed_cost: float = 100.0                # 配布・検証・仕組み作りの1回払い
    devices: int = DEVICE_COUNT                   # 1,000 台
    line_mbps: float = LINE_MBPS                  # 100.0 Mbps
    distance_km: float = 500.0
    edge_slo_ms: float = 100.0
    slots: int = 2
    total_ctx: int = 2048
    max_tokens: int = 48
    model_file: str = "qwen05b-q4_k_m.gguf"
    headroom: float = HEADROOM                    # 1本に任せる rps の余白（30%）

    def __post_init__(self) -> None:
        if not 0.0 <= self.send_ratio <= 1.0:
            raise ValueError("send_ratio は 0 以上 1 以下で指定してください")
        if not 0.0 <= self.cache_hit_rate < 1.0:
            raise ValueError("cache_hit_rate は 0 以上 1 未満で指定してください")
        if self.peak_factor < 1.0:
            raise ValueError("peak_factor は 1.0 以上です（ピークは平均以上）")
        if self.edge_requests_per_month <= 0:
            raise ValueError("edge_requests_per_month は正の数を指定してください")

    # --- 需要（エッジ → クラウド）-----------------------------------------
    @property
    def cloud_requests_per_month(self) -> float:
        """エッジで判定できずクラウドへ回る件数。**送信率がここを決める。**"""
        return self.edge_requests_per_month * self.send_ratio

    @property
    def cloud_requests_after_cache(self) -> float:
        """応答キャッシュに当たった件はサーバを呼ばない（セッション6）。"""
        return self.cloud_requests_per_month * (1.0 - self.cache_hit_rate)

    @property
    def edge_avg_rps(self) -> float:
        return self.cloud_requests_after_cache / SECONDS_PER_MONTH

    @property
    def peak_rps(self) -> float:
        """合計ピーク。**本社ぶんとエッジ由来を足す**（片方だけ見ると外す）。"""
        return self.hq_peak_rps + self.edge_avg_rps * self.peak_factor

    @property
    def avg_rps(self) -> float:
        """平均。**単価の分母はこちら**（ピークではない）。"""
        return self.hq_baseline_rps + self.edge_avg_rps

    @property
    def plan(self) -> Plan:
        """容量計画（中間プロジェクト1 の道具をそのまま使う）。"""
        return plan_for(Demand(peak_rps=self.peak_rps,
                               baseline_rps=self.avg_rps),
                        self.point, slots=self.slots,
                        total_ctx=self.total_ctx, headroom=self.headroom,
                        model_file=self.model_file, title=TITLE,
                        max_tokens=self.max_tokens)

    # --- 動作点と容量 -------------------------------------------------------
    @property
    def point(self) -> Point:
        """① 実測：SLO を満たす中で最も rps が高い点（中間プロジェクト1）。

        **rps が最大の点ではない。** 飽和した点の rps はほとんど同じなので、
        rps だけで選ぶと体感の壊れた点を選ぶ。
        """
        return operating_point(MEASURED, DEFAULT_SLOS)

    @property
    def per_instance_rps(self) -> float:
        return self.point.throughput_rps * (1.0 - self.headroom)

    @property
    def instances(self) -> int:
        return self.plan.peak_instances

    @property
    def memory_per_instance(self) -> str:
        return self.plan.memory.quantity()

    @property
    def total_memory_mib(self) -> int:
        return self.plan.total_memory_mib

    # --- 単価（相対単位）---------------------------------------------------
    @property
    def utilization(self) -> float:
        """能力のうち実際に埋まっている割合。**台数をピークから数えると下がる。**"""
        return self.avg_rps / (self.instances * self.point.throughput_rps)

    @property
    def cloud_cost_per_1k(self) -> float:
        """セッション10 の式。件数に依存せず、**利用率に反比例する**。"""
        return SelfHosted(self.hourly_cost, self.instances,
                          self.point.throughput_rps,
                          self.utilization).cost_per_1k_requests

    @property
    def edge_cost_per_1k(self) -> float:
        """件数に反比例する（中間プロジェクト2 と同じ式）。"""
        return self.edge_fixed_cost / self.edge_requests_per_month * 1000.0

    @property
    def hybrid_cost_per_1k(self) -> float:
        """系全体。エッジの固定費 ＋ 送信率 × クラウドの単価。"""
        return self.edge_cost_per_1k + self.send_ratio * self.cloud_cost_per_1k

    @property
    def breakeven_requests(self) -> float:
        """エッジの固定費 ÷ クラウドの1リクエスト単価（セッション10 と同じ式）。"""
        return self.edge_fixed_cost / (self.cloud_cost_per_1k / 1000.0)

    # --- 逆転条件 -----------------------------------------------------------
    @property
    def peak_per_send_ratio(self) -> float:
        """送信率 1.0 あたりのピーク rps（送信率を動かしたときの傾き）。"""
        return (self.edge_requests_per_month * (1.0 - self.cache_hit_rate)
                / SECONDS_PER_MONTH * self.peak_factor)

    @property
    def send_ratio_limit(self) -> float:
        """いまの台数のまま許せる送信率の上限。**超えると台数が1本増える。**

        (台数 × 1本の能力 − 本社のピーク) ÷ 傾き。
        しきい値を上げる相談が来たら、まずこの数字を見る。
        """
        slope = self.peak_per_send_ratio
        if slope <= 0:
            return 1.0
        room = self.instances * self.per_instance_rps - self.hq_peak_rps
        return max(min(room / slope, 1.0), 0.0)

    @property
    def capacity_rps(self) -> float:
        """いまの台数で安全に受けられる rps。"""
        return self.instances * self.per_instance_rps

    @property
    def peak_headroom_ratio(self) -> float:
        """能力のうちピークで使う割合。1.0 に近いほど段差が近い。"""
        return self.peak_rps / self.capacity_rps

    # --- エッジ側 -----------------------------------------------------------
    @property
    def edge_footprint(self) -> Footprint:
        """分類器の占有。**KVキャッシュは 0**（保持する状態が無い）。"""
        return Footprint(weights_mb=INT8_MB, kv_mb=0.0,
                         runtime_mb=RUNTIME_CLASSIFIER_MB)

    @property
    def llm_footprint(self) -> Footprint:
        """却下した構成（言語モデルを端末に置く）の占有。"""
        return Footprint(weights_mb=GGUF_Q4_K_M_MB,
                         kv_mb=kv_mb("qwen05b", SEQ_LEN),
                         runtime_mb=RUNTIME_LLM_MB)

    @property
    def rtt_ms(self) -> float:
        """② 物理計算：往復の下限（距離は前提値）。"""
        return rtt_floor_ms(self.distance_km)

    @property
    def distribution_seconds(self) -> float:
        """② 物理計算：全台に配る時間の下限（セッション15 の式）。"""
        return transfer_seconds(INT8_MB, self.devices, self.line_mbps)

    @property
    def max_parallel_downloads(self) -> int:
        """タイムアウトを守れる同時ダウンロード台数の上限（切り捨て）。"""
        return max_parallel_for_timeout(INT8_MB, CLIENT_TIMEOUT_S, self.line_mbps)

    @property
    def stages(self) -> list:
        """段階展開の計画（1 / 9 / 90 / 900 台）。"""
        return stage_plan(self.devices, STAGE_FRACTIONS, INT8_MB,
                          self.line_mbps, OBSERVE_HOURS)

    @property
    def rollout_hours(self) -> float:
        """配布 ＋ 観察（最終段の後の観察は含めない）。"""
        return plan_elapsed_hours(self.stages)

    # --- 完結率（系としての SLO の材料）------------------------------------
    @property
    def completion_ratio(self) -> float:
        """エッジで完結した割合。送信率の裏返し。"""
        return 1.0 - self.send_ratio

    @property
    def completion_floor(self) -> float:
        """これを下回ると台数が1本増える（＝コストが上がる）下限。"""
        return 1.0 - self.send_ratio_limit


def design_for(threshold: float, margins=DEMO_MARGINS, **kw) -> Design:
    """しきい値から送信率を出して設計を組み立てる（中間プロジェクト2 の振り分け）。

    マージンは**例示の固定値**であり実測ではない。自分のモデルのマージンは
    `src/mid02/edge_side.py` が `reports/mid02_edge.json` に書き出す。
    """
    return Design(send_ratio=route(margins, threshold).send_ratio,
                  threshold=threshold, **kw)


def trace(design: Design | None = None,
          thresholds=THRESHOLDS) -> list[dict]:
    """しきい値を振ったときの連鎖。**同時に良くはならない**のが要点。"""
    base = design or Design()
    rows: list[dict] = []
    for t in thresholds:
        d = replace(base, threshold=t,
                    send_ratio=route(DEMO_MARGINS, t).send_ratio)
        rows.append({
            "threshold": t, "send_ratio": d.send_ratio,
            "cloud_requests": d.cloud_requests_per_month,
            "peak_rps": d.peak_rps, "instances": d.instances,
            "memory_mib": d.total_memory_mib, "utilization": d.utilization,
            "cloud_cost": d.cloud_cost_per_1k,
            "hybrid_cost": d.hybrid_cost_per_1k,
            "leaked_per_1k": d.send_ratio * 1000,
            "offline_ok_per_1k": (1.0 - d.send_ratio) * 1000,
        })
    return rows


# ---------------------------------------------------------------------------
# 表示
# ---------------------------------------------------------------------------


def _pad(label: str, width: int = 19) -> str:
    """全角を2桁として数えて右に詰める（出力の桁を揃える）。"""
    used = sum(2 if ord(ch) > 0x2E80 else 1 for ch in label)
    return label + " " * max(width - used, 0)


def show_inputs(d: Design) -> None:
    print("=== 前提（③前提値。金額は相対単位）===")
    print(f"{_pad('一次判定の月間件数')}: {d.edge_requests_per_month:,.0f} 件"
          f"（端末 {d.devices:,} 台 × {REQUESTS_PER_DEVICE_HOUR:g} 件/時 × 24h × 30日）")
    print(f"{_pad('しきい値 / 送信率')}: {d.threshold:.2f} / {d.send_ratio:.1%}")
    print(f"{_pad('本社のピーク / 平常')}: {d.hq_peak_rps:.1f} rps / "
          f"{d.hq_baseline_rps:.1f} rps")
    print(f"{_pad('応答キャッシュ')}: ヒット率 {d.cache_hit_rate:.1%}")
    print(f"{_pad('ピーク倍率')}: {d.peak_factor:.1f} 倍（未実測の前提値）")
    print(f"{_pad('測定条件')}: {MEASURED_CONDITIONS}")


def show_chain(d: Design) -> None:
    print("=== 連鎖（1つの入力から順に数える）===")
    print(f"{_pad('クラウドへ回る件数')}: {d.edge_requests_per_month:,.0f} × "
          f"{d.send_ratio:.3f} = {d.cloud_requests_per_month:,.0f} 件/月")
    print(f"{_pad('キャッシュ後')}: {d.cloud_requests_per_month:,.0f} × "
          f"(1 − {d.cache_hit_rate:.2f}) = {d.cloud_requests_after_cache:,.0f} 件/月")
    print(f"{_pad('平均 rps')}: {d.cloud_requests_after_cache:,.0f} ÷ "
          f"{SECONDS_PER_MONTH:,} = {d.edge_avg_rps:.4f} rps")
    print(f"{_pad('ピーク rps')}: {d.edge_avg_rps:.4f} × {d.peak_factor:.1f} = "
          f"{d.edge_avg_rps * d.peak_factor:.3f} rps")
    print(f"{_pad('合計ピーク')}: {d.hq_peak_rps:.1f} + "
          f"{d.edge_avg_rps * d.peak_factor:.3f} = {d.peak_rps:.3f} rps")
    print(f"{_pad('1本の能力')}: {d.point.throughput_rps} × "
          f"(1 − {d.headroom:.2f}) = {d.per_instance_rps:.3f} rps")
    print(f"{_pad('台数')}: {d.peak_rps:.3f} ÷ {d.per_instance_rps:.3f} = "
          f"{d.peak_rps / d.per_instance_rps:.2f} -> {d.instances} 本")
    print(f"{_pad('メモリ / 本')}: {d.plan.memory_formula()} -> "
          f"{d.memory_per_instance}")
    print(f"{_pad('メモリ合計')}: {d.instances} 本 × "
          f"{d.plan.memory_per_instance_mib} MiB = {d.total_memory_mib:,} MiB")
    print(f"{_pad('利用率')}: {d.avg_rps:.4f} ÷ ({d.instances} × "
          f"{d.point.throughput_rps}) = {d.utilization:.1%}")
    print(f"{_pad('1000件単価')}: ({d.hourly_cost:g} × {d.instances}) ÷ "
          f"({d.avg_rps:.4f} × 3600) × 1000 = {d.cloud_cost_per_1k:.4f}")
    print(f"{_pad('エッジの1000件単価')}: {d.edge_fixed_cost:g} ÷ "
          f"{d.edge_requests_per_month:,.0f} × 1000 = {d.edge_cost_per_1k:.4f}")
    print(f"{_pad('ハイブリッド単価')}: {d.edge_cost_per_1k:.4f} + "
          f"{d.send_ratio:.3f} × {d.cloud_cost_per_1k:.4f} = "
          f"{d.hybrid_cost_per_1k:.4f}")
    print(f"{_pad('損益分岐')}: {d.edge_fixed_cost:g} ÷ "
          f"{d.cloud_cost_per_1k / 1000.0:.8f} = {d.breakeven_requests:,.0f} 件"
          f"（いまの件数はその {d.edge_requests_per_month / d.breakeven_requests:.1f} 倍）")


def show_reversal(d: Design) -> None:
    print("=== 逆転条件 ===")
    print(f"{_pad('送信率の上限')}: {d.send_ratio_limit:.1%}"
          f"（= ({d.instances} × {d.per_instance_rps:.3f} − "
          f"{d.hq_peak_rps:.1f}) ÷ {d.peak_per_send_ratio:.4f}）")
    print(f"{_pad('いまの余裕')}: {d.peak_rps:.3f} rps ÷ 能力 "
          f"{d.capacity_rps:.3f} rps = {d.peak_headroom_ratio:.1%}")
    print(f"{_pad('完結率')}: {d.completion_ratio:.1%}"
          f"（下限 {d.completion_floor:.1%}。下回ると台数が1本増える）")
    print("-> 台数を決めているのは本社のピークである。"
          "ピーク倍率（未実測）を動かしても台数は変わらない。")


def show_trace(rows: list[dict]) -> None:
    print("=== しきい値を振ったときの連鎖（同時に良くはならない）===")
    print("| しきい値 | 送信率 | クラウドへ/月 | 合計ピーク | 台数 | メモリ合計 "
          "| 利用率 | クラウド単価 | 系全体の単価 | 本文が出る/1000件 |")
    print("| --: | --: | --: | --: | --: | --: | --: | --: | --: | --: |")
    for r in rows:
        print(f"| {r['threshold']:.2f} | {r['send_ratio']:.1%} | "
              f"{r['cloud_requests']:,.0f} | {r['peak_rps']:.3f} | "
              f"{r['instances']} | {r['memory_mib']:,} MiB | "
              f"{r['utilization']:.1%} | {r['cloud_cost']:.4f} | "
              f"{r['hybrid_cost']:.4f} | {r['leaked_per_1k']:.0f} |")
    print("-> 系全体の単価は単調に増えるが、"
          "**クラウド単価は台数の段差で跳ねる**（単調ではない）。")
    print("-> 送信率を下げるとクラウド単価は上がる"
          "（台数が本社のピークで決まっていて、利用率だけが下がるため）。")


def show_edge(d: Design) -> None:
    print("=== エッジ側の予算（③前提値の端末に、①実測のモデルを載せる）===")
    fp, llm = d.edge_footprint, d.llm_footprint
    print(f"分類器 int8 : {fp.weights_mb:.2f} + {fp.kv_mb:.2f} + "
          f"{fp.runtime_mb:.1f} = {fp.total_mb:.2f} MB")
    print(f"0.5B Q4_K_M : {llm.weights_mb:.1f} + {llm.kv_mb:.1f} + "
          f"{llm.runtime_mb:.1f} = {llm.total_mb:.1f} MB（却下した構成）")
    print("| 端末 | 上限 | 分類器 | 0.5B |")
    print("| :--- | --: | :--- | :--- |")
    for name, budget in DEVICES.items():
        ok_small, _ = fits(budget, fp)
        ok_llm, margin_llm = fits(budget, llm)
        llm_text = "載る" if ok_llm else f"載らない（{-margin_llm:.1f} MB 不足）"
        print(f"| {name} | {budget.limit_mb:,.1f} MB | "
              f"{'載る' if ok_small else '載らない'} | {llm_text} |")
    print()
    print("=== OTA（②物理計算。セッション15 の式）===")
    print(f"全台への配布（下限）: {d.distribution_seconds:,.1f} 秒"
          f"（{d.distribution_seconds / 60:.1f} 分）"
          f" = {INT8_MB:.2f} MB × {d.devices:,} 台 ÷ {d.line_mbps:.1f} Mbps")
    print(f"fp32 なら          : "
          f"{transfer_seconds(FP32_MB, d.devices, d.line_mbps) / d.distribution_seconds:.1f}"
          " 倍（サイズ比の逆数）")
    print(f"同時ダウンロード上限: {d.max_parallel_downloads} 台"
          f"（タイムアウト {CLIENT_TIMEOUT_S:.0f} 秒）")
    print("| 段 | 台数 | この段の配布（下限） | 観察 |")
    print("| --: | --: | --: | --: |")
    for stage in d.stages:
        print(f"| {stage.index} | {stage.added} | {stage.seconds:,.1f} 秒 | "
              f"{stage.observe_hours:.0f} 時間 |")
    print(f"所要（配布 + 観察）: {d.rollout_hours:.1f} 時間"
          f"（約 {d.rollout_hours / 24:.1f} 日）")
    print(f"往復の物理下限     : {d.rtt_ms:.2f} ms"
          f"（距離 {d.distance_km:.0f} km・前提値。SLO {d.edge_slo_ms:.0f} ms の"
          f" {d.rtt_ms / d.edge_slo_ms:.1%}）")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ハイブリッド基盤の系を数える")
    parser.add_argument("--trace", action="store_true",
                        help="しきい値を振ったときの連鎖")
    parser.add_argument("--edge", action="store_true",
                        help="エッジ側の予算と OTA の数字")
    parser.add_argument("--threshold", type=float, default=None,
                        help="しきい値を指定する（送信率が変わる）")
    args = parser.parse_args(argv)

    design = Design() if args.threshold is None else design_for(args.threshold)

    if args.trace:
        show_trace(trace(design))
        return 0
    if args.edge:
        show_edge(design)
        return 0

    show_inputs(design)
    print()
    show_chain(design)
    print()
    show_reversal(design)
    return 0


if __name__ == "__main__":
    sys.exit(main())
