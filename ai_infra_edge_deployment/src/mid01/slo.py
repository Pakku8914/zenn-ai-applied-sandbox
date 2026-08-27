#!/usr/bin/env python3
"""SLO（サービスレベル目標）を「測った値」から導く（中間プロジェクト1）。

このモジュールは判断を代わりにしてくれる道具ではない。**前提が変わったら
結論が自動で数え直される**ようにするための道具である。手で電卓を叩き直すと、
必ずどこかを直し忘れる。

考え方は1つだけ。

    要件（利用者が待てる時間） = 天井
    測った p95 × 余裕の係数     = 床
    SLO の目標値は床と天井のあいだに置く。床が天井を超えたら成立しない。

数値の出どころは本書の実測（`MEASURED_CONDITIONS`）だが、**絶対値は再現しない。**
同じ環境でも実行ごとに 2 倍程度ぶれる。学ぶのは関係と数え方である。
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.session04.serving_config import SweepRow, find_saturation  # noqa: E402

MEASURED_CONDITIONS = (
    "2026-08-15 実測 / aarch64 / CPU 2コア / メモリ 5.8GB / Python 3.12.13 / "
    "llama.cpp -t 2 / Q4_K_M / -c 2048 -np 2 / max_tokens=48 / 20 リクエスト"
)
"""本文・成果物に数値を書くときに必ず併記する測定条件。"""

MAX_TOKENS = 48
"""出力トークン数の上限。測定条件と SLO で同じ値を使う。"""


# ---------------------------------------------------------------------------
# 測った点
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Point:
    """同時実行を1段変えて測った1点。**すべて実測値である。**

    自分の環境で測ったら、この形で作り直して渡すこと（本書の値を使わない）。
    """

    concurrency: int
    ttft_p50_ms: float
    ttft_p95_ms: float
    total_p50_ms: float
    total_p95_ms: float
    tpot_p50_ms: float
    throughput_tps: float
    throughput_rps: float
    n: int = 20

    def observed(self, metric: str, quantile: int = 95) -> float:
        """指標名と分位から実測値を引く。測っていない組み合わせは例外にする。"""
        name = f"{metric}_p{quantile}_ms"
        if not hasattr(self, name):
            raise ValueError(f"その指標は測っていません: {name}")
        return float(getattr(self, name))

    def queue_wait_ms(self, baseline_ttft_ms: float) -> float:
        """キュー待ちの近似（並列1 の TTFT を待ちゼロの代理として引く）。"""
        return max(self.ttft_p50_ms - baseline_ttft_ms, 0.0)


MEASURED: tuple[Point, ...] = (
    Point(1, 155.0, 194.0, 1034.0, 1212.0, 19.19, 45.0, 0.96),
    Point(2, 52.0, 100.0, 1737.0, 2126.0, 36.74, 53.0, 1.13),
    Point(4, 1772.0, 2064.0, 3379.0, 3737.0, 36.15, 53.9, 1.15),
)
"""セッション4の実測表（`reports/load_serve_c{1,2,4}.json`）。

TPOT は `LoadReport.tpot.p50` の実測値である。`(総時間 − TTFT) ÷ トークン数` の
概算で代用してはいけない（章をまたいで数字が食い違う）。
"""

MIN_SAMPLES = {50: 1, 95: 20, 99: 100}
"""分位ごとに必要な最低件数（セッション2）。"""


def enough_samples(n: int, quantile: int = 95) -> bool:
    """その分位を出すのに件数が足りているか。"""
    if quantile not in MIN_SAMPLES:
        raise ValueError(f"扱わない分位です: p{quantile}")
    return n >= MIN_SAMPLES[quantile]


# ---------------------------------------------------------------------------
# 目標値を導く
# ---------------------------------------------------------------------------


def derive_floor(measured_ms: float, margin: float = 1.5,
                 round_to: float = 100.0) -> float:
    """測った値に余裕を掛けて、上に丸める（＝床）。

    切り上げるのが要点である。切り下げると、測った値そのものを割ってしまう
    目標ができあがる。
    """
    if measured_ms <= 0:
        raise ValueError("測った値は正の数を指定してください")
    if margin < 1.0:
        raise ValueError("margin は 1.0 以上を指定してください")
    if round_to <= 0:
        raise ValueError("round_to は正の数を指定してください")
    return float(math.ceil(measured_ms * margin / round_to) * round_to)


@dataclass(frozen=True)
class Requirement:
    """利用者側の上限（＝天井）。**前提値であり実測ではない。**"""

    label: str
    metric: str
    ceiling_ms: float
    why: str


@dataclass(frozen=True)
class Proposal:
    """床と天井を突き合わせた結果。"""

    requirement: Requirement
    measured_ms: float
    margin: float
    round_to: float
    floor_ms: float

    @property
    def feasible(self) -> bool:
        return self.floor_ms <= self.requirement.ceiling_ms

    @property
    def headroom(self) -> float:
        """天井が床の何倍か。小さいほど、劣化したときに先に要件を割る。"""
        return self.requirement.ceiling_ms / self.floor_ms

    @property
    def verdict(self) -> str:
        if self.feasible:
            return (f"要件内に収まる（床 {self.floor_ms:.0f} ms ≦ "
                    f"天井 {self.requirement.ceiling_ms:.0f} ms）")
        return (f"要件と両立しない（床 {self.floor_ms:.0f} ms > "
                f"天井 {self.requirement.ceiling_ms:.0f} ms）")

    def explain(self) -> str:
        return "\n".join([
            f"{self.requirement.label}: {self.measured_ms:.0f} ms × "
            f"{self.margin} = {self.measured_ms * self.margin:.0f} → "
            f"{self.floor_ms:.0f} ms（天井 {self.requirement.ceiling_ms:.0f} ms）",
            self.verdict,
        ])


def propose(requirement: Requirement, measured_ms: float, margin: float = 1.5,
            round_to: float = 100.0) -> Proposal:
    """要件（天井）と実測（床）を突き合わせる。"""
    return Proposal(requirement, float(measured_ms), float(margin),
                    float(round_to), derive_floor(measured_ms, margin, round_to))


# ---------------------------------------------------------------------------
# SLO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Slo:
    """守る約束。

    **`on_breach` が空の SLO は作れないようにしてある。** 超えたときの行動が
    書かれていない目標値は、守られているかを確認する人がいても、割ったときに
    動く人がいない。それは SLO ではなく願望である。
    """

    metric: str
    quantile: int
    target_ms: float
    label: str
    window: str
    how: str
    why: str
    on_breach: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.metric not in ("ttft", "total", "tpot"):
            raise ValueError(f"扱わない指標です: {self.metric}")
        if self.quantile not in MIN_SAMPLES:
            raise ValueError(f"扱わない分位です: p{self.quantile}")
        if self.target_ms <= 0:
            raise ValueError("目標値は正の数を指定してください")
        if not self.on_breach:
            raise ValueError("目標を超えたときにやることが1つも書かれていません")

    def judge(self, observed_ms: float) -> bool:
        return observed_ms <= self.target_ms

    def satisfied_by(self, point: Point) -> bool:
        return self.judge(point.observed(self.metric, self.quantile))

    def describe(self) -> str:
        return f"{self.label} ≦ {self.target_ms:.0f} ms"


PROVISIONAL_ACTIONS: tuple[str, ...] = (
    "/health と /slots を見て、スロットが埋まっているかを確認する（1 分）",
    "ゲートウェイの MAX_INFLIGHT が 2 になっているかを確認し、\n"
    "   4 以上なら 2 に直して再起動する（3 分）",
    "応答キャッシュの TTL（CACHE_TTL）を 300 → 900 秒に延ばす（1 分）",
)
"""暫定対応（当番・5 分以内）。1 回に 1 つだけ実施する。"""

PERMANENT_ACTIONS: tuple[str, ...] = (
    "src/review01/triage.py に観測値を渡し、原因の候補と根拠を出す（10 分）",
    "キュー待ちが支配的なら、容量計画に従ってインスタンスを 1 本増やす（30 分）",
    "デコード（TPOT）が支配的なら、-c 2048 -np 2 の条件で量子化を測り直す（2 時間）",
    "プリフィルが支配的なら、受け入れ判定で長すぎる入力を断る（1 時間）",
)
"""恒久対応（オーナー・次営業日まで）。"""

REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement("最初の反応", "ttft", 1000.0, "利用者が待てる上限（前提値）"),
    Requirement("回答が出そろうまで", "total", 5000.0, "利用者が待てる上限（前提値）"),
)
"""みなと商事から与えられた天井。**前提値であり実測ではない。**"""

DEFAULT_SLOS: tuple[Slo, ...] = (
    Slo(metric="ttft", quantile=95, target_ms=200.0, label="TTFT p95",
        window="営業日 9:00〜18:00",
        how="固定プロンプト 20 件 / 出力 48 トークン / 温度 0 / 並列 2",
        why="対話型で利用者が画面の前で待つ。最初の反応が体感を決める",
        on_breach=PROVISIONAL_ACTIONS + PERMANENT_ACTIONS),
    Slo(metric="total", quantile=95, target_ms=3200.0, label="総時間 p95",
        window="営業日 9:00〜18:00",
        how="固定プロンプト 20 件 / 出力 48 トークン / 温度 0 / 並列 2",
        why="反応が速くても完了が遅ければ使えない。要件の余裕が薄いのはこちら",
        on_breach=PROVISIONAL_ACTIONS + PERMANENT_ACTIONS),
)
"""本書の実測から導いた SLO の例。**自分の環境の値で作り直すこと。**"""


def satisfies(point: Point, slos: tuple[Slo, ...] = DEFAULT_SLOS) -> bool:
    return all(s.satisfied_by(point) for s in slos)


def operating_point(points: tuple[Point, ...] = MEASURED,
                    slos: tuple[Slo, ...] = DEFAULT_SLOS) -> Point:
    """SLO を満たす中で最も rps が高い点。

    **「rps が最大の点」ではない。** 飽和した点の rps はほとんど同じなので、
    rps だけで選ぶと体感の壊れた点を選んでしまう。
    """
    ok = [p for p in points if satisfies(p, slos)]
    if not ok:
        raise ValueError("SLO を満たす動作点がありません")
    return max(ok, key=lambda p: p.throughput_rps)


def saturation_of(points: tuple[Point, ...] = MEASURED) -> int | None:
    """飽和点（セッション4の定義）。刻みが粗いと None になる。"""
    rows = [SweepRow(p.concurrency, p.ttft_p50_ms, p.total_p50_ms,
                     p.throughput_tps) for p in points]
    return find_saturation(rows)


def throughput_gain(points: tuple[Point, ...] = MEASURED) -> list[tuple[int, float]]:
    """段ごとのスループットの伸び率。伸びが止まった段が飽和点である。"""
    ordered = sorted(points, key=lambda p: p.concurrency)
    gains: list[tuple[int, float]] = []
    for prev, cur in zip(ordered, ordered[1:]):
        gains.append((cur.concurrency,
                      (cur.throughput_tps - prev.throughput_tps) / prev.throughput_tps))
    return gains


# ---------------------------------------------------------------------------
# TPOT の割り付け（総時間の目標から逆算する）
# ---------------------------------------------------------------------------


def tpot_budget_ms(total_target_ms: float, ttft_target_ms: float,
                   max_tokens: int = MAX_TOKENS) -> float:
    """総時間の目標から TPOT の上限を割り付ける。

    セッション2の式 `総時間 = TTFT + TPOT × (出力数 − 1)` の逆算である。
    **これは目標の割り付けであって実測ではない。**
    """
    if max_tokens < 2:
        raise ValueError("出力トークン数は 2 以上を指定してください")
    if total_target_ms <= ttft_target_ms:
        raise ValueError("総時間の目標は TTFT の目標より大きくしてください")
    return (total_target_ms - ttft_target_ms) / (max_tokens - 1)


def total_ms_for(ttft_ms: float, tpot_ms: float,
                 max_tokens: int = MAX_TOKENS) -> float:
    """TTFT と TPOT から総時間を出す（出力上限を変えたときの確認に使う）。"""
    if max_tokens < 1:
        raise ValueError("出力トークン数は 1 以上を指定してください")
    return ttft_ms + tpot_ms * (max_tokens - 1)


# ---------------------------------------------------------------------------
# 成果物① SLO 定義
# ---------------------------------------------------------------------------


def slo_document(point: Point, slos: tuple[Slo, ...] = DEFAULT_SLOS,
                 margin: float = 1.5, round_to: float = 100.0,
                 max_tokens: int = MAX_TOKENS) -> str:
    """引き継げる形（Markdown）の SLO 定義。値と根拠を必ず並べて書く。"""
    ttft, total = slos[0], slos[1]
    ttft_req, total_req = REQUIREMENTS[0], REQUIREMENTS[1]
    ttft_measured = point.observed(ttft.metric, ttft.quantile)
    total_measured = point.observed(total.metric, total.quantile)
    tpot = tpot_budget_ms(total.target_ms, ttft.target_ms, max_tokens)
    provisional = "\n".join(f"{i}. {a}" for i, a
                            in enumerate(PROVISIONAL_ACTIONS, start=1))
    permanent = "\n".join(f"{i}. {a}" for i, a
                          in enumerate(PERMANENT_ACTIONS,
                                       start=len(PROVISIONAL_ACTIONS) + 1))
    return f"""# SLO 定義：みなと商事 ヘルプデスク回答 API

最終更新: 2026-08-15 / 次回見直し: 構成変更時、または3か月後

## 1. 対象と適用範囲

- 対象: 社内ヘルプデスク回答 API（ゲートウェイ経由の /generate）
- 適用時間: {ttft.window}（時間外は対象外）
- 対象外: 応答キャッシュにヒットしたリクエスト（サーバを呼ばないため別集計）
- 前提（要件として与えられた値・実測ではない）:
  利用者 240 人 / ピーク 2.0 rps / 平常 0.4 rps /
  待てる最初の反応 {ttft_req.ceiling_ms:,.0f} ms / 待てる完了 {total_req.ceiling_ms:,.0f} ms

## 2. 指標（なぜこの指標か）

| 指標 | なぜ選んだか |
| :--- | :--- |
| {ttft.label} | {ttft.why} |
| {total.label} | {total.why} |

TPOT は利用者が体感しないため SLO には含めず、総時間から割り付けた
内部目標（{tpot:.1f} ms 以下）として扱う。スループットは容量計画の入力として使う。
平均は使わない（遅い数件を薄めて隠すため）。

## 3. 目標値（どう導いたか）

| 指標 | 実測 p95（並列 {point.concurrency}） | 係数 | 丸め | 目標値 | 要件の天井 | 余裕 |
| :--- | --: | --: | --: | --: | --: | --: |
| {ttft.label} | {ttft_measured:,.0f} ms | {margin} | {round_to:.0f} ms 単位で切り上げ | {ttft.target_ms:,.0f} ms | {ttft_req.ceiling_ms:,.0f} ms | {ttft_req.ceiling_ms / ttft.target_ms:.2f} 倍 |
| {total.label} | {total_measured:,.0f} ms | {margin} | {round_to:.0f} ms 単位で切り上げ | {total.target_ms:,.0f} ms | {total_req.ceiling_ms:,.0f} ms | {total_req.ceiling_ms / total.target_ms:.2f} 倍 |

- 内部目標: TPOT ≦ ({total.target_ms:,.0f} − {ttft.target_ms:,.0f}) ÷ ({max_tokens} − 1) = {tpot:.1f} ms（実測 {point.tpot_p50_ms} ms）
- 動作点: 並列 {point.concurrency}（飽和点の手前で実測した点）。{point.throughput_rps} rps
- 係数 {margin} の根拠: 同一環境でも絶対値が実行ごとに 2 倍程度ぶれる。
  p95（20 件に 1 件は超えてよい）と「2 日連続で超えたら違反」の判定を
  組み合わせることで、ぶれは吸収しつつ 2 倍の劣化は検知できる線として選んだ。
- 丸め幅 {round_to:.0f} ms の根拠: 運用で覚えられる粒度。10 ms 単位は判断に寄与しない。
- 注記: 目標を 150 ms に厳しくすると並列 1（TTFT p95 194 ms）が
  SLO を満たさなくなる。1 本ずつ入れ替える運用に影響するため、
  丸め幅の変更は容量計画と一緒に見直す。

## 4. 測定方法

| 項目 | 内容 |
| :--- | :--- |
| 誰が | 週次: サービスオーナー / 異常時: 当番 |
| 何で | src/session04/sweep.py --label slo_check_YYYYMMDD --concurrency {point.concurrency} --max-tokens {max_tokens} --prompts 20 |
| 条件 | {ttft.how} / ウォームアップ 2 回 |
| 件数 | {MIN_SAMPLES[95]} 件（p95 に必要な最低件数。p99 を出すなら {MIN_SAMPLES[99]} 件） |
| 頻度 | 営業日の朝 1 回（ピーク前）＋ 設定変更のたび |
| 判定 | 20 件のうち 19 件目までが目標内なら達成（p95 の定義）。2 日連続で超えたら違反 |
| 記録 | reports/sweep_slo_check_YYYYMMDD.json を残す。測定条件も一緒に残す |

## 5. 目標を超えたときにやること

暫定対応（当番・5 分以内）:

{provisional}

恒久対応（オーナー・次営業日まで）:

{permanent}

やらないこと:

- 推論サーバの再起動を最初の手段にしない（重み 379.4 MiB のロードだけで
  1,335.9 ms の見積り。待っている利用者を全員切ることになる）
- 設定を同時に 2 つ変えない（効いたものが分からなくなる）
- CPU 使用率を根拠に判断しない（デコードはメモリ帯域律速）

## 6. この SLO を見直す条件

1. 量子化形式・-np・-c のいずれかを変えた
2. モデルを載せ替えた（0.5B から 8B 級へなど）
3. 出力上限（max_tokens）を変えた
4. ピークのリクエスト率が前提の 1.5 倍（3.0 rps）を超えた
5. インスタンスを載せるマシンの CPU 数・メモリが変わった
6. 応答キャッシュのヒット率が大きく変わった（対象外の件数が変わる）
"""


__all__ = [
    "DEFAULT_SLOS", "MAX_TOKENS", "MEASURED", "MEASURED_CONDITIONS",
    "MIN_SAMPLES", "PERMANENT_ACTIONS", "PROVISIONAL_ACTIONS", "REQUIREMENTS",
    "Point", "Proposal", "Requirement", "Slo", "derive_floor", "enough_samples",
    "operating_point", "propose", "satisfies", "saturation_of", "slo_document",
    "total_ms_for", "throughput_gain", "tpot_budget_ms",
]
