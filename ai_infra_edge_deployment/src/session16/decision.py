#!/usr/bin/env python3
"""意思決定と移行（セッション16）。

**新しい技術は入っていない。** セッション9〜14 で作った計算を、そのまま
「どこで推論するか」の判断に流し込むだけのファイルである。

扱うのは5つ。

1. ゲート（満たさなければ失格。**点数で埋め合わせられない**）
2. 単価と損益分岐（セッション10 の式をそのまま使う）
3. 感度分析（どの前提がどれだけ動くと結論が反転するか）
4. 重み付きスコア（**順位を作る道具ではなく、漏れを見つける道具**）
5. 移行計画と再判断のトリガー

数値は3種類あり、**混ぜてはいけない**（セッション11 からの規律）。

  ① 実測値   : 本書の測定結果（測定条件つきで引用する）
  ② 物理計算 : 定数から一意に決まるもの（往復の下限・配布時間）
  ③ 前提値   : 読者が自分の案件の値を入れるもの（件数・人員・単価・軸のスコア）

金額はすべて**相対単位**である（インスタンス1時間の値段を 1 と置く）。
本書は特定クラウドの価格を書かない。

    python src/session16/decision.py                       # 3シナリオまとめて
    python src/session16/decision.py --scenario s2          # 1つだけ
    python src/session16/decision.py --scenario s2 --markdown
    python src/session16/decision.py --scenario s2 --markdown --out reports/session16_decision.md
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, replace
from pathlib import Path

SANDBOX = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SANDBOX))

from src.session09.scaling import MEASURED_CONDITIONS, best_point  # noqa: E402
from src.session10.cost_report import (  # noqa: E402
    HEADROOM, MAX_UTILIZATION, Assumptions, breakeven, cost_per_1k,
)
from src.session11.edge_budget import (  # noqa: E402
    Footprint, MemoryBudget, fits, monthly_upload_gb, rtt_floor_ms,
)
from src.session14.mcu_budget import (  # noqa: E402
    DEVICE_E, GGUF_Q4_K_M_MB, KB, KV_PER_TOKEN_KB_05B, KV_PER_TOKEN_KB_8B, MB,
    ONNX_INT8_MB, SEQ_LEN, fits_raw,
)

SECONDS_PER_MONTH = 30 * 24 * 3600      # ③ 前提値：1か月＝30日として数える
HOURS_PER_MONTH = 720.0

POINT = best_point()
"""① 実測：SLO を満たす中で rps が最大の動作点（並列2 / 1.13 rps）。"""

PEAK_FACTOR = 3.0
"""③ 前提値：ピークが平均の何倍か。**未実測。** ここを実測に置き換えるのが最優先。"""

FLOOR_INSTANCES = 2
"""③ 前提値：可用性のための台数の下限（セッション9 の floor）。需要から出た数ではない。"""

EDGE_SHARE = 0.70
"""③ 前提値：ハイブリッドで端末側だけで完結する割合。残りがクラウドへ行く。

**「送信率」とは別の数**である。ここは「端末で答えまで出せた割合」で、
シナリオごとの送信率（`Scenario.send_ratio`）はタスクの性質で決まる。
"""

RUNTIME_CLASSIFIER_MB = 50.0    # ③ 前提値（セッション11）
RUNTIME_LLM_MB = 150.0          # ③ 前提値（セッション11）

# ③ 前提値：セッション11 の共通端末（数値を変えると章をまたいだ比較が壊れる）
DEVICE_A = MemoryBudget(total_mb=4096, os_reserved_mb=1024, other_apps_mb=1536)
DEVICE_D = MemoryBudget(total_mb=1024, os_reserved_mb=256, other_apps_mb=128)

# 端末に載せる候補のフットプリント（重み ＋ KVキャッシュ ＋ 実行時メモリ）
FOOTPRINTS: dict[str, Footprint] = {
    "classifier": Footprint(weights_mb=ONNX_INT8_MB, kv_mb=0.0,
                            runtime_mb=RUNTIME_CLASSIFIER_MB),
    "0.5b": Footprint(weights_mb=GGUF_Q4_K_M_MB,
                      kv_mb=KV_PER_TOKEN_KB_05B * SEQ_LEN / KB,
                      runtime_mb=RUNTIME_LLM_MB),
    "8b": Footprint(weights_mb=8e9 * 2 / MB,
                    kv_mb=KV_PER_TOKEN_KB_8B * SEQ_LEN / KB,
                    runtime_mb=RUNTIME_LLM_MB),
}
MODEL_LABELS = {"classifier": "分類器 int8", "0.5b": "0.5B Q4_K_M", "8b": "8B級 f16"}
FRONT_MODEL = "classifier"
"""ハイブリッドの前段に置くモデル。**前段は分類器で足りる**のが成立の条件。"""

# --- 選択肢 -----------------------------------------------------------------
API = "クラウドAPI"
SELF = "自前ホスティング"
EDGE = "エッジ"
HYBRID = "ハイブリッド"
OPTIONS: tuple[str, ...] = (API, SELF, EDGE, HYBRID)

STAFF_NEEDED = {API: 1, SELF: 2, EDGE: 2, HYBRID: 3}
"""③ 前提値：その案を運用するのに最低限必要な人数。**下限があるならゲートにする。**"""

MODE_FIXED = "固定台数"
MODE_AUTO = "オートスケール"


# ---------------------------------------------------------------------------
# 1. 前提（読者が入れる値）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Inputs:
    """コスト側の前提。**1つでも変われば答えも変わる。**

    `point_rps` だけが①実測で、あとは③前提値である。
    """

    monthly_requests: float
    peak_factor: float = PEAK_FACTOR
    hourly_cost: float = 1.0
    point_rps: float = POINT.throughput_rps
    api_input_price_per_1m: float = 0.8
    api_output_price_per_1m: float = 3.2
    input_tokens: float = 300.0
    output_tokens: float = 48.0

    def __post_init__(self) -> None:
        if self.monthly_requests <= 0:
            raise ValueError("monthly_requests は正の数を指定してください")
        if self.point_rps <= 0:
            raise ValueError("point_rps は正の数を指定してください")
        if self.peak_factor < 1.0:
            raise ValueError("peak_factor は 1.0 以上です（ピークは平均以上）")

    # --- 能力 -------------------------------------------------------------
    @property
    def per_instance_rps(self) -> float:
        """1本に安全に任せられる rps（ヘッドルーム 30% を引いた値）。"""
        return self.point_rps * (1.0 - HEADROOM)

    @property
    def avg_rps(self) -> float:
        return self.monthly_requests / SECONDS_PER_MONTH

    @property
    def peak_rps(self) -> float:
        return self.avg_rps * self.peak_factor

    @property
    def requests_per_hour(self) -> float:
        """1時間に実際に来る件数（＝単価の分母。能力ではない）。"""
        return self.monthly_requests / HOURS_PER_MONTH

    # --- 台数と利用率 -----------------------------------------------------
    def instances(self, mode: str = MODE_AUTO) -> int:
        """必要な台数。**切り上げるので整数の段差ができる。** ここが結論の脆さの源。"""
        need = self.peak_rps if mode == MODE_FIXED else self.avg_rps
        return max(FLOOR_INSTANCES,
                   math.ceil(self.avg_rps / self.per_instance_rps),
                   math.ceil(need / self.per_instance_rps))

    def utilization(self, mode: str = MODE_AUTO) -> float:
        """能力のうち実際に埋まっている割合。台数の決め方でここが変わる。"""
        return self.avg_rps / (self.instances(mode) * self.point_rps)

    def assumptions(self, mode: str = MODE_AUTO) -> Assumptions:
        """セッション10 の `Assumptions` に変換する（単価の式を再実装しない）。"""
        return Assumptions(hourly_cost=self.hourly_cost,
                           instances=self.instances(mode),
                           rps_per_instance=self.point_rps,
                           utilization=self.utilization(mode),
                           api_input_price_per_1m=self.api_input_price_per_1m,
                           api_output_price_per_1m=self.api_output_price_per_1m,
                           input_tokens=self.input_tokens,
                           output_tokens=self.output_tokens)


def self_cost_per_1k(inp: Inputs, mode: str = MODE_AUTO) -> float:
    return cost_per_1k(inp.assumptions(mode))


def api_cost_per_1k(inp: Inputs) -> float:
    return breakeven(inp.assumptions()).api_per_1k


def self_is_cheaper(inp: Inputs, mode: str = MODE_AUTO) -> bool:
    """結論の本体。感度分析はこの真偽が反転する点を探す。"""
    return self_cost_per_1k(inp, mode) < api_cost_per_1k(inp)


# ---------------------------------------------------------------------------
# 2. シナリオ
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    """③ 前提値の束。**この表が埋まらないうちは3択を比較できない。**"""

    key: str
    name: str
    inputs: Inputs
    offline_required: bool
    raw_data_may_leave: bool
    slo_ms: float
    distance_km: float
    model_class: str
    device_name: str
    device: MemoryBudget
    staff: int
    api_priced: bool
    # 通信量の見積もり（③前提値）。payload_bytes が 0 のときは計算しない。
    payload_bytes: float = 0.0
    per_hour: float = 60.0
    devices: int = 1000
    send_ratio: float = 1.0


SCENARIOS: dict[str, Scenario] = {
    "s1": Scenario("s1", "社内ヘルプデスク（試験導入・1部署）", Inputs(100_000),
                   offline_required=False, raw_data_may_leave=True, slo_ms=1000.0,
                   distance_km=1000.0, model_class="8b", device_name="端末A",
                   device=DEVICE_A, staff=2, api_priced=True),
    "s2": Scenario("s2", "社内ヘルプデスク（全社展開）", Inputs(10_000_000),
                   offline_required=False, raw_data_may_leave=True, slo_ms=1000.0,
                   distance_km=1000.0, model_class="8b", device_name="端末A",
                   device=DEVICE_A, staff=3, api_priced=True),
    # 端末 1,000 台 × 毎分1件 × 24時間 × 30日 = 43,200,000 件（③前提値）
    "s3": Scenario("s3", "工場の一次判定（オフライン必須）", Inputs(43_200_000),
                   offline_required=True, raw_data_may_leave=False, slo_ms=100.0,
                   distance_km=1000.0, model_class="classifier", device_name="端末D",
                   device=DEVICE_D, staff=3, api_priced=False,
                   # 384次元の float32 = 1,536 バイト。一次判定で疑いのある 5% だけ送る
                   payload_bytes=384 * 4, per_hour=60.0, devices=1000,
                   send_ratio=0.05),
}


# ---------------------------------------------------------------------------
# 3. ゲート（採点より先に効く）
# ---------------------------------------------------------------------------


def footprint_mb(model_class: str) -> float:
    return FOOTPRINTS[model_class].total_mb


def gate_reasons(sc: Scenario, option: str) -> list[str]:
    """失格の理由を**全部**返す（1つ目で打ち切らない）。

    打ち切ると「1つ直せば通る」と誤解される。セッション15 の互換性チェックと同じ規律。
    """
    reasons: list[str] = []
    cloud = option in (API, SELF)

    if cloud and sc.offline_required:
        reasons.append("オフライン必須（回線が切れたら止まる）")
    if cloud and not sc.raw_data_may_leave:
        reasons.append("生データを端末から出せない")

    # ハイブリッドは一次判定が端末で完結し、送るのは集約した特徴量だけなので
    # 上の2つのゲートを通る（セッション15 の集約指標と同じ考え方）。
    floor_ms = rtt_floor_ms(sc.distance_km) if cloud else 0.0
    if floor_ms >= sc.slo_ms:
        reasons.append(f"往復の下限 {floor_ms:.1f} ms が SLO {sc.slo_ms:.0f} ms に収まらない")

    if option in (EDGE, HYBRID):
        model = sc.model_class if option == EDGE else FRONT_MODEL
        ok, _margin = fits(sc.device, FOOTPRINTS[model])
        if not ok:
            reasons.append(
                f"{MODEL_LABELS[model]} が{sc.device_name} に載らない"
                f"（{footprint_mb(model):,.2f} MB ＞ {sc.device.limit_mb:,.2f} MB）")

    if STAFF_NEEDED[option] > sc.staff:
        reasons.append(f"運用人員 {sc.staff} 人 ＜ 必要 {STAFF_NEEDED[option]} 人")
    return reasons


def survivors(sc: Scenario) -> list[str]:
    return [o for o in OPTIONS if not gate_reasons(sc, o)]


def device_ratio(sc: Scenario, model_class: str | None = None) -> float:
    """端末の上限に対する超過倍率（1.0 を超えたら載らない）。"""
    return footprint_mb(model_class or sc.model_class) / sc.device.limit_mb


def mcu_flash_ratio(model_class: str = "classifier") -> float:
    """マイコン級（端末E）の Flash 上限に対する倍率。

    RAM 側は Flash で既に落ちているので 0 を渡している（判定は Flash だけで足りる）。
    """
    weights_kb = FOOTPRINTS[model_class].weights_mb * KB
    return fits_raw(DEVICE_E, weights_kb, 0.0).flash_use


# ---------------------------------------------------------------------------
# 4. 評価軸と重み付きスコア
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Axis:
    key: str
    name: str
    is_gate: bool


AXES: tuple[Axis, ...] = (
    Axis("offline", "オフライン耐性", True),
    Axis("privacy", "プライバシー", True),
    Axis("latency", "レイテンシ", True),
    Axis("model_size", "モデルの大きさの上限", True),
    Axis("unit_cost", "単価", False),
    Axis("ops", "運用負荷", False),
    Axis("scale", "スケールの上限", False),
    Axis("debug", "障害の切り分けやすさ", False),
)

SCORES: dict[str, dict[str, int]] = {
    # ③ 前提値：チームで合意して決める数字（1 が悪い・5 が良い）。
    # 単価だけは計算から出すので、ここには入れない。
    API: {"offline": 1, "privacy": 1, "latency": 2, "model_size": 5,
          "ops": 5, "scale": 5, "debug": 2},
    SELF: {"offline": 1, "privacy": 3, "latency": 3, "model_size": 3,
           "ops": 2, "scale": 2, "debug": 5},
    EDGE: {"offline": 5, "privacy": 5, "latency": 5, "model_size": 1,
           "ops": 1, "scale": 4, "debug": 2},
    # ハイブリッドは「良い方を採れる軸」が多く「悪い方が残る軸」が少ない。
    # だから採点表では構造的に強くなる。**スコアで決めない理由がここにある。**
    HYBRID: {"offline": 3, "privacy": 4, "latency": 5, "model_size": 5,
             "ops": 1, "scale": 4, "debug": 2},
}

COST_BUCKETS: tuple[tuple[float, int], ...] = ((0.5, 5), (1.0, 4), (2.0, 3), (5.0, 2))
"""API との比 → 単価のスコア。比が 5 を超えたら 1（それ以上は区別しない）。"""


@dataclass(frozen=True)
class Weights:
    key: str
    name: str
    values: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.values.values())


WEIGHTS: tuple[Weights, ...] = (
    Weights("重みA", "まず安く始める",
            {"unit_cost": 5, "latency": 2, "offline": 1, "privacy": 2,
             "model_size": 3, "ops": 4, "scale": 2, "debug": 1}),
    Weights("重みB", "止まらないことが第一",
            {"unit_cost": 2, "latency": 4, "offline": 5, "privacy": 5,
             "model_size": 1, "ops": 2, "scale": 1, "debug": 2}),
)


def cost_ratio(sc: Scenario, option: str, mode: str = MODE_AUTO) -> float:
    """API を 1.0 としたときの相対単価。

    エッジは推論の変動費が 0（**端末は既にある前提**。新規調達は別会計で、
    本書はその見積もりを扱わない）。ハイブリッドは端末で完結しなかったぶん
    だけクラウドに行くので (1 − EDGE_SHARE) 倍になる。
    """
    if option == API:
        return 1.0
    if option == EDGE:
        return 0.0
    if option == HYBRID:
        return 1.0 - EDGE_SHARE
    if not sc.api_priced:
        raise ValueError(f"{sc.key} には本書のトークン単価の形が当てはまりません")
    return self_cost_per_1k(sc.inputs, mode) / api_cost_per_1k(sc.inputs)


def cost_score(ratio: float) -> int:
    for limit, score in COST_BUCKETS:
        if ratio <= limit:
            return score
    return 1


def score_of(sc: Scenario, option: str, axis_key: str,
             mode: str = MODE_AUTO) -> int:
    if axis_key == "unit_cost":
        return cost_score(cost_ratio(sc, option, mode))
    return SCORES[option][axis_key]


def weighted_score(sc: Scenario, option: str, w: Weights,
                   mode: str = MODE_AUTO) -> float:
    """5点満点に正規化した総合点。**順位を作るためではなく、漏れを見るために出す。**"""
    if gate_reasons(sc, option):
        raise ValueError(f"{option} はゲートで失格しています（採点しません）")
    total = sum(w.values[a.key] * score_of(sc, option, a.key, mode) for a in AXES)
    return total / w.total


def ranking(sc: Scenario, w: Weights, mode: str = MODE_AUTO) -> list[tuple[str, float]]:
    rows = [(o, weighted_score(sc, o, w, mode)) for o in survivors(sc)]
    return sorted(rows, key=lambda kv: kv[1], reverse=True)


# ---------------------------------------------------------------------------
# 5. 感度分析（どの前提が結論を変えるか）
# ---------------------------------------------------------------------------

SENSITIVITY: tuple[tuple[str, str, float], ...] = (
    ("月間リクエスト数", "monthly_requests", 1.0),
    ("インスタンス時間単価", "hourly_cost", 1.0),
    # 動作点は 1.13 rps だが、判断に使うのはヘッドルームを引いた 1本 0.791 rps
    # なので、表示だけそちらに換算する（倍率は同じ）。
    ("動作点の rps（1本）", "point_rps", 1.0 - HEADROOM),
    ("API の出力トークン単価", "api_output_price_per_1m", 1.0),
    ("1リクエストの出力トークン数", "output_tokens", 1.0),
    ("1リクエストの入力トークン数", "input_tokens", 1.0),
    ("ピークが平均の何倍か", "peak_factor", 1.0),
)


def _verdict(inp: Inputs, field: str, multiplier: float, mode: str) -> bool:
    return self_is_cheaper(replace(inp, **{field: getattr(inp, field) * multiplier}),
                           mode)


SCAN_SPAN = 0.5
"""感度を調べる幅（現在の値の ±50%）。この範囲で反転しなければ「堅い」と扱う。"""


def _flip_side(inp: Inputs, field: str, mode: str, direction: int,
               step: float = 0.0005, span: float = SCAN_SPAN) -> float | None:
    """`direction`（+1 で増やす / −1 で減らす）に走査して、最初に反転する倍率を返す。

    **二分探索だけで済ませてはいけない。** 単価は月間件数に対して単調ではなく
    （台数が1本増える瞬間に跳ね上がる）、素朴な二分探索では境目を取り違える。
    そこで細かく走査して境目を挟み込み、そのあとで詰めている。
    """
    base = self_is_cheaper(inp, mode)
    steps = round(span / step)
    prev = 1.0
    for i in range(1, steps + 1):
        m = 1.0 + direction * step * i
        if m <= 0:
            return None
        if _verdict(inp, field, m, mode) != base:
            lo, hi = prev, m       # lo は base 側・hi は反転側
            for _ in range(80):
                mid = (lo + hi) / 2.0
                if _verdict(inp, field, mid, mode) != base:
                    hi = mid
                else:
                    lo = mid
            return hi
        prev = m
    return None


@dataclass(frozen=True)
class Flip:
    """1つの前提について、結論が反転する点。"""

    label: str
    field: str
    base_value: float
    down: float | None
    up: float | None

    @property
    def nearest(self) -> float | None:
        """1.0 にいちばん近い反転倍率（どちら側でも）。"""
        sides = [m for m in (self.down, self.up) if m is not None]
        return min(sides, key=lambda m: abs(m - 1.0)) if sides else None

    @property
    def nearest_pct(self) -> float | None:
        m = self.nearest
        return None if m is None else (m - 1.0) * 100.0

    @property
    def fragility(self) -> float:
        """脆さ。小さいほど脆い。反転しない前提は無限に堅い。"""
        pct = self.nearest_pct
        return float("inf") if pct is None else abs(pct)

    def value_at(self, side: str) -> float | None:
        m = self.down if side == "down" else self.up
        return None if m is None else self.base_value * m


_FLIP_CACHE: dict[tuple[str, str, Inputs], list[Flip]] = {}


def flips(sc: Scenario, mode: str = MODE_AUTO) -> list[Flip]:
    """全部の前提について、両側の反転点を求める。走査が重いので結果を覚えておく。"""
    if not sc.api_priced:
        raise ValueError(f"{sc.key} は単価の比較対象が無いので感度分析をしません")
    key = (sc.key, mode, sc.inputs)
    cached = _FLIP_CACHE.get(key)
    if cached is not None:
        return cached
    out: list[Flip] = []
    for label, field, factor in SENSITIVITY:
        out.append(Flip(label, field, getattr(sc.inputs, field) * factor,
                        _flip_side(sc.inputs, field, mode, -1),
                        _flip_side(sc.inputs, field, mode, +1)))
    _FLIP_CACHE[key] = out
    return out


def fragility_order(sc: Scenario, mode: str = MODE_AUTO) -> list[Flip]:
    """脆い順に並べる。**上の1〜2本がそのまま再判断のトリガーになる。**"""
    return sorted(flips(sc, mode), key=lambda f: f.fragility)


# ---------------------------------------------------------------------------
# 6. 移行計画
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Stage:
    """移行の1段。**進む条件と撤退条件を必ず対で持つ。**"""

    name: str
    ratio: float
    observe_days: int
    advance: str
    retreat: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.ratio <= 1.0:
            raise ValueError("ratio は 0 以上 1 以下です")
        if self.observe_days <= 0:
            raise ValueError("observe_days は 1 日以上です（観察しない段は作らない）")
        if not self.advance or not self.retreat:
            raise ValueError("進む条件と撤退条件の両方が必要です")


STAGES: tuple[Stage, ...] = (
    Stage("第0段 影運転", 0.00, 3,
          "応答の等価性が確認できる／エラー率が API 側以下", "左の条件を満たさない"),
    Stage("第1段", 0.01, 2,
          "TTFT p95 ≦ 1,000 ms かつ 総時間 p95 ≦ 3,000 ms",
          "TTFT p95 ＞ 1,000 ms が15分継続"),
    Stage("第2段", 0.10, 3,
          "＋ 1000リクエスト単価が試算の1.5倍以内",
          "5xx 率が API 時代の2倍超が15分継続"),
    Stage("第3段", 0.50, 7, "＋ キュー長が 1.0 件/本 以下", "同上"),
    Stage("第4段", 1.00, 14, "＋ 撤退条件に一度も触れない", "同上"),
)

DECISIONS = ("進める", "進めない", "戻す")
"""判断は3値にする。2値にすると「進めない」が消え、悪化していない段で進めてしまう。"""


def observe_days_total(stages: tuple[Stage, ...] = STAGES) -> int:
    return sum(s.observe_days for s in stages)


def ratios_monotonic(stages: tuple[Stage, ...] = STAGES) -> bool:
    return all(a.ratio < b.ratio for a, b in zip(stages, stages[1:]))


# ---------------------------------------------------------------------------
# 7. 再判断のトリガー
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Trigger:
    """再判断の起動条件。**5要素すべてが埋まっていないと判定できない。**"""

    metric: str
    threshold: str
    window: str
    action: str
    owner: str

    def __post_init__(self) -> None:
        missing = [name for name, value in (("指標", self.metric),
                                            ("しきい値", self.threshold),
                                            ("観測期間", self.window),
                                            ("アクション", self.action),
                                            ("担当", self.owner)) if not value]
        if missing:
            raise ValueError("トリガーに欠けている要素があります: " + " / ".join(missing))


def triggers_for(sc: Scenario, mode: str = MODE_AUTO) -> tuple[Trigger, ...]:
    """感度分析の反転値から、そのままトリガーを作る。

    **しきい値を人が思いつきで決めない**のが要点。数字は全部計算から来る。
    """
    be = breakeven(sc.inputs.assumptions(mode))
    order = {f.field: f for f in flips(sc, mode)}
    cheaper = self_is_cheaper(sc.inputs, mode)
    out: list[Trigger] = [
        # 損益分岐は必ず計算できるので、向きだけを結論に合わせる。
        Trigger("月間リクエスト数（BI 月次）",
                _man(be.requests_per_hour * HOURS_PER_MONTH)
                + ("を下回る" if cheaper else "を超える"),
                "2か月続けて",
                "クラウドAPI への切り戻しを試算" if cheaper
                else "自前ホスティングの試算をやり直す", "インフラ課"),
    ]
    up_flip = order["monthly_requests"].value_at("up")
    if up_flip is not None:
        out.append(Trigger("月間リクエスト数（BI 月次）", f"{_man(up_flip)}を超える",
                           "1か月", "台数が1本増える前に単価を再計算", "インフラ課"))
    rps_flip = order["point_rps"].value_at("down")
    out.append(Trigger(
        "動作点の rps（1本）",
        f"{rps_flip:.4f} を下回る" if rps_flip is not None
        else f"{sc.inputs.per_instance_rps:.4f} から 5% 以上下がる",
        "モデル更新のたびに測る",
        "負荷試験で測り、容量計画とコスト試算を作り直す", "インフラ課"))
    api_flip = order["api_output_price_per_1m"].value_at("down")
    out.append(Trigger(
        "API の公表単価",
        f"出力トークン単価が {api_flip:.2f} 以下になる" if api_flip is not None
        else "改定が公表される", "随時", "3択を再判断する", "インフラ課"))
    out.append(Trigger("利用率（セッション10 のメトリクス）",
                       f"{be.utilization * 100:.1f}% を"
                       + ("下回る" if cheaper else "上回る"), "2週間続けて",
                       "停止スケジュールか API 併用を検討" if cheaper
                       else "自前ホスティングの試算をやり直す", "当番"))
    return tuple(out)


# ---------------------------------------------------------------------------
# 8. 意思決定文書
# ---------------------------------------------------------------------------

DOC_SECTIONS: tuple[str, ...] = (
    "1. 前提", "2. 選択肢", "3. 評価軸と重み", "4. 数字", "5. 結論",
    "6. 再判断のトリガー", "7. 前提が変わったときの再計算手順",
)


def missing_sections(text: str) -> list[str]:
    """欠けている欄を返す。**空なら文書として成立している。**"""
    return [s for s in DOC_SECTIONS if f"## {s}" not in text]


def _pct(ratio: float) -> str:
    return f"{ratio * 100:.1f}%"


def _num(value: float) -> str:
    """桁の違う数を素直に書く（1,000万件も 0.7716 も同じ関数で扱う）。"""
    return f"{value:,.0f}" if abs(value) >= 10000 else f"{value:.4g}"


def _man(count: float) -> str:
    """件数を万件で書く。"""
    return f"{count / 10000:,.1f}万件"


def decisive_axes(sc: Scenario, option: str, w: Weights,
                  mode: str = MODE_AUTO, n: int = 2) -> list[str]:
    """総合点への寄与が大きい軸。**結論に書くのはこれで、総合点ではない。**"""
    rows = [(a.name, w.values[a.key] * score_of(sc, option, a.key, mode))
            for a in AXES]
    return [name for name, _ in sorted(rows, key=lambda kv: kv[1],
                                       reverse=True)[:n]]


def document_markdown(sc: Scenario, w: Weights | None = None,
                      mode: str = MODE_AUTO) -> str:
    """引き継げる成果物。**前提・数字・トリガー・再計算手順を必ず含める。**"""
    w = w or WEIGHTS[0]
    inp = sc.inputs
    alive = survivors(sc)
    rows = ranking(sc, w, mode)
    top = rows[0][0] if rows else "なし"
    lines = [
        f"# 意思決定：どこで推論するか（{sc.name}）",
        "",
        "作成 2026-08-15 / 作成者 インフラ課 / 次回棚卸し 3か月後",
        "",
        "## 1. 前提",
        "",
        f"測定条件：{MEASURED_CONDITIONS}",
        "",
        "**金額はすべて相対単位です**（インスタンス1時間の値段を 1 と置く）。"
        "自分の契約の値を入れると自分の通貨の答えになります。",
        "",
        "| 入力 | 値 | 種別 |",
        "| :--- | --: | :--- |",
        f"| 月間リクエスト数 | {inp.monthly_requests:,.0f} 件 | ③前提値 |",
        f"| 動作点 | 並列{POINT.concurrency}・{inp.point_rps} rps・"
        f"TTFT p95 {POINT.ttft_p95_ms:.0f} ms | ①実測 |",
        f"| 1本の安全な能力 | {inp.per_instance_rps:.3f} rps"
        f"（ヘッドルーム {_pct(HEADROOM)}） | ①実測から計算 |",
        f"| ピーク倍率 | {inp.peak_factor} 倍 | ③前提値（**未実測**。"
        "アクセスログから測る） |",
        f"| API のトークン単価 | 入力 {inp.api_input_price_per_1m} / "
        f"出力 {inp.api_output_price_per_1m} | ③前提値（契約） |",
        f"| 1リクエストのトークン | 入力 {inp.input_tokens:.0f} / "
        f"出力 {inp.output_tokens:.0f} | ③前提値 |",
        f"| 運用人員 | {sc.staff} 人 | ③前提値 |",
        f"| SLO（一次応答） | {sc.slo_ms:.0f} ms | 要件 |",
        f"| 対象端末 | {sc.device_name}（上限 {sc.device.limit_mb:,.2f} MB） | ③前提値 |",
        "",
        "## 2. 選択肢",
        "",
        "| 案 | 判定 | 理由 |",
        "| :--- | :--- | :--- |",
    ]
    for option in OPTIONS:
        reasons = gate_reasons(sc, option)
        verdict = "通過" if not reasons else "失格"
        lines.append(f"| {option} | {verdict} | "
                     + ("ゲートをすべて通過" if not reasons
                        else "／".join(reasons)) + " |")
    lines += [
        "",
        "## 3. 評価軸と重み",
        "",
        f"ゲート4軸（オフライン耐性・プライバシー・レイテンシ・モデルの大きさ）"
        f"＋重み付け4軸。採用する重みは **{w.key}（{w.name}）** "
        "（要件から決める。案を見てから決めない）。",
        "",
        "| 案 | " + " | ".join(f"{v.key}" for v in WEIGHTS) + " |",
        "| :--- | " + " | ".join("--:" for _ in WEIGHTS) + " |",
    ]
    for option in alive:
        cells = " | ".join(f"{weighted_score(sc, option, v, mode):.2f}"
                           for v in WEIGHTS)
        lines.append(f"| {option} | {cells} |")
    lines += ["", "## 4. 数字", ""]
    if sc.api_priced:
        be = breakeven(inp.assumptions(mode))
        lines += [
            f"- API {api_cost_per_1k(inp):.4f} ／ 自前（{MODE_AUTO}"
            f"{inp.instances(MODE_AUTO)}本）{self_cost_per_1k(inp, MODE_AUTO):.4f}"
            f" ／ 自前（{MODE_FIXED}{inp.instances(MODE_FIXED)}本）"
            f"{self_cost_per_1k(inp, MODE_FIXED):.4f}",
            f"- 損益分岐 {be.requests_per_hour:,.2f} 件/時"
            f"（月 {_man(be.requests_per_hour * HOURS_PER_MONTH)}）。"
            f"能力 {be.capacity_per_hour:,.1f} 件/時 の"
            + ("内側" if be.achievable else "外側"),
            f"- 利用率 {_pct(inp.utilization(mode))}"
            f"（上限 {_pct(MAX_UTILIZATION)}）",
        ]
        top_flip = fragility_order(sc, mode)[0]
        if top_flip.nearest_pct is None:
            lines.append(f"- 感度：どの前提も ±{_pct(SCAN_SPAN)} の範囲では"
                         "結論を反転させない（**桁で開いた差は前提が動いても消えない**）")
        else:
            lines.append(f"- 感度：いちばん脆い前提は「{top_flip.label}」で "
                         f"{top_flip.nearest_pct:+.1f}% で反転する")
    else:
        lines += [
            "- 単価の比較は不要（ゲートでクラウド側の2案が失格）",
            f"- 端末に載るか：{MODEL_LABELS[sc.model_class]} "
            f"{footprint_mb(sc.model_class):,.2f} MB ≦ {sc.device_name} の上限 "
            f"{sc.device.limit_mb:,.2f} MB",
            f"- 往復の下限：{rtt_floor_ms(sc.distance_km):.1f} ms"
            f"（SLO {sc.slo_ms:.0f} ms の "
            f"{_pct(rtt_floor_ms(sc.distance_km) / sc.slo_ms)}）",
        ]
        if sc.payload_bytes > 0:
            raw_gb = monthly_upload_gb(sc.payload_bytes, sc.per_hour, sc.devices)
            sent_gb = monthly_upload_gb(sc.payload_bytes, sc.per_hour, sc.devices,
                                        send_ratio=sc.send_ratio)
            lines.append(
                f"- 通信量：生データ {raw_gb:,.2f} GB/月 → 一次判定で "
                f"{_pct(sc.send_ratio)} だけ送れば {sent_gb:,.2f} GB/月"
                f"（{raw_gb / sent_gb:,.0f} 分の1）")
    lines += [
        "",
        "## 5. 結論",
        "",
        f"**{top}** を採る（{w.key} で1位）。決め手になった軸は"
        + "・".join(f"「{name}」" for name in decisive_axes(sc, top, w, mode))
        + "。",
        "**総合点は根拠ではありません。** 決め手の軸とその数字で判断しています。",
        "",
        "## 6. 再判断のトリガー",
        "",
        "| # | 指標 | しきい値 | 観測期間 | アクション | 担当 |",
        "| :-- | :--- | :--- | :--- | :--- | :--- |",
    ]
    if sc.api_priced:
        for i, t in enumerate(triggers_for(sc, mode), start=1):
            lines.append(f"| {i} | {t.metric} | {t.threshold} | {t.window} | "
                         f"{t.action} | {t.owner} |")
    else:
        lines.append("| 1 | 生データの社外送信の可否 | 許可が下りる | 随時 | "
                     "最も硬いゲートが消えるので全体を再判断 | インフラ課 |")
    lines += [
        "",
        "## 7. 前提が変わったときの再計算手順",
        "",
        "1. `src/session04/sweep.py` で同時実行を振り、**SLO を満たす最大の点**"
        "を動作点に採る",
        "2. `src/session09/plan.py` で台数を数え直す",
        "3. `src/session10/cost_report.py` で単価と損益分岐を出し直す",
        f"4. `src/session16/decision.py --scenario {sc.key} --markdown` で"
        "本文書を再生成する",
        "5. 反転値が変わったら、6章のトリガーのしきい値を書き換える",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 9. 表示
# ---------------------------------------------------------------------------


def report(sc: Scenario, mode: str = MODE_AUTO) -> str:
    inp = sc.inputs
    lines = [f"=== {sc.key.upper()}: {sc.name} ===",
             f"  測定条件      : {MEASURED_CONDITIONS}",
             f"  月間件数      : {inp.monthly_requests:,.0f} 件"
             f"（{inp.requests_per_hour:,.2f} 件/時・平均 {inp.avg_rps:.4f} rps）",
             f"  1本の能力     : {inp.per_instance_rps:.3f} rps"
             f"（動作点 {inp.point_rps} rps × ヘッドルーム {_pct(HEADROOM)} を引く）",
             "",
             "  [ゲート] 満たさなければ失格。点数で埋め合わせられない",
             "  | 案 | 判定 | 理由（全部） |",
             "  | :--- | :--- | :--- |"]
    for option in OPTIONS:
        reasons = gate_reasons(sc, option)
        lines.append(f"  | {option} | {'通過' if not reasons else '失格'} | "
                     + ("—" if not reasons else "／".join(reasons)) + " |")
    lines.append(f"  生き残った案  : {'、'.join(survivors(sc)) or 'なし'}")

    if sc.api_priced:
        be = breakeven(inp.assumptions(mode))
        n_fixed, n_auto = inp.instances(MODE_FIXED), inp.instances(MODE_AUTO)
        lines += [
            "",
            "  [単価] 同じ件数でも運転の仕方で変わる",
            f"  単価: 固定{n_fixed}本 {self_cost_per_1k(inp, MODE_FIXED):.4f}"
            f" / オートスケール{n_auto}本 {self_cost_per_1k(inp, MODE_AUTO):.4f}"
            f" / API {api_cost_per_1k(inp):.4f}",
            f"  利用率: 固定 {_pct(inp.utilization(MODE_FIXED))}"
            f" / オートスケール {_pct(inp.utilization(MODE_AUTO))}"
            f"（上限 {_pct(MAX_UTILIZATION)}）",
            f"  比: {cost_ratio(sc, SELF, mode):.2f} 倍（自前 ÷ API）",
            f"  損益分岐: {be.requests_per_hour:,.2f} 件/時"
            f"（月 {_man(be.requests_per_hour * HOURS_PER_MONTH)}"
            f"・利用率 {be.utilization * 100:.1f}%）",
            f"  能力: {be.capacity_per_hour:,.1f} 件/時 → 分岐点は"
            + ("内側（達成できる）" if be.achievable else "外側（自前は安くならない）"),
            "",
            "  [感度] どの前提がどれだけ動くと結論が反転するか",
            "  | 前提 | いまの値 | 減る側 | 増える側 | いちばん近い反転 |",
            "  | :--- | --: | --: | --: | --: |",
        ]
        for f in fragility_order(sc, mode):
            down = "—" if f.down is None else _num(f.value_at("down"))
            up = "—" if f.up is None else _num(f.value_at("up"))
            near = "反転しない" if f.nearest_pct is None else f"{f.nearest_pct:+.1f}%"
            lines.append(f"  | {f.label} | {_num(f.base_value)} | {down} | {up} | "
                         f"{near} |")
        if fragility_order(sc, mode)[0].nearest_pct is None:
            lines.append(f"  -> どの前提も ±{_pct(SCAN_SPAN)} では反転しない。"
                         "**桁で開いた差は前提が動いても消えない**")
        else:
            lines.append("  -> 上位2つは同じ境目（台数が1本増える点）を"
                         "別の側から見たもの。**価格ではない**")

    alive = survivors(sc)
    if alive:
        lines += ["", "  [スコア] 順位を作る道具ではなく、漏れを見る道具",
                  "  | 案 | " + " | ".join(f"{w.key}（{w.name}）" for w in WEIGHTS)
                  + " |",
                  "  | :--- | " + " | ".join("--:" for _ in WEIGHTS) + " |"]
        for option in alive:
            cells = " | ".join(f"{weighted_score(sc, option, w, mode):.2f}"
                               for w in WEIGHTS)
            lines.append(f"  | {option} | {cells} |")
        tops = [ranking(sc, w, mode)[0] for w in WEIGHTS]
        lines.append("  1位（重みごと）: "
                     + " / ".join(f"{w.key}: {name} {score:.2f}"
                                  for w, (name, score) in zip(WEIGHTS, tops)))
        if len({name for name, _ in tops}) == 1:
            lines.append(f"  -> どの重みでも {tops[0][0]} が1位。"
                         "**採点表がその案を構造的に有利にしていないか疑う**")
        else:
            lines.append("  -> 重みで1位が入れ替わる。"
                         "**スコアは根拠にならない。決め手の軸を書く**")
    return "\n".join(lines)


def migration_report() -> str:
    lines = ["=== 移行計画（段階と撤退条件）===",
             f"  判断は{len(DECISIONS)}値: " + "／".join(DECISIONS),
             "  | 段 | 自前へ | 観察 | 進む条件 | 撤退条件 |",
             "  | :--- | --: | --: | :--- | :--- |"]
    for s in STAGES:
        lines.append(f"  | {s.name} | {s.ratio:.0%} | {s.observe_days}日 | "
                     f"{s.advance} | {s.retreat} |")
    lines += [f"  観察期間の合計: {observe_days_total()} 日",
              "  撤退の操作: ゲートウェイの自前向け比率を 0 に戻す（1手順・数秒）",
              "  エッジへ流用するとき: 段の刻みを台数（1/9/90/900）にし、"
              "各段24時間観察する（切り戻しに 1,404.8 秒以上かかるため）"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="どこで推論するかを決める")
    parser.add_argument("--scenario", choices=[*sorted(SCENARIOS), "all"],
                        default="all")
    parser.add_argument("--weights", choices=[w.key for w in WEIGHTS],
                        default=WEIGHTS[0].key)
    parser.add_argument("--mode", choices=[MODE_AUTO, MODE_FIXED], default=MODE_AUTO)
    parser.add_argument("--markdown", action="store_true",
                        help="意思決定文書（Markdown）を出す")
    parser.add_argument("--out", help="Markdown を書き出すパス")
    args = parser.parse_args(argv)

    keys = sorted(SCENARIOS) if args.scenario == "all" else [args.scenario]
    weights = next(w for w in WEIGHTS if w.key == args.weights)

    if args.markdown or args.out:
        if len(keys) != 1:
            print("--markdown は --scenario で1つ選んでください", file=sys.stderr)
            return 2
        body = document_markdown(SCENARIOS[keys[0]], weights, args.mode)
        print(body)
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(body + "\n", encoding="utf-8")
            print(f"\n-> {out}")
        return 0

    for i, key in enumerate(keys):
        if i:
            print()
        print(report(SCENARIOS[key], args.mode))
    print()
    print(migration_report())
    return 0


if __name__ == "__main__":
    sys.exit(main())
