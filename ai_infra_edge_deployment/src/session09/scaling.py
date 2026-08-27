#!/usr/bin/env python3
"""スケールの指標選択と容量計画（セッション9）。

「**何を見て**増やすか」と「**何本**必要か」を、当てずっぽうではなく
測った動作点から出すための道具。クラスタも推論サーバも要らない。

扱うのは4つ。

1. 指標の選択（CPU 使用率・GPU 使用率・キュー長・キュー待ち時間・
   スロット使用率・TTFT の p95）と、どれを発火に使うか
2. しきい値（飽和点とスロット数から、キュー長のしきい値を導く）
3. スケールの遅れ（発火の遅れ ＋ コールドスタート）とヘッドルーム
4. 必要レプリカ数（**SLO を満たす**動作点の rps から数える）

**絶対値は再現しない。** ここに入っている数値は本書の実測（2026-08-15 実測 /
aarch64 / CPU 2コア / メモリ 5.8GB / Python 3.12.13 / llama.cpp `-t 2`）だが、
環境が変われば変わる。学ぶのは「関係」と「数え方」である。

時間に関する入力（メトリクスの周期・スケジュール・起動）のうち、起動の見積りは
セッション7の `Assumptions` を引き継いだ**仮定**であり実測ではない。
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.session04.serving_config import SweepRow, find_saturation  # noqa: E402
from src.session07.imageplan import GGUF_MB  # noqa: E402
from src.session08.budget import FETCH, startup_seconds  # noqa: E402

MEASURED_CONDITIONS = (
    "2026-08-15 実測 / aarch64 / CPU 2コア / メモリ 5.8GB / Python 3.12.13 / "
    "llama.cpp -t 2 / Q4_K_M / -c 2048 -np 2 / max_tokens=48 / 20 リクエスト"
)
"""本文に数値を書くときに必ず併記する測定条件。"""

SLOTS_PER_INSTANCE = 2
"""1インスタンスの並列スロット数（`-np 2`）。"""


# ---------------------------------------------------------------------------
# 1. 指標の選択
# ---------------------------------------------------------------------------

FIRST = "第一候補"
TOGETHER = "併用"
VERIFY = "検証"
LAST_RESORT = "最後の手段"


@dataclass(frozen=True)
class MetricChoice:
    """スケールの指標1つぶんの評価。"""

    key: str
    name: str
    captures: str
    fits: str
    pitfall: str
    role: str

    @property
    def for_firing(self) -> bool:
        """発火（スケールの判断）に使ってよいか。"""
        return self.role in (FIRST, TOGETHER)


METRICS: tuple[MetricChoice, ...] = (
    MetricChoice(
        "queue_length", "キュー長",
        "まだ処理を始められていないリクエストの件数",
        "最も向く。「待たされている量」そのものである",
        "取り出す配線が要る（次章）。入口で 429/503 を返す構成では増えない",
        FIRST),
    MetricChoice(
        "slot_utilization", "スロット使用率",
        "使用中スロット ÷ 総スロット",
        "併用向き。飽和の直前までは素直に上がる",
        "100% に張り付いた先が見えない（並列2 も並列4 も 100%）",
        TOGETHER),
    MetricChoice(
        "queue_wait_ms", "キュー待ち時間",
        "待ち行列に置かれていた時間",
        "向くが遅い。完了したリクエストしか観測できない",
        "まだ待っている人が数に入らないので、発火が遅れる",
        VERIFY),
    MetricChoice(
        "ttft_p95", "TTFT の p95",
        "利用者の体感（最初の1トークンが返るまでの待ち）",
        "SLO の判定に向く。発火には遅い",
        "遅行指標。応答キャッシュのヒットで薄まる。20 件未満では出せない",
        VERIFY),
    MetricChoice(
        "cpu_utilization", "CPU 使用率",
        "計算でコアが埋まっているか",
        "向かない。デコードはメモリ帯域律速なので、飽和しても上がりきらないことがある",
        "requests と limits を揃えた推論 Pod では生成中ずっと張り付く。待ち行列と相関しない",
        LAST_RESORT),
    MetricChoice(
        "gpu_utilization", "GPU 使用率",
        "サンプル期間中にカーネルが1つ以上動いていた時間の割合",
        "向かない。並列度でも飽和度でもない",
        "帯域待ちでも 100% に見える。本書は GPU を実測していない（一次情報の引用のみ）",
        LAST_RESORT),
)

METRICS_BY_KEY = {m.key: m for m in METRICS}

FIRING_ORDER = ("queue_length", "slot_utilization", "queue_wait_ms",
                "ttft_p95", "cpu_utilization", "gpu_utilization")
"""発火に使うときの優先順。上にあるものから選ぶ。"""

FALLBACK_NOTE = {
    "queue_length": "",
    "slot_utilization": "100% に張り付いた先が見えません。"
                        "どれだけ超過しているかはキュー長でしか分かりません",
    "queue_wait_ms": "完了したリクエストしか観測できないので、発火が遅れます。"
                     "しきい値の妥当性を確かめる用途に留めてください",
    "ttft_p95": "悪化してから動く遅行指標です。SLO の逸脱検知に使い、"
                "発火はキュー長に任せてください",
    "cpu_utilization": "推論の飽和と相関しません。"
                       "プリフィル主体で入力長がほぼ一定のときの暫定策に留め、"
                       "まずキュー長を取り出せるようにしてください",
    "gpu_utilization": "並列度も飽和度も表しません。"
                       "GPU の空き VRAM とあわせて人が見る指標です",
}


def metric_table() -> str:
    """指標の比較表（Markdown）。判断基準の節にそのまま貼れる形で返す。"""
    lines = ["| 指標 | 何を捉えるか | 推論に向くか | 落とし穴 | 役割 |",
             "| :--- | :--- | :--- | :--- | :--- |"]
    order = {FIRST: 0, TOGETHER: 1, VERIFY: 2, LAST_RESORT: 3}
    for m in sorted(METRICS, key=lambda x: order[x.role]):
        lines.append(f"| {m.name} | {m.captures} | {m.fits} | {m.pitfall} | {m.role} |")
    return "\n".join(lines)


def recommend_metric(available: set[str] | frozenset[str]) -> tuple[MetricChoice, str]:
    """取れる指標の集合から、発火に使う指標を1つ選ぶ。

    返り値は（選んだ指標, 注意書き）。注意書きが空文字なら、そのまま使ってよい。
    **選べる指標が無いときは例外にする。** 「無いから CPU で」と黙って倒れない。
    """
    unknown = set(available) - set(METRICS_BY_KEY)
    if unknown:
        raise ValueError(f"知らない指標です: {sorted(unknown)}")
    for key in FIRING_ORDER:
        if key in available:
            return METRICS_BY_KEY[key], FALLBACK_NOTE[key]
    raise ValueError("使える指標が1つもありません。まずキュー長を取り出してください")


# ---------------------------------------------------------------------------
# 2. 動作点（測った点）と SLO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OperatingPoint:
    """同時実行を1段変えて測った1点。**すべて実測値である。**"""

    concurrency: int
    ttft_p50_ms: float
    ttft_p95_ms: float
    total_p50_ms: float
    total_p95_ms: float
    tpot_p50_ms: float
    throughput_tps: float
    throughput_rps: float

    def queue_len(self, slots: int = SLOTS_PER_INSTANCE) -> int:
        """スロットが埋まったあとに待っている件数（＝キュー長）。"""
        return max(self.concurrency - slots, 0)

    def slot_utilization(self, slots: int = SLOTS_PER_INSTANCE) -> float:
        """スロット使用率。1.0 で頭打ちになる（ここが落とし穴）。"""
        if slots <= 0:
            raise ValueError("slots は 1 以上を指定してください")
        return min(self.concurrency / slots, 1.0)


POINTS: tuple[OperatingPoint, ...] = (
    OperatingPoint(1, 155.0, 194.0, 1034.0, 1212.0, 19.19, 45.0, 0.96),
    OperatingPoint(2, 52.0, 100.0, 1737.0, 2126.0, 36.74, 53.0, 1.13),
    OperatingPoint(4, 1772.0, 2064.0, 3379.0, 3737.0, 36.15, 53.9, 1.15),
)
"""セッション4の実測表（`reports/load_serve_c{1,2,4}.json`）。

TPOT は `LoadReport.tpot.p50` の実測値である。
`(総時間 − TTFT) ÷ トークン数` の概算で代用してはいけない。
"""


@dataclass(frozen=True)
class Slo:
    """守る約束。**動作点を選ぶのはこの2本の線である。**"""

    ttft_p95_ms: float = 1000.0
    total_p95_ms: float = 3000.0

    def satisfied_by(self, point: OperatingPoint) -> bool:
        return (point.ttft_p95_ms <= self.ttft_p95_ms
                and point.total_p95_ms <= self.total_p95_ms)

    def describe(self) -> str:
        return (f"TTFT p95 ≦ {self.ttft_p95_ms:.0f} ms / "
                f"総時間 p95 ≦ {self.total_p95_ms:.0f} ms")


def sweep_rows(points: tuple[OperatingPoint, ...] = POINTS) -> list[SweepRow]:
    """セッション4の `find_saturation` に渡せる形に直す。"""
    return [SweepRow(p.concurrency, p.ttft_p50_ms, p.total_p50_ms, p.throughput_tps)
            for p in points]


def saturation_concurrency(points: tuple[OperatingPoint, ...] = POINTS) -> int | None:
    """飽和点（セッション4の定義：伸びが止まり TTFT が悪化する最初の点）。"""
    return find_saturation(sweep_rows(points))


def best_point(points: tuple[OperatingPoint, ...] = POINTS,
               slo: Slo | None = None) -> OperatingPoint:
    """SLO を満たす中で最もスループット（rps）が高い動作点。

    **「rps が最大の点」ではなく「SLO を満たす最大の点」を採る。** 飽和した点の
    rps はほとんど同じなので、rps だけで選ぶと体感の壊れた点を選んでしまう。
    """
    slo = slo or Slo()
    ok = [p for p in points if slo.satisfied_by(p)]
    if not ok:
        raise ValueError("SLO を満たす動作点がありません。"
                         "設定（スロット数・量子化）か SLO を見直してください")
    return max(ok, key=lambda p: p.throughput_rps)


def little_check_rps(point: OperatingPoint,
                     slots: int = SLOTS_PER_INSTANCE) -> float:
    """`スロット数 ÷ 1リクエストの総時間` で rps を検算する（待ち行列の理屈）。

    実測の rps とかけ離れていたら、測り方か前提のどちらかが間違っている。
    """
    return slots / (point.total_p50_ms / 1000.0)


@dataclass(frozen=True)
class BlindSpot:
    """CPU 使用率の死角。健全な点と飽和した点を並べる。"""

    healthy: OperatingPoint
    saturated: OperatingPoint
    slots: int = SLOTS_PER_INSTANCE

    @property
    def throughput_ratio(self) -> float:
        return self.saturated.throughput_tps / self.healthy.throughput_tps

    @property
    def tpot_ratio(self) -> float:
        return self.saturated.tpot_p50_ms / self.healthy.tpot_p50_ms

    @property
    def ttft_p95_ratio(self) -> float:
        return self.saturated.ttft_p95_ms / self.healthy.ttft_p95_ms

    @property
    def same_slot_utilization(self) -> bool:
        return (self.healthy.slot_utilization(self.slots)
                == self.saturated.slot_utilization(self.slots))

    def explain(self) -> str:
        h, s = self.healthy, self.saturated
        return "\n".join([
            f"CPU 使用率の死角（{MEASURED_CONDITIONS}）",
            f"  健全な点  : 並列 {h.concurrency} — TTFT p95 {h.ttft_p95_ms:.0f} ms / "
            f"TPOT {h.tpot_p50_ms} ms / {h.throughput_tps} tok/s / "
            f"スロット使用率 {h.slot_utilization(self.slots) * 100:.0f}% / "
            f"キュー長 {h.queue_len(self.slots)} 件",
            f"  飽和した点: 並列 {s.concurrency} — TTFT p95 {s.ttft_p95_ms:.0f} ms / "
            f"TPOT {s.tpot_p50_ms} ms / {s.throughput_tps} tok/s / "
            f"スロット使用率 {s.slot_utilization(self.slots) * 100:.0f}% / "
            f"キュー長 {s.queue_len(self.slots)} 件",
            f"  スループット比: {self.throughput_ratio:.2f} 倍（サーバがしている計算量はほぼ同じ）",
            f"  TPOT 比       : {self.tpot_ratio:.2f} 倍（1トークンあたりの生成時間もほぼ同じ）",
            f"  TTFT p95 比   : {self.ttft_p95_ratio:.1f} 倍（利用者の体感だけが壊れている）",
            "  結論: 計算量が同じなら CPU 使用率も同じになる。"
            "CPU 使用率はこの2点を区別できない。",
            f"        区別できるのはキュー長（{h.queue_len(self.slots)} 件 と "
            f"{s.queue_len(self.slots)} 件）である。",
        ])


def cpu_blind_spot(points: tuple[OperatingPoint, ...] = POINTS,
                   slo: Slo | None = None,
                   slots: int = SLOTS_PER_INSTANCE) -> BlindSpot:
    """SLO を満たす点と飽和した点を取り出して並べる。"""
    healthy = best_point(points, slo)
    sat = saturation_concurrency(points)
    if sat is None:
        raise ValueError("飽和点が見つかりません。刻みを細かくして測り直してください")
    saturated = next(p for p in points if p.concurrency == sat)
    return BlindSpot(healthy, saturated, slots)


@dataclass(frozen=True)
class ScaleShape:
    """同じサーバを「縦に詰める」か「横に並べる」かの比較の1行。"""

    label: str
    instances: int
    concurrency_per_instance: int
    rps: float
    tpot_ms: float
    ttft_p95_ms: float


def scale_up_vs_out(points: tuple[OperatingPoint, ...] = POINTS,
                    slots: int = SLOTS_PER_INSTANCE) -> tuple[ScaleShape, ScaleShape]:
    """縦（スロットを使い切る）と横（レプリカを増やす）を実測から並べる。

    **横の掛け算は「別のノードに置く」前提である。** 同じノードに2本置けば
    CPU を分け合うので成り立たない（`requests.cpu` を守る限り、スケジューラは
    空きのあるノードを選ぶ）。
    """
    by_c = {p.concurrency: p for p in points}
    if 1 not in by_c or slots not in by_c:
        raise ValueError("並列1 と スロット数ぶんの並列の実測が必要です")
    single, full = by_c[1], by_c[slots]
    up = ScaleShape(f"縦：1インスタンス × 並列{slots}", 1, slots,
                    full.throughput_rps, full.tpot_p50_ms, full.ttft_p95_ms)
    out = ScaleShape(f"横：{slots}インスタンス × 並列1", slots, 1,
                     single.throughput_rps * slots, single.tpot_p50_ms,
                     single.ttft_p95_ms)
    return up, out


def target_queue_len(points: tuple[OperatingPoint, ...] = POINTS,
                     slots: int = SLOTS_PER_INSTANCE,
                     divisor: float = 2.0) -> float:
    """キュー長のしきい値を飽和点から導く。

    飽和点でのキュー長（＝飽和点の同時実行 − スロット数）の `1/divisor` を採る。
    **飽和してから発火しては遅い**ので、手前に置くのが要点である。
    下限は 1 件（0 件をしきい値にすると常に発火する）。
    """
    if divisor <= 0:
        raise ValueError("divisor は正の数を指定してください")
    sat = saturation_concurrency(points)
    if sat is None:
        return 1.0
    return max(max(sat - slots, 0) / divisor, 1.0)


# ---------------------------------------------------------------------------
# 3. スケールの遅れ
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScaleLag:
    """「増やせ」と決まってから、実際に処理を始めるまでの遅れ（秒）。

    前半（発火）と後半（供給）に分けて数えるのが要点である。**縮めるべきは
    支配している側**で、それは環境によって入れ替わる。

    - `metric_period_s` / `hpa_period_s`：既定値の目安（Kubernetes の
      HPA は既定 15 秒間隔で評価する）
    - `stabilization_s`：`behavior.scaleUp.stabilizationWindowSeconds`
    - `schedule_s`：Pod がノードに載るまで（**仮定**）
    - `startup_s`：セッション7・8の起動見積り（**仮定の積み上げ**）
    - `ready_detect_s`：`readinessProbe.periodSeconds`（準備完了を検出する遅れ）
    """

    startup_s: float
    metric_period_s: float = 15.0
    hpa_period_s: float = 15.0
    stabilization_s: float = 0.0
    schedule_s: float = 5.0
    ready_detect_s: float = 10.0

    @property
    def fire_s(self) -> float:
        """発火まで（指標が届き、HPA が評価し、安定化を抜けるまで）。"""
        return self.metric_period_s + self.hpa_period_s + self.stabilization_s

    @property
    def provision_s(self) -> float:
        """供給まで（Pod が載り、起動し、準備完了が検出されるまで）。"""
        return self.schedule_s + self.startup_s + self.ready_detect_s

    @property
    def total_s(self) -> float:
        return self.fire_s + self.provision_s

    def breakdown(self) -> dict[str, float]:
        return {"メトリクスの周期": self.metric_period_s,
                "HPA の評価間隔": self.hpa_period_s,
                "安定化ウィンドウ": self.stabilization_s,
                "Pod のスケジュール": self.schedule_s,
                "起動（重み取得込み）": self.startup_s,
                "readiness の検出": self.ready_detect_s}

    @property
    def dominant(self) -> str:
        """内訳で最も大きい項目。ここを縮めない改善は効かない。"""
        return max(self.breakdown().items(), key=lambda kv: kv[1])[0]

    def explain(self) -> str:
        lines = [f"スケールの遅れ {self.total_s:.1f} 秒"
                 f"（発火 {self.fire_s:.1f} ＋ 供給 {self.provision_s:.1f}）"]
        for name, value in self.breakdown().items():
            lines.append(f"  {name}: {value:.1f} 秒")
        lines.append(f"  支配している項目: {self.dominant}")
        return "\n".join(lines)


def lag_for(method: str = FETCH, weights_mib: float | None = None,
            **kwargs: float) -> ScaleLag:
    """重みの配り方とサイズから遅れを組み立てる（セッション7の見積りを使う）。"""
    weights = GGUF_MB["q4_k_m"] if weights_mib is None else weights_mib
    return ScaleLag(startup_s=startup_seconds(method, weights), **kwargs)


# ---------------------------------------------------------------------------
# 4. 容量計画
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapacityPlan:
    """何本必要かと、HPA に書く値。**入力が変わったら数え直す。**"""

    peak_rps: float
    baseline_rps: float
    ramp_rps_per_s: float
    headroom: float
    slots: int
    point: OperatingPoint
    lag: ScaleLag
    slo: Slo
    surge_factor: float
    floor: int
    saturation: int | None
    points: tuple[OperatingPoint, ...] = field(default=POINTS, repr=False)

    # --- 1インスタンスの能力 ------------------------------------------------
    @property
    def per_instance_rps(self) -> float:
        """安全に任せられる1インスタンスの rps（ヘッドルームを引いた値）。"""
        return self.point.throughput_rps * (1.0 - self.headroom)

    # --- 本数 ---------------------------------------------------------------
    @property
    def peak_replicas(self) -> int:
        return math.ceil(self.peak_rps / self.per_instance_rps)

    @property
    def baseline_replicas(self) -> int:
        return math.ceil(self.baseline_rps / self.per_instance_rps)

    @property
    def burst_rps(self) -> float:
        """スケールが間に合うまでに増えてしまう負荷。"""
        return self.ramp_rps_per_s * self.lag.total_s

    @property
    def headroom_replicas(self) -> int:
        """立ち上がりを吸収するために常時空けておく本数。"""
        return math.ceil(self.burst_rps / self.per_instance_rps)

    @property
    def min_replicas(self) -> int:
        return max(self.floor, self.baseline_replicas + self.headroom_replicas)

    @property
    def max_replicas(self) -> int:
        return math.ceil(self.peak_replicas * self.surge_factor)

    # --- しきい値と遅れ ------------------------------------------------------
    @property
    def target_queue_len(self) -> float:
        return target_queue_len(self.points, self.slots)

    @property
    def cold_start_wait_s(self) -> float:
        """`minReplicas: 0` にしたときに最初の利用者が待つ時間。"""
        return self.lag.total_s

    @property
    def slo_multiple(self) -> float:
        """その待ちが TTFT の SLO の何倍か。"""
        return self.cold_start_wait_s * 1000.0 / self.slo.ttft_p95_ms

    # --- 説明 ---------------------------------------------------------------
    @property
    def saturation_queue_len(self) -> int:
        """飽和点でのキュー長（しきい値を導く元になる数）。"""
        return max((self.saturation or 0) - self.slots, 0)

    def explain(self) -> str:
        p = self.point
        if self.saturation is None:
            saturation_line = "  飽和点          : 検出されず（刻みを細かくして測り直す）"
        else:
            saturation_line = (f"  飽和点          : 並列 {self.saturation}"
                               f"（スロット {self.slots} の "
                               f"{self.saturation / self.slots:.0f} 倍）")
        return "\n".join([
            "容量計画",
            f"  測定条件        : {MEASURED_CONDITIONS}",
            f"  SLO             : {self.slo.describe()}",
            saturation_line,
            f"  採用する動作点  : 並列 {p.concurrency} — "
            f"TTFT p95 {p.ttft_p95_ms:.0f} ms / 総時間 p95 {p.total_p95_ms:.0f} ms / "
            f"TPOT {p.tpot_p50_ms} ms / {p.throughput_rps} rps",
            f"  1インスタンス   : {p.throughput_rps} rps × "
            f"(1 − {self.headroom:.2f}) = {self.per_instance_rps:.2f} rps",
            f"  ピーク {self.peak_rps:.2f} rps : {self.peak_rps:.2f} ÷ "
            f"{self.per_instance_rps:.2f} = "
            f"{self.peak_rps / self.per_instance_rps:.2f} → {self.peak_replicas} 本",
            f"  平常 {self.baseline_rps:.2f} rps  : {self.baseline_rps:.2f} ÷ "
            f"{self.per_instance_rps:.2f} = "
            f"{self.baseline_rps / self.per_instance_rps:.2f} → "
            f"{self.baseline_replicas} 本",
            f"  スケールの遅れ  : {self.lag.total_s:.1f} 秒"
            f"（発火 {self.lag.fire_s:.1f} ＋ 供給 {self.lag.provision_s:.1f}）",
            f"  立ち上がりの吸収: {self.ramp_rps_per_s} rps/s × "
            f"{self.lag.total_s:.1f} 秒 = {self.burst_rps:.2f} rps → "
            f"{self.burst_rps / self.per_instance_rps:.2f} → "
            f"{self.headroom_replicas} 本",
            f"  minReplicas     : max({self.floor}, {self.baseline_replicas} + "
            f"{self.headroom_replicas}) = {self.min_replicas}",
            f"  maxReplicas     : {self.peak_replicas} × {self.surge_factor} = "
            f"{self.peak_replicas * self.surge_factor:.1f} → {self.max_replicas}",
            f"  しきい値        : 1インスタンスあたり平均キュー長 "
            f"{self.target_queue_len:.1f} 件"
            f"（飽和時 {self.saturation_queue_len} 件の半分）",
        ])

    def markdown(self, title: str = "みなと商事 ヘルプデスク回答 API") -> str:
        """引き継げる成果物（Markdown）。**前提と再計算手順を必ず含める。**"""
        lines = [
            f"# 容量計画：{title}",
            "",
            f"- 測定条件：{MEASURED_CONDITIONS}",
            "- **絶対値は再現しません。** 自分の環境で測り直し、同じ手順で数え直してください。",
            "",
            "## 1. 前提（変わったら数え直す入力）",
            "",
            "| 入力 | 値 | 出どころ |",
            "| :--- | --: | :--- |",
            f"| ピークのリクエスト率 | {self.peak_rps:.2f} rps | 要件 |",
            f"| 平常時のリクエスト率 | {self.baseline_rps:.2f} rps | 要件 |",
            f"| 立ち上がりの傾き | {self.ramp_rps_per_s} rps/s | 要件 |",
            f"| ヘッドルーム | {self.headroom * 100:.0f}% | 運用の判断 |",
            f"| 1インスタンスのスロット数 | {self.slots} | `-np {self.slots}` |",
            f"| SLO | {self.slo.describe()} | 要件 |",
            "",
            "## 2. 動作点（実測から選ぶ）",
            "",
            "| 並列 | TTFT p95 | 総時間 p95 | TPOT p50 | rps | キュー長 | SLO |",
            "| --: | --: | --: | --: | --: | --: | :--- |",
        ]
        for p in self.points:
            verdict = "満たす" if self.slo.satisfied_by(p) else "満たさない"
            mark = "（採用）" if p.concurrency == self.point.concurrency else ""
            if self.saturation == p.concurrency:
                mark = "（飽和点）"
            lines.append(f"| {p.concurrency} | {p.ttft_p95_ms:.0f} ms | "
                         f"{p.total_p95_ms:.0f} ms | {p.tpot_p50_ms} ms | "
                         f"{p.throughput_rps} | {p.queue_len(self.slots)} 件 | "
                         f"{verdict}{mark} |")
        lines += [
            "",
            "## 3. 数え方",
            "",
            "```text",
            self.explain(),
            "```",
            "",
            "## 4. HPA に書く値",
            "",
            "| フィールド | 値 | 根拠 |",
            "| :--- | --: | :--- |",
            f"| `minReplicas` | {self.min_replicas} | "
            f"平常 {self.baseline_replicas} 本 ＋ 立ち上がり吸収 "
            f"{self.headroom_replicas} 本（下限 {self.floor} 本） |",
            f"| `maxReplicas` | {self.max_replicas} | "
            f"ピーク {self.peak_replicas} 本 × {self.surge_factor} |",
            f"| キュー長のしきい値 | {self.target_queue_len:.1f} 件/本 | "
            f"飽和時 {self.saturation_queue_len} 件の半分 |",
            "",
            "## 5. 前提が変わったときの再計算手順",
            "",
            "1. 同時実行を振って測り直す（`src/session04/sweep.py`）。"
            "**SLO を満たす最大の点**を動作点に採る",
            "2. その点の rps にヘッドルームを掛け、1インスタンスの能力を出す",
            "3. ピーク ÷ 1インスタンスの能力（切り上げ）＝ 必要な本数",
            "4. 起動の見積りを出し直し（`src/session08/budget.py`）、"
            "（遅れ × 立ち上がりの傾き）÷ 1インスタンスの能力 ＝ 常時空けておく本数",
            "5. 飽和点からキュー長のしきい値を引き直し、"
            "`src/session09/lint_hpa.py --plan` でマニフェストと突き合わせる",
        ]
        return "\n".join(lines)


def plan_capacity(*, peak_rps: float = 5.0, baseline_rps: float = 0.5,
                  ramp_rps_per_s: float = 0.02, headroom: float = 0.30,
                  slots: int = SLOTS_PER_INSTANCE,
                  points: tuple[OperatingPoint, ...] = POINTS,
                  slo: Slo | None = None, lag: ScaleLag | None = None,
                  surge_factor: float = 1.7, floor: int = 2) -> CapacityPlan:
    """容量計画を組み立てる。入力の妥当性はここで弾く。"""
    if peak_rps <= 0:
        raise ValueError("peak_rps は正の数を指定してください")
    if baseline_rps < 0 or ramp_rps_per_s < 0:
        raise ValueError("baseline_rps と ramp_rps_per_s は 0 以上です")
    if not 0.0 <= headroom < 1.0:
        raise ValueError("headroom は 0 以上 1 未満で指定してください")
    if slots < 1:
        raise ValueError("slots は 1 以上を指定してください")
    if surge_factor < 1.0:
        raise ValueError("surge_factor は 1.0 以上を指定してください")
    if floor < 1:
        raise ValueError("floor は 1 以上を指定してください（0 にしない）")
    slo = slo or Slo()
    return CapacityPlan(
        peak_rps=peak_rps, baseline_rps=baseline_rps,
        ramp_rps_per_s=ramp_rps_per_s, headroom=headroom, slots=slots,
        point=best_point(points, slo), lag=lag or lag_for(), slo=slo,
        surge_factor=surge_factor, floor=floor,
        saturation=saturation_concurrency(points), points=points)


__all__ = [
    "FIRST", "FIRING_ORDER", "LAST_RESORT", "MEASURED_CONDITIONS", "METRICS",
    "METRICS_BY_KEY", "POINTS", "SLOTS_PER_INSTANCE", "TOGETHER", "VERIFY",
    "BlindSpot", "CapacityPlan", "MetricChoice", "OperatingPoint", "ScaleLag",
    "ScaleShape", "Slo", "best_point", "cpu_blind_spot", "lag_for",
    "little_check_rps", "metric_table", "plan_capacity", "recommend_metric",
    "saturation_concurrency", "scale_up_vs_out", "sweep_rows",
    "target_queue_len",
]
