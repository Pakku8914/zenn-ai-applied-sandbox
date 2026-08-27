#!/usr/bin/env python3
"""端末群（fleet）の側から見た OTA（セッション15）。

`ota.py` が「1台をどう壊さずに更新するか」を扱うのに対し、こちらは
「1,000 台をどの順で・どれだけの帯域で・何を見ながら更新するか」を扱う。

    python src/session15/rollout.py       # 帯域と段階展開の数字
    python src/session15/fleet_report.py  # 監視・門・集約指標
    python src/session15/verify.py        # 本章の自己検証

数値の3分類は session11/edge_budget.py と同じ規律で扱う。**混ぜてはいけない。**

  ① 実測値   : セッション12 の ONNX サイズと等価性（測定条件つきで引用する）
  ② 物理計算 : 台数・サイズ・回線から出る配布時間（誰が計算しても同じ）
  ③ 前提値   : 台数・回線・観察時間・許容倍率・タイムアウト（読者が自分の値を入れる）

**本書は実端末群を持っていない。** したがって「OTA の成功率」「実際の配信時間」の
実測値はこのファイルに存在しない。sample_fleet() が返す端末群は、決定的に作った
架空のデータである。
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

SANDBOX = Path(__file__).resolve().parents[2]
for _extra in (SANDBOX, SANDBOX / "src" / "session07", SANDBOX / "src" / "session15"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from fetch_weights import fetch_waves  # noqa: E402  セッション7から再利用
from ota import parse_version  # noqa: E402

MB = 1024 ** 2
GB = 1024 ** 3

# --- ③ 前提値（セッション11 で置いた値。同じものを指すときは必ずこの数値を使う）---
DEVICE_COUNT = 1000
LINE_MBPS = 100.0
OBSERVE_HOURS = 24.0            # 1段あたりの観察期間
FAILURE_TOLERANCE = 1.5         # 現行版の失敗率の何倍までを許すか
MIN_INFERENCES = 1000           # これ未満の件数では判断しない
CLIENT_TIMEOUT_S = 300.0        # 端末側のダウンロードのタイムアウト
STAGE_FRACTIONS = (0.001, 0.01, 0.10, 1.00)
DELTA_RATIO = 0.30              # 差分が全体の何割になるか（実測していない）
TELEMETRY_DAYS = 30
AGG_BYTES_PER_DAY = 200         # 集約指標1件の大きさ
SAMPLES_PER_DAY = 200           # 1台が1日に処理する件数

# --- ① 実測値（2026-08-15 実測 / aarch64 / CPU 2コア / メモリ 5.8GB / Python 3.12.13）---
# バイト数が正典で、MB 表示はそこから導く（逆をやると丸めた表示値から
# 存在しないバイト数を作ってしまう。17.56 × 1024^2 = 18,412,995 は実ファイルより
# 3,496 バイト多い）。値は models/onnx/classifier_{fp32,int8}.onnx の実サイズ。
FP32_BYTES = 73_531_824             # 実測（os.path.getsize）
INT8_BYTES = 18_409_499             # 実測（os.path.getsize）
FP32_MB = round(FP32_BYTES / MB, 2)  # 70.13
INT8_MB = round(INT8_BYTES / MB, 2)  # 17.56
EQ_MAX_DIFF = 0.001344               # 新旧モデルの確率の最大差（セッション12）
EQ_MAX_DIFF_LIMIT = 0.01             # ③ 判定に使う上限（セッション12 と同じ）
EQ_MARGIN = 0.05                     # ③ 「はっきりしている」と見なすマージン

INPUT_DIM = 384                      # セッション12 の分類器と同じ入力次元
RAW_BYTES_PER_SAMPLE = INPUT_DIM * 4  # fp32 の入力ベクトル1件（1,536 バイト）

# レイテンシのバケット。境界は SLO から決め、**あとから変えない**。
BUCKET_EDGES_MS = (0.5, 1.0, 2.0, 5.0)
BUCKET_LABELS = ("0.5 ms 未満", "1.0 ms 未満", "2.0 ms 未満",
                 "5.0 ms 未満", "5.0 ms 以上")

# 端末が送ってよい項目。**許可リストにする**（拒否リストは項目が増えたとき漏れる）。
DEVICE_PAYLOAD_KEYS = ("model_version", "app_version", "inferences",
                       "failures", "latency_buckets", "window_hours")


# --- 帯域（②物理計算）------------------------------------------------------
def transfer_seconds(size_mb: float, devices: int = DEVICE_COUNT,
                     mbps: float = LINE_MBPS) -> float:
    """②物理計算：合計バイト数を回線速度で割るだけ。8 はバイト -> ビット。"""
    if size_mb < 0 or devices < 0 or mbps <= 0:
        raise ValueError("size_mb・devices は 0 以上、mbps は正の値にしてください")
    return size_mb * devices * 8 / mbps


def total_gb(size_mb: float, devices: int = DEVICE_COUNT) -> float:
    """配布1回で流れる合計（GB）。セッション11 と同じ式にしてある。"""
    return size_mb * devices / 1024


def per_device_seconds(size_mb: float, parallel: int,
                       mbps: float = LINE_MBPS) -> float:
    """同時に parallel 台が落とすとき、1台が終わるまでの秒数。

    帯域は等分されると仮定する。**同時台数に比例して1台が遅くなる**のが要点で、
    同時 1,000 台なら1台の所要は全体の所要と同じになる（全員が最後まで走る）。
    """
    if parallel < 1:
        raise ValueError("parallel は 1 以上にしてください")
    share_mbps = mbps / parallel
    return size_mb * 8 / share_mbps


def max_parallel_for_timeout(size_mb: float, timeout_s: float = CLIENT_TIMEOUT_S,
                             mbps: float = LINE_MBPS) -> int:
    """タイムアウトを守れる同時台数の上限（切り捨て）。

    四捨五入してはいけない。1台でも上限を超えるとタイムアウトして再送が始まる。
    """
    return int(timeout_s * mbps // (size_mb * 8))


def waves(devices: int, max_parallel: int) -> int:
    """何波に分かれるか。セッション7の fetch_waves をそのまま再利用する。"""
    return fetch_waves(devices, max_parallel)


def average_concurrent(devices: int = DEVICE_COUNT, window_s: float = 3600.0,
                       size_mb: float = INT8_MB, mbps: float = LINE_MBPS) -> float:
    """台数を窓幅に均等に散らしたときの平均同時台数（到着率 × 単独所要）。"""
    if window_s <= 0:
        raise ValueError("window_s は正の値にしてください")
    return devices * (size_mb * 8 / mbps) / window_s


# --- 段階展開 ---------------------------------------------------------------
@dataclass(frozen=True)
class Stage:
    index: int           # 何段目か
    fraction: float      # この段までに配る割合
    added: int           # この段で新しく配る台数
    target: int          # この段までの累積
    seconds: float       # ②物理計算：この段の配布にかかる秒数
    observe_hours: float


def stage_plan(total: int = DEVICE_COUNT, fractions=STAGE_FRACTIONS,
               size_mb: float = INT8_MB, mbps: float = LINE_MBPS,
               observe_hours: float = OBSERVE_HOURS) -> list[Stage]:
    """割合の並びから段階展開の計画を作る。台数の合計は必ず total になる。

    割合は「その段までに配り終える累積」として読む。1% の段は 10 台ではなく
    **9 台**である（すでに1台配っているため）。累積で考えないと二重に数える。
    """
    if total < 1:
        raise ValueError("total は 1 以上にしてください")
    stages: list[Stage] = []
    done = 0
    for index, fraction in enumerate(fractions, start=1):
        # round を挟むのは浮動小数の誤差対策（1000*0.001 が 2 台に切り上がる事故を防ぐ）
        target = min(total, max(1, math.ceil(round(total * fraction, 6))))
        added = target - done
        if added <= 0:
            continue
        stages.append(Stage(index, fraction, added, target,
                            transfer_seconds(size_mb, added, mbps), observe_hours))
        done = target
    return stages


def plan_elapsed_hours(stages: list[Stage]) -> float:
    """観察を含めた所要時間。観察は段の間だけ数える（最終段の後は含めない）。"""
    if not stages:
        return 0.0
    transfer_h = sum(stage.seconds for stage in stages) / 3600
    observe_h = sum(stage.observe_hours for stage in stages[:-1])
    return transfer_h + observe_h


# --- 監視（版別の分布）------------------------------------------------------
@dataclass(frozen=True)
class DeviceReport:
    """1台が1日1回送ってくる集約指標（生の入力は含まない）。"""

    device_id: str
    model_version: str
    app_version: str
    last_seen_h: float
    inferences: int
    failures: int
    buckets: tuple[int, ...]


@dataclass(frozen=True)
class VersionStat:
    version: str
    devices: int
    ratio: float
    inferences: int
    failures: int
    offline: int
    buckets: tuple[int, ...]

    @property
    def failure_rate(self) -> float:
        return self.failures / self.inferences if self.inferences else 0.0


@dataclass(frozen=True)
class FleetTotals:
    devices: int
    inferences: int
    failures: int
    offline: int

    @property
    def failure_rate(self) -> float:
        return self.failures / self.inferences if self.inferences else 0.0

    @property
    def offline_ratio(self) -> float:
        return self.offline / self.devices if self.devices else 0.0


def sample_fleet(total: int = DEVICE_COUNT) -> list[DeviceReport]:
    """決定的に作った架空の端末群。**実測ではない。**

    乱数を使っていないので、誰の環境でも同じ数字になる。内訳は
    新版 1.3.0 が 100 台・現行 1.2.0 が 850 台・取り残された 1.1.0 が 50 台で、
    10 台に1台がオフライン（最後の通信から 30 時間）である。
    """
    if total < 200:
        raise ValueError("total は 200 以上にしてください（内訳が重なります）")
    rows: list[DeviceReport] = []
    for index in range(total):
        if index < 100:                                  # 新版（試用中）
            version, app, failures = "1.3.0", "2.1.0", 5
            buckets = (120, 50, 20, 8, 2)
        elif index >= total - 50:                        # 更新が届いていない端末
            version, app, failures = "1.1.0", "1.9.0", 2
            buckets = (100, 60, 30, 8, 2)
        else:                                            # 現行
            version, app, failures = "1.2.0", "2.1.0", 1
            buckets = (150, 40, 8, 2, 0)
        rows.append(DeviceReport(
            device_id=f"dev-{index:04d}", model_version=version, app_version=app,
            last_seen_h=30.0 if index % 10 == 0 else 0.5,
            inferences=SAMPLES_PER_DAY, failures=failures, buckets=buckets))
    return rows


def version_mix(reports: list[DeviceReport],
                offline_after_h: float = OBSERVE_HOURS) -> list[VersionStat]:
    """版別に集計する。**指標には必ずモデルの版を添える**（無いと原因が特定できない）。"""
    groups: dict[str, list[DeviceReport]] = {}
    for report in reports:
        groups.setdefault(report.model_version, []).append(report)
    total = len(reports)
    stats = [
        VersionStat(
            version=version, devices=len(rows),
            ratio=len(rows) / total if total else 0.0,
            inferences=sum(r.inferences for r in rows),
            failures=sum(r.failures for r in rows),
            offline=sum(1 for r in rows if r.last_seen_h >= offline_after_h),
            buckets=merge_buckets(rows))
        for version, rows in groups.items()
    ]
    stats.sort(key=lambda stat: parse_version(stat.version), reverse=True)
    return stats


def fleet_totals(reports: list[DeviceReport],
                 offline_after_h: float = OBSERVE_HOURS) -> FleetTotals:
    """全体の合計。**分母は常に全台**（オフラインを外さない）。"""
    return FleetTotals(
        devices=len(reports),
        inferences=sum(r.inferences for r in reports),
        failures=sum(r.failures for r in reports),
        offline=sum(1 for r in reports if r.last_seen_h >= offline_after_h))


# --- レイテンシ（足せる形で受け取る）---------------------------------------
def merge_buckets(reports: list[DeviceReport]) -> tuple[int, ...]:
    """バケットは足せる。だから端末からは件数で受け取る。"""
    total = [0] * len(BUCKET_LABELS)
    for report in reports:
        if len(report.buckets) != len(BUCKET_LABELS):
            raise ValueError("バケットの数が合いません（境界を変えたデータは混ぜられません）")
        for index, count in enumerate(report.buckets):
            total[index] += count
    return tuple(total)


def quantile_bucket(buckets: tuple[int, ...], q: float) -> str:
    """パーセンタイルが「どの区間に入るか」を返す。値そのものは出せない。

    パーセンタイルは足せないので、端末から p95 を受け取っても合成できない。
    件数で受け取り、合計してから求めるのが唯一の正しい順序である。
    """
    total = sum(buckets)
    if total == 0:
        return "データなし"
    rank = math.ceil(q * total)
    seen = 0
    for label, count in zip(BUCKET_LABELS, buckets):
        seen += count
        if seen >= rank:
            return label
    return BUCKET_LABELS[-1]


# --- 門（配る前・配った後）-------------------------------------------------
@dataclass(frozen=True)
class Decision:
    verdict: str                      # 続行 / 保留 / 中止（配る前は 配ってよい / 配ってはいけない）
    reasons: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.verdict in ("続行", "配ってよい")


def release_gate(max_diff: float, clear_agree: bool,
                 max_diff_limit: float = EQ_MAX_DIFF_LIMIT) -> Decision:
    """配る前の門。セッション12 の等価性の判定をそのまま使う。"""
    reasons: list[str] = []
    if max_diff > max_diff_limit:
        reasons.append(f"確率の最大差 {max_diff:.6f} が上限 {max_diff_limit:.6f} を超えています")
    if not clear_agree:
        reasons.append(f"マージン {EQ_MARGIN:.2f} 以上のサンプルに不一致があります")
    return Decision("配ってよい" if not reasons else "配ってはいけない", tuple(reasons))


def rollout_gate(new: VersionStat, baseline: VersionStat,
                 tolerance: float = FAILURE_TOLERANCE,
                 min_inferences: int = MIN_INFERENCES) -> Decision:
    """配った後の門。続行 / 保留 / 中止 の3つを返す。

    **件数の検査を先に置く。** 逆にすると 3 件中1件失敗（33.3%）のような揺れた
    値で「中止」が出て、良い版を捨てることになる。
    """
    if new.inferences < min_inferences:
        return Decision("保留", (f"件数が足りません（{new.inferences} 件 < "
                                 f"{min_inferences} 件）",))
    limit = baseline.failure_rate * tolerance
    if new.failure_rate > limit:
        return Decision("中止", (f"新版の失敗率 {new.failure_rate:.3%} が"
                                 f"許容 {limit:.3%} を超えています",))
    return Decision("続行", ())


# --- 集約指標（プライバシー）-----------------------------------------------
def device_payload(report: DeviceReport, window_hours: float = OBSERVE_HOURS) -> dict:
    """端末が1日1回送る集約指標。生の入力は1バイトも含めない。"""
    return {"model_version": report.model_version, "app_version": report.app_version,
            "inferences": report.inferences, "failures": report.failures,
            "latency_buckets": list(report.buckets), "window_hours": window_hours}


def check_payload(payload: dict) -> None:
    """許可リストに無いキーがあれば例外にする（拒否リストにしない）。"""
    extra = set(payload) - set(DEVICE_PAYLOAD_KEYS)
    if extra:
        raise ValueError(f"送ってはいけない項目が含まれています: {sorted(extra)}")
    missing = set(DEVICE_PAYLOAD_KEYS) - set(payload)
    if missing:
        raise ValueError(f"必要な項目が足りません: {sorted(missing)}")


def telemetry_bytes(devices: int = DEVICE_COUNT, days: int = TELEMETRY_DAYS,
                    raw: bool = False) -> int:
    """テレメトリの転送量（③前提値）。raw=True は生データを送った場合。"""
    per_day = RAW_BYTES_PER_SAMPLE * SAMPLES_PER_DAY if raw else AGG_BYTES_PER_DAY
    return per_day * devices * days
