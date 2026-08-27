#!/usr/bin/env python3
"""単価で語る（セッション10）。

「高い」「安い」を式で言えるようにするための道具。**特定クラウドの価格は書かない。**
インスタンス時間単価と API のトークン単価は**読者が入れる値**で、既定値は
「インスタンス1時間の値段を 1 と置いた相対単位」である（価格は本書の中で最も速く
古くなる情報なので、本書が提供するのは式と感度分析だけにしてある）。

    python src/session10/cost_report.py
    python src/session10/cost_report.py --utilization 0.2
    python src/session10/cost_report.py --hourly 0.4 --instances 7
    python src/session10/cost_report.py --out reports/cost_report.md

計算はすべて決定的で、Prometheus もネットワークも要らない。動作点（rps）と
レイテンシはセッション4・9 の実測値（`src/session09/scaling.py`）を引いている。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from infrakit.cost import (  # noqa: E402
    HostedAPI, SelfHosted, breakeven_requests_per_hour, utilization_table,
)
from src.session09.scaling import (  # noqa: E402
    MEASURED_CONDITIONS, POINTS, best_point, plan_capacity, saturation_concurrency,
)

HOURS_PER_WEEK = 168.0
"""1週間の時間数。停止スケジュールの計算に使う。"""

BUSINESS_HOURS_PER_WEEK = 60.0
"""平日 8:00-20:00（12 時間 × 5 日）。**要件であって実測ではない。**"""

HEADROOM = 0.30
"""セッション9 で空けたヘッドルーム。利用率の実務上の上限はこの裏返しになる。"""

MAX_UTILIZATION = 1.0 - HEADROOM

UTILIZATIONS: tuple[float, ...] = (0.1, 0.2, 0.5, 0.7, 0.9)
"""感度を見るために振る利用率。"""

CACHE_HIT_RATE = 0.30
"""応答キャッシュのヒット率の例（**前提値**）。単価はそのまま (1 − h) 倍になる。"""

QUANT_TOTAL_MS = {"q4_k_m": 1051.0, "q8_0": 730.0}
"""量子化別の総時間 p50（セッション3 の実測・スロット1・並列1・max_tokens=48）。"""

PLAN = plan_capacity()
"""セッション9 の容量計画。停止スケジュールの待ち時間（56.6 秒）を引くために使う。"""

SLO_POINT = best_point()
"""SLO を満たす中で rps が最大の動作点（並列2 / 1.13 rps）。**単価の分母はこれ。**"""

_SAT = saturation_concurrency()
SATURATED_POINT = next(p for p in POINTS if p.concurrency == _SAT)
"""飽和した点（並列4 / 1.15 rps）。単価は少し良く見えるが体感は壊れている。"""


# ---------------------------------------------------------------------------
# 1. 前提（読者が入れる値）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Assumptions:
    """コスト試算の入力。**どれか1つでも変われば答えも変わる。**

    `hourly_cost` と API の単価は相対単位である。自分の契約の値を入れると、
    そのまま自分の通貨での答えになる（式は同じ）。
    """

    hourly_cost: float = 1.0            # インスタンス1台の1時間あたり（読者が入れる）
    instances: int = 3                  # 台数（セッション9 の minReplicas）
    rps_per_instance: float = SLO_POINT.throughput_rps   # 実測（SLO を満たす動作点）
    utilization: float = MAX_UTILIZATION                 # 実際に埋まっている割合
    api_input_price_per_1m: float = 0.8    # 1Mトークンあたり（読者が入れる）
    api_output_price_per_1m: float = 3.2
    input_tokens: float = 300.0            # 1リクエストの入力（自分のプロンプトで実測する）
    output_tokens: float = 48.0            # 測定条件と同じ max_tokens=48

    def __post_init__(self) -> None:
        if self.hourly_cost < 0:
            raise ValueError("hourly_cost は 0 以上を指定してください")
        if self.instances < 1:
            raise ValueError("instances は 1 以上を指定してください")
        if self.rps_per_instance <= 0:
            raise ValueError("rps_per_instance は正の数を指定してください")
        if not 0.0 < self.utilization <= 1.0:
            raise ValueError("utilization は 0 より大きく 1 以下で指定してください")
        if min(self.api_input_price_per_1m, self.api_output_price_per_1m) < 0:
            raise ValueError("API の単価は 0 以上を指定してください")
        if min(self.input_tokens, self.output_tokens) < 0:
            raise ValueError("トークン数は 0 以上を指定してください")

    # --- 自前ホスティング -------------------------------------------------
    def self_hosted(self, utilization: float | None = None) -> SelfHosted:
        return SelfHosted(self.hourly_cost, self.instances, self.rps_per_instance,
                          self.utilization if utilization is None else utilization)

    @property
    def cost_per_hour(self) -> float:
        """1時間の固定費。**利用率に関係なく発生する**のがこの費用の性質である。"""
        return self.hourly_cost * self.instances

    # --- クラウドAPI -------------------------------------------------------
    def api(self) -> HostedAPI:
        return HostedAPI(self.api_input_price_per_1m, self.api_output_price_per_1m,
                         self.input_tokens, self.output_tokens)


def requests_per_hour(a: Assumptions, utilization: float | None = None) -> float:
    """1時間に処理できたリクエスト数（単価の分母）。"""
    return a.self_hosted(utilization).requests_per_hour


def cost_per_1k(a: Assumptions, utilization: float | None = None) -> float:
    """1000リクエスト単価。台数は式で約分されるので、台数を変えても動かない。"""
    return a.self_hosted(utilization).cost_per_1k_requests


def capacity_requests_per_hour(a: Assumptions) -> float:
    """ヘッドルームを残したまま SLO を守って捌ける上限（1時間）。"""
    return requests_per_hour(a, MAX_UTILIZATION)


# ---------------------------------------------------------------------------
# 2. 表示のための小道具
# ---------------------------------------------------------------------------


def _n(value: float) -> str:
    """相対単位の数を素直に書く（1.0 は「1」、0.126 は「0.126」）。"""
    return f"{value:.6g}"


def _pct(ratio: float) -> str:
    return f"{ratio * 100:g}%"


def _delta(pct: float) -> str:
    """変化率。ぴったり 0 のときは符号を付けない（「動かない」ことを示す）。"""
    return "0.0%" if abs(pct) < 1e-12 else f"{pct:+.1f}%"


# ---------------------------------------------------------------------------
# 3. 利用率・ヘッドルーム
# ---------------------------------------------------------------------------


def utilization_rows(a: Assumptions,
                     utilizations: tuple[float, ...] = UTILIZATIONS) -> list[dict]:
    """利用率を振った表。`infrakit.cost.utilization_table` に比の列を足す。"""
    base = cost_per_1k(a)
    rows = utilization_table(a.self_hosted(), utilizations)
    for row in rows:
        row["ratio_to_base"] = row["cost_per_1k_requests"] / base
    return rows


def headroom_price(a: Assumptions) -> dict:
    """ヘッドルームの値段（利用率 100% に対する割高）。"""
    full = cost_per_1k(a, 1.0)
    capped = cost_per_1k(a, MAX_UTILIZATION)
    return {"full": full, "capped": capped, "ratio": capped / full}


# ---------------------------------------------------------------------------
# 4. 停止スケジュール
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Schedule:
    """1週間のうち何時間・何本動かすか。"""

    label: str
    replicas_on: int
    replicas_off: int
    hours_on: float = BUSINESS_HOURS_PER_WEEK
    note: str = ""

    @property
    def hours_off(self) -> float:
        return HOURS_PER_WEEK - self.hours_on

    @property
    def instance_hours(self) -> float:
        return self.replicas_on * self.hours_on + self.replicas_off * self.hours_off

    def saving_ratio(self, baseline: float) -> float:
        return 0.0 if baseline <= 0 else 1.0 - self.instance_hours / baseline


def schedules(a: Assumptions) -> list[Schedule]:
    """常時稼働・夜間縮退・夜間停止の3案。待ち時間はセッション9 の遅れを引く。"""
    wait_s = PLAN.cold_start_wait_s
    return [
        Schedule(f"常時 {a.instances} 本", a.instances, a.instances,
                 HOURS_PER_WEEK, "0 秒"),
        Schedule("夜間・週末は 1 本", a.instances, 1, BUSINESS_HOURS_PER_WEEK,
                 "0 秒（1本は残る）"),
        Schedule("夜間・週末は 0 本", a.instances, 0, BUSINESS_HOURS_PER_WEEK,
                 f"{wait_s:.1f} 秒（TTFT SLO の {PLAN.slo_multiple:.1f} 倍）"),
    ]


# ---------------------------------------------------------------------------
# 5. 損益分岐
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Breakeven:
    """自前が API より安くなる境目。

    **rps も利用率も式に現れない。** 動くのは「その件数を捌けるか」だけである。
    """

    api_per_request: float
    api_per_1k: float
    requests_per_hour: float
    capacity_per_hour: float
    utilization: float
    self_cost_per_1k: float

    @property
    def rps(self) -> float:
        return self.requests_per_hour / 3600.0

    @property
    def achievable(self) -> bool:
        """ヘッドルームを残したまま分岐点を超えられるか。"""
        return self.requests_per_hour <= self.capacity_per_hour

    @property
    def self_hosting_cheaper_now(self) -> bool:
        return self.self_cost_per_1k < self.api_per_1k


def breakeven(a: Assumptions) -> Breakeven:
    api = a.api()
    per_request = api.cost_per_1k_requests / 1000.0
    rph = breakeven_requests_per_hour(a.self_hosted(), api)
    full = requests_per_hour(a, 1.0)
    return Breakeven(per_request, api.cost_per_1k_requests, rph,
                     capacity_requests_per_hour(a),
                     rph / full if full else float("inf"), cost_per_1k(a))


# ---------------------------------------------------------------------------
# 6. 感度分析
# ---------------------------------------------------------------------------

SENSITIVITY: tuple[tuple[str, str], ...] = (
    ("インスタンス時間単価", "hourly_cost"),
    ("動作点の rps", "rps_per_instance"),
    ("利用率", "utilization"),
    ("API の出力トークン単価", "api_output_price_per_1m"),
    ("1リクエストの出力トークン数", "output_tokens"),
)


def sensitivity_rows(a: Assumptions, bump: float = 0.10) -> list[dict]:
    """各入力を `bump` だけ増やしたときの単価と損益分岐の変化率。"""
    base_cost = cost_per_1k(a)
    base_break = breakeven(a).requests_per_hour
    rows: list[dict] = []
    for label, field_name in SENSITIVITY:
        value = getattr(a, field_name) * (1.0 + bump)
        variant = replace(a, **{field_name: value})
        rows.append({
            "label": label,
            "cost_delta": cost_per_1k(variant) / base_cost - 1.0,
            "breakeven_delta": breakeven(variant).requests_per_hour / base_break - 1.0,
        })
    return rows


# ---------------------------------------------------------------------------
# 7. 単価と体感の取引・「高い」の分解
# ---------------------------------------------------------------------------


def saturation_tradeoff(a: Assumptions) -> dict:
    """飽和させたときの「1.7% 安く、体感は 20.6 倍悪い」を数字で出す。"""
    slo, sat = SLO_POINT, SATURATED_POINT
    saturated = replace(a, rps_per_instance=sat.throughput_rps)
    cost_slo, cost_sat = cost_per_1k(a), cost_per_1k(saturated)
    return {"rps_ratio": sat.throughput_rps / slo.throughput_rps,
            "cost_slo": cost_slo, "cost_sat": cost_sat,
            "cost_ratio": cost_sat / cost_slo,
            "saving_pct": (1.0 - cost_sat / cost_slo) * 100.0,
            "ttft_slo_ms": slo.ttft_p95_ms, "ttft_sat_ms": sat.ttft_p95_ms,
            "ttft_ratio": sat.ttft_p95_ms / slo.ttft_p95_ms}


def levers(a: Assumptions) -> list[dict]:
    """施策 → 単価の倍率 → 体感への影響。**倍率はすべて式か実測から出す。**"""
    low, high = 0.2, MAX_UTILIZATION
    quant = QUANT_TOTAL_MS["q8_0"] / QUANT_TOTAL_MS["q4_k_m"]
    trade = saturation_tradeoff(a)
    return [
        {"action": f"利用率を {_pct(low)} から {_pct(high)} へ",
         "ratio": cost_per_1k(a, high) / cost_per_1k(a, low),
         "felt": "変わらない（同じ動作点）", "why": "単価は利用率に反比例"},
        {"action": "量子化を Q4_K_M から Q8_0 へ", "ratio": quant,
         "felt": f"総時間 p50 が {QUANT_TOTAL_MS['q4_k_m']:.0f} → "
                 f"{QUANT_TOTAL_MS['q8_0']:.0f} ms",
         "why": "セッション3 の実測（スロット1・並列1）"},
        {"action": f"応答キャッシュのヒット率 {_pct(CACHE_HIT_RATE)}",
         "ratio": 1.0 - CACHE_HIT_RATE, "felt": "ヒットしたぶんは即答",
         "why": "サーバを呼ばないので (1 − ヒット率) 倍"},
        {"action": f"台数を {a.instances} 本から {PLAN.peak_replicas} 本へ",
         "ratio": cost_per_1k(replace(a, instances=PLAN.peak_replicas)) / cost_per_1k(a),
         "felt": "待ちが減る", "why": "単価は台数に依存しない（式で約分）"},
        {"action": "飽和させる（並列2 → 並列4）", "ratio": trade["cost_ratio"],
         "felt": f"TTFT p95 が {trade['ttft_ratio']:.1f} 倍",
         "why": "やってはいけない"},
    ]


# ---------------------------------------------------------------------------
# 8. 表示
# ---------------------------------------------------------------------------


def explain(a: Assumptions) -> str:
    lines: list[str] = []
    rph = requests_per_hour(a)
    cost = cost_per_1k(a)

    lines += [
        "=== 前提（読者が入れる値。ここが変われば答えも変わる）===",
        f"  インスタンス時間単価 : {_n(a.hourly_cost)}"
        "（相対単位。--hourly で自分の値を入れる）",
        f"  台数                 : {a.instances} 本（セッション9 の minReplicas）",
        f"  1台の rps            : {a.rps_per_instance}"
        "（SLO を満たす動作点の実測値）",
        f"  利用率               : {_pct(a.utilization)}"
        f"（ヘッドルーム {_pct(HEADROOM)} の裏返し）",
        f"  API のトークン単価   : 入力 {_n(a.api_input_price_per_1m)} / "
        f"出力 {_n(a.api_output_price_per_1m)}（1Mトークンあたり・相対単位）",
        f"  1リクエストのトークン: 入力 {_n(a.input_tokens)} / "
        f"出力 {_n(a.output_tokens)}",
        f"  測定条件             : {MEASURED_CONDITIONS}",
        "",
        "=== 1000リクエスト単価 ===",
        f"  1時間の固定費  : {_n(a.hourly_cost)} × {a.instances} 本 = "
        f"{_n(a.cost_per_hour)}",
        f"  1時間の処理数  : {a.rps_per_instance} rps × 3600 × {a.instances} 本 × "
        f"{_pct(a.utilization)} = {rph:.1f} リクエスト",
        f"  1000リクエスト : {_n(a.cost_per_hour)} ÷ {rph:.1f} × 1000 = {cost:.4f}",
        "",
        "=== 利用率を振る（単価は利用率に反比例する）===",
        f"| 利用率 | 1時間の処理数 | 1000リクエスト単価 | {_pct(a.utilization)} との比 |",
        "| --: | --: | --: | --: |",
    ]
    for row in utilization_rows(a):
        lines.append(f"| {_pct(row['utilization'])} | "
                     f"{row['requests_per_hour']:,} | "
                     f"{row['cost_per_1k_requests']:.4f} | "
                     f"{row['ratio_to_base']:.2f} 倍 |")
    low, high = min(UTILIZATIONS), max(UTILIZATIONS)
    lines.append(f"  {_pct(low)} と {_pct(high)} の差は "
                 f"{cost_per_1k(a, low) / cost_per_1k(a, high):.2f} 倍"
                 f"（= {high:g} ÷ {low:g}）。値引き交渉より先にここを見る")

    hp = headroom_price(a)
    lines += [
        "",
        "=== ヘッドルームの値段 ===",
        f"  利用率 100% なら {hp['full']:.4f}、{_pct(MAX_UTILIZATION)} なら "
        f"{hp['capped']:.4f}（{hp['ratio']:.2f} 倍）",
        f"  セッション9 で空けた {_pct(HEADROOM)} は、単価では "
        f"{hp['ratio']:.2f} 倍の割高として現れる（安全のために払う値段）",
        "",
        "=== 停止スケジュール（平日 8:00-20:00 だけ動かす）===",
        "| 案 | 週あたりインスタンス時間 | 削減 | 最初の利用者の待ち |",
        "| :--- | --: | --: | :--- |",
    ]
    plans = schedules(a)
    baseline = plans[0].instance_hours
    for plan in plans:
        lines.append(f"| {plan.label} | {plan.instance_hours:.1f} | "
                     f"{plan.saving_ratio(baseline) * 100:.1f}% | {plan.note} |")

    be = breakeven(a)
    lines += [
        "",
        "=== クラウドAPIとの損益分岐 ===",
        f"  API の1リクエスト単価 : {_n(a.input_tokens)} ÷ 1e6 × "
        f"{_n(a.api_input_price_per_1m)} + {_n(a.output_tokens)} ÷ 1e6 × "
        f"{_n(a.api_output_price_per_1m)} = {be.api_per_request:.7g}",
        f"  API の1000リクエスト   : {be.api_per_1k:.4f}",
        f"  損益分岐               : {_n(a.cost_per_hour)} ÷ "
        f"{be.api_per_request:.7g} = {be.requests_per_hour:.2f} リクエスト/時"
        f"（= {be.rps:.2f} rps）",
        f"  損益分岐の利用率       : {be.utilization * 100:.1f}%"
        + (f"（上限 {_pct(MAX_UTILIZATION)} の内側 → 達成できる）" if be.achievable
           else f"（上限 {_pct(MAX_UTILIZATION)} を超える → "
                "この前提では自前は安くならない）"),
        f"  いまの利用率 {_pct(a.utilization)} の単価: 自前 {be.self_cost_per_1k:.4f} "
        + ("< " if be.self_hosting_cheaper_now else "> ")
        + f"API {be.api_per_1k:.4f} → "
        + ("自前が安い" if be.self_hosting_cheaper_now else "API が安い"),
        "",
        "=== 感度分析（各入力を +10% したとき）===",
        "| 入力 | 自前の単価 | 損益分岐リクエスト数 |",
        "| :--- | --: | --: |",
    ]
    for row in sensitivity_rows(a):
        lines.append(f"| {row['label']} | {_delta(row['cost_delta'] * 100)} | "
                     f"{_delta(row['breakeven_delta'] * 100)} |")
    lines.append("  損益分岐リクエスト数は rps にも利用率にも動かされない"
                 "（固定費と API 単価だけで決まる）")

    trade = saturation_tradeoff(a)
    lines += [
        "",
        "=== 単価だけを最適化してはいけない ===",
        f"  飽和させる（並列{SLO_POINT.concurrency} → 並列{SATURATED_POINT.concurrency}）"
        f"と rps は {SLO_POINT.throughput_rps} → {SATURATED_POINT.throughput_rps}"
        f"（{trade['rps_ratio']:.2f} 倍）",
        f"  単価は {trade['cost_slo']:.4f} → {trade['cost_sat']:.4f}"
        f"（{trade['cost_ratio']:.2f} 倍・{trade['saving_pct']:.1f}% 安い）",
        f"  しかし TTFT p95 は {trade['ttft_slo_ms']:.0f} ms → "
        f"{trade['ttft_sat_ms']:.0f} ms（{trade['ttft_ratio']:.1f} 倍）で SLO 違反",
        "",
        "=== 「高い」を分解する（施策 → 単価の倍率 → 体感）===",
        "| 施策 | 単価の倍率 | 体感への影響 | 根拠 |",
        "| :--- | --: | :--- | :--- |",
    ]
    for lever in levers(a):
        lines.append(f"| {lever['action']} | {lever['ratio']:.2f} | "
                     f"{lever['felt']} | {lever['why']} |")
    return "\n".join(lines)


def report_markdown(a: Assumptions,
                    title: str = "みなと商事 ヘルプデスク回答 API") -> str:
    """引き継げる成果物（Markdown）。**前提と再計算手順を必ず含める。**"""
    be = breakeven(a)
    hp = headroom_price(a)
    trade = saturation_tradeoff(a)
    plans = schedules(a)
    baseline = plans[0].instance_hours
    lines = [
        f"# コスト試算：{title}",
        "",
        f"- 測定条件：{MEASURED_CONDITIONS}",
        "- **金額の絶対値は約束しません。** 単価は相対単位（インスタンス1時間の"
        "値段を 1 と置く）で、自分の契約の値を入れると自分の通貨の答えになります。",
        f"- SLO：{PLAN.slo.describe()}（**制約条件**。単価だけで結論を出さない）",
        "",
        "## 1. 前提（変わったら数え直す入力）",
        "",
        "| 入力 | 値 | 種別 |",
        "| :--- | --: | :--- |",
        f"| インスタンス時間単価 | {_n(a.hourly_cost)} | 入力欄（読者が入れる） |",
        f"| 台数 | {a.instances} 本 | セッション9 の容量計画 |",
        f"| 1台の rps | {a.rps_per_instance} | 実測（SLO を満たす動作点・並列"
        f"{SLO_POINT.concurrency}） |",
        f"| TTFT p95 | {SLO_POINT.ttft_p95_ms:.0f} ms | 実測（同条件） |",
        f"| 総時間 p95 | {SLO_POINT.total_p95_ms:.0f} ms | 実測（同条件） |",
        f"| 利用率 | {_pct(a.utilization)} | 仮定（ヘッドルーム "
        f"{_pct(HEADROOM)} の裏返し） |",
        f"| 入力／出力トークン | {_n(a.input_tokens)} / {_n(a.output_tokens)} | "
        "仮定（出力は max_tokens と同じ） |",
        f"| API のトークン単価 | {_n(a.api_input_price_per_1m)} / "
        f"{_n(a.api_output_price_per_1m)} | 入力欄（読者が入れる） |",
        f"| スケールの遅れ | {PLAN.cold_start_wait_s:.1f} 秒 | 仮定の積み上げ"
        "（セッション7・8・9） |",
        "",
        "## 2. 1000リクエスト単価",
        "",
        "```text",
        "単価 = （インスタンス時間単価 × 台数） ÷ "
        "（rps × 3600 × 台数 × 利用率） × 1000",
        f"     = （{_n(a.hourly_cost)} × {a.instances}） ÷ "
        f"（{a.rps_per_instance} × 3600 × {a.instances} × {a.utilization:g}） × 1000",
        f"     = {cost_per_1k(a):.4f}",
        "```",
        "",
        "**台数は約分されます。** 台数を増やしても単価は変わりません"
        "（利用率が同じなら）。",
        "",
        "## 3. 利用率の感度",
        "",
        "| 利用率 | 1時間の処理数 | 1000リクエスト単価 |",
        "| --: | --: | --: |",
    ]
    for row in utilization_rows(a):
        lines.append(f"| {_pct(row['utilization'])} | "
                     f"{row['requests_per_hour']:,} | "
                     f"{row['cost_per_1k_requests']:.4f} |")
    lines += [
        "",
        f"利用率 {_pct(min(UTILIZATIONS))} と {_pct(max(UTILIZATIONS))} の差は "
        f"{cost_per_1k(a, min(UTILIZATIONS)) / cost_per_1k(a, max(UTILIZATIONS)):.2f}"
        " 倍です。ヘッドルームの値段は "
        f"{hp['ratio']:.2f} 倍（利用率 100% との比）。",
        "",
        "**打ち手の優先順位**（単価の倍率）：",
        "",
        "| 施策 | 単価の倍率 | 体感への影響 |",
        "| :--- | --: | :--- |",
    ]
    for lever in levers(a):
        lines.append(f"| {lever['action']} | {lever['ratio']:.2f} | "
                     f"{lever['felt']} |")
    lines += [
        "",
        f"**やってはいけない**：飽和させると単価は {trade['saving_pct']:.1f}% しか"
        f"下がらないのに、TTFT p95 は {trade['ttft_ratio']:.1f} 倍になります。",
        "",
        "## 4. 停止スケジュール",
        "",
        "| 案 | 週インスタンス時間 | 削減 | 最初の利用者の待ち |",
        "| :--- | --: | --: | :--- |",
    ]
    for plan in plans:
        lines.append(f"| {plan.label} | {plan.instance_hours:.1f} | "
                     f"{plan.saving_ratio(baseline) * 100:.1f}% | {plan.note} |")
    lines += [
        "",
        "`minReplicas` は下限なので、夜間縮退はスケジュール実行で "
        "`minReplicas` を書き換える形になります。**SLO を時間帯で定義し直せるか**"
        "を先に確認してください。",
        "",
        "## 5. クラウドAPI との損益分岐",
        "",
        "```text",
        "損益分岐リクエスト数（1時間） = "
        "（インスタンス時間単価 × 台数） ÷ （API の1リクエスト単価）",
        f"  = {_n(a.cost_per_hour)} ÷ {be.api_per_request:.7g} = "
        f"{be.requests_per_hour:.2f} リクエスト/時（{be.rps:.2f} rps）",
        f"  能力（ヘッドルームを残したまま）= {be.capacity_per_hour:.1f} リクエスト/時",
        f"  分岐点の利用率 = {be.utilization * 100:.1f}%",
        "```",
        "",
        ("分岐点は能力の内側なので、達成できる可能性があります。"
         if be.achievable else
         "分岐点が能力を超えています。**この前提では自前は安くなりません。**"),
        "",
        "| 入力 | 自前の単価 | 損益分岐リクエスト数 |",
        "| :--- | --: | --: |",
    ]
    for row in sensitivity_rows(a):
        lines.append(f"| {row['label']} +10% | {_delta(row['cost_delta'] * 100)} | "
                     f"{_delta(row['breakeven_delta'] * 100)} |")
    lines += [
        "",
        "## 6. 前提が変わったときの再計算手順",
        "",
        "1. 同時実行を振って測り直す（`src/session04/sweep.py`）。"
        "**SLO を満たす最大の点**を動作点に採る",
        "2. その rps を `--rps` に、観測した利用率を `--utilization` に入れる",
        "3. `--out reports/cost_report.md` で単価と感度分析を出し直す",
        "4. API の価格表と実測トークン数を `--api-input` / `--api-output` / "
        "`--input-tokens` / `--output-tokens` に入れる",
        "5. 損益分岐が能力の内側かを確認する（外側なら自前は選べない）",
        "6. 停止スケジュールを選び直し、SLO の文言と HPA の `minReplicas` を"
        "突き合わせる（`src/session09/lint_hpa.py --plan`）",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 9. CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="推論の単価と損益分岐")
    parser.add_argument("--hourly", type=float, default=1.0,
                        help="インスタンス1台の1時間単価（相対単位）")
    parser.add_argument("--instances", type=int, default=3, help="台数")
    parser.add_argument("--rps", type=float, default=SLO_POINT.throughput_rps,
                        help="1台の rps（SLO を満たす動作点の実測値）")
    parser.add_argument("--utilization", type=float, default=MAX_UTILIZATION,
                        help="利用率（0 より大きく 1 以下）")
    parser.add_argument("--api-input", type=float, default=0.8,
                        help="API の入力単価（1Mトークンあたり・相対単位）")
    parser.add_argument("--api-output", type=float, default=3.2,
                        help="API の出力単価（1Mトークンあたり・相対単位）")
    parser.add_argument("--input-tokens", type=float, default=300.0)
    parser.add_argument("--output-tokens", type=float, default=48.0)
    parser.add_argument("--markdown", action="store_true",
                        help="引き継げる成果物（Markdown）を表示する")
    parser.add_argument("--out", help="Markdown を書き出すパス")
    parser.add_argument("--title", default="みなと商事 ヘルプデスク回答 API")
    args = parser.parse_args(argv)

    try:
        a = Assumptions(args.hourly, args.instances, args.rps, args.utilization,
                        args.api_input, args.api_output,
                        args.input_tokens, args.output_tokens)
    except ValueError as err:
        print(f"前提が不正です: {err}", file=sys.stderr)
        return 2

    if args.markdown or args.out:
        body = report_markdown(a, args.title)
        print(body)
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(body + "\n", encoding="utf-8")
            print(f"\n-> {out}")
    else:
        print(explain(a))
    return 0


if __name__ == "__main__":
    sys.exit(main())
