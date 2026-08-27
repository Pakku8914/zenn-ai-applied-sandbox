#!/usr/bin/env python3
"""推論サーバのメトリクスを「本書の名前」に直すアダプタ（セッション10）。

**上流の項目名を信じてはいけない。** llama.cpp が `/metrics` で公開する項目名は
版によって変わる（本書が最も陳腐化に弱いと考えている箇所のひとつ）。そこで上流の
名前をそのままダッシュボードや HPA に書かず、この層で本書の名前
（`inference_queue_length` など。セッション9 で決めた名前）に翻訳する。

    推論サーバ /metrics ──> このアダプタ ──> Prometheus ──> ダッシュボード / HPA

こうしておけば、上流の名前が変わったときに直すのは `SOURCES` の候補名だけで、
ダッシュボードもアラートも HPA も触らずに済む。

**ネットワークに出ない検証ができるように、同梱のサンプル文字列を持たせている。**
`--sample` を付けると通信せずに動く（`verify.py` はこの経路だけを使う）。

    python src/session10/inference_metrics.py --sample saturated
    python src/session10/inference_metrics.py --sample healthy --gateway-inflight 2
    python src/session10/inference_metrics.py --url http://llama:8080/metrics
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.session09.scaling import SLOTS_PER_INSTANCE as SLOTS  # noqa: E402

# ---------------------------------------------------------------------------
# 1. Prometheus のテキスト形式を読む（最小のパーサ）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Sample:
    """1行ぶんの観測値。`name{labels} value` の形。"""

    name: str
    labels: tuple[tuple[str, str], ...]
    value: float

    def label(self, key: str) -> str | None:
        return dict(self.labels).get(key)


def _to_float(token: str) -> float:
    """`+Inf` や `NaN` も読めるようにする（Prometheus の書式）。"""
    text = token.strip()
    if text in ("+Inf", "Inf", "inf", "+inf"):
        return math.inf
    if text in ("-Inf", "-inf"):
        return -math.inf
    if text in ("NaN", "nan"):
        return math.nan
    return float(text)


def _parse_labels(text: str) -> tuple[tuple[str, str], ...]:
    """`le="0.05",job="llama"` を並べ替えたタプルにする。

    **ラベル値にカンマや `}` を含む場合は正しく読めない。** 本書が扱うのは自分で
    出したメトリクスと単純なゲージだけなので、これで足りる。本番で任意の入力を
    読むなら専用のライブラリを使うこと（そこまで作るのは本書の主題ではない）。
    """
    pairs: list[tuple[str, str]] = []
    for part in text.split(","):
        chunk = part.strip()
        if not chunk:
            continue
        key, _, value = chunk.partition("=")
        pairs.append((key.strip(), value.strip().strip('"')))
    return tuple(sorted(pairs))


def parse_exposition(text: str) -> list[Sample]:
    """`# HELP` / `# TYPE` のコメント行を捨て、値の行だけを返す。"""
    samples: list[Sample] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "{" in line:
            name, _, rest = line.partition("{")
            label_part, _, tail = rest.partition("}")
            labels = _parse_labels(label_part)
        else:
            name, _, tail = line.partition(" ")
            labels = ()
        fields = tail.split()
        if not fields:
            continue  # 値が無い行は捨てる（壊れた行で落とさない）
        samples.append(Sample(name.strip(), labels, _to_float(fields[0])))
    return samples


def gauge(samples: list[Sample], name: str) -> float | None:
    """ラベルの付いていない値を1つ取り出す。無ければ **None**（0 ではない）。"""
    for sample in samples:
        if sample.name == name and not sample.labels:
            return sample.value
    return None


def bucket_counts(samples: list[Sample], name: str) -> list[tuple[float, float]]:
    """`name_bucket` の (le, **累積**件数) を昇順で返す。"""
    out: list[tuple[float, float]] = []
    for sample in samples:
        if sample.name != f"{name}_bucket":
            continue
        le = sample.label("le")
        if le is None:
            continue
        out.append((_to_float(le), sample.value))
    return sorted(out, key=lambda kv: kv[0])


def _fmt_value(value: float) -> str:
    if math.isinf(value):
        return "+Inf" if value > 0 else "-Inf"
    if math.isnan(value):
        return "NaN"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.6g}"


# ---------------------------------------------------------------------------
# 2. 上流の名前 → 本書の名前
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceMetric:
    """本書の名前1つと、それを作れる上流の候補名。"""

    ours: str
    candidates: tuple[str, ...]
    required: bool
    how_to_check: str
    meaning: str


SOURCES: tuple[SourceMetric, ...] = (
    SourceMetric(
        "inference_active_requests",
        # 2026-08-15 にこの環境で見えた名前。**保証はない。**
        # 自分の環境で curl して、見つけた名前をここに足す（足すだけでよい）
        ("llamacpp:requests_processing",),
        True,
        "curl -s http://localhost:8080/metrics | grep -i -e process -e slot",
        "スロットに載って処理中の件数。ここからスロット使用率を作る",
    ),
    SourceMetric(
        "inference_queue_length",
        ("llamacpp:requests_deferred",),
        True,
        "curl -s http://localhost:8080/metrics | grep -i -e defer -e queue -e wait",
        "スロットに載れず待っている件数。セッション9 で選んだ第一の指標",
    ),
    SourceMetric(
        "inference_kv_cache_ratio",
        ("llamacpp:kv_cache_usage_ratio",),
        False,
        "curl -s http://localhost:8080/metrics | grep -i kv",
        "KVキャッシュの埋まり具合。無くてもスケールはできる",
    ),
)

SOURCE_BY_OURS = {s.ours: s for s in SOURCES}

OUR_METRICS: tuple[tuple[str, str, str], ...] = (
    ("inference_queue_length", "gauge",
     "スロットに載れず待っている件数（セッション9 の第一の指標）"),
    ("inference_slot_utilization", "gauge",
     "使用中スロット ÷ 総スロット（1.0 で頭打ち）"),
    ("inference_active_requests", "gauge", "スロットに載って処理中の件数"),
    ("inference_kv_cache_ratio", "gauge", "KVキャッシュの埋まり具合（0.0〜1.0）"),
)

GATEWAY_METRICS: tuple[tuple[str, str, str, str], ...] = (
    ("inference_gateway_requests_total", "counter",
     "ゲートウェイが受け付けた件数", "requests"),
    ("inference_gateway_rate_limited_total", "counter",
     "429 で断った件数（セッション5）", "rate_limited"),
    ("inference_gateway_rejected_total", "counter",
     "503 で断った件数（バックプレッシャ）", "rejected"),
    ("inference_gateway_cache_hits_total", "counter",
     "応答キャッシュのヒット件数（セッション6）", "cache_hits"),
    ("inference_gateway_errors_total", "counter", "上流エラーの件数", "errors"),
    ("inference_gateway_inflight", "gauge",
     "ゲートウェイが上流に投げて未完了の件数", "inflight"),
)


@dataclass(frozen=True)
class AdaptResult:
    """翻訳の結果。**欠測は 0 で埋めず、欠測として持ち歩く。**"""

    values: dict[str, float]
    used: dict[str, str]
    missing: tuple[str, ...]
    derived: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.missing

    def render(self) -> str:
        """Prometheus のテキスト形式で出す。無い項目は行そのものを出さない。"""
        lines: list[str] = []
        for name, kind, help_text in OUR_METRICS:
            if name not in self.values:
                continue
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} {kind}")
            lines.append(f"{name} {_fmt_value(self.values[name])}")
        return "\n".join(lines)

    def advice(self) -> list[str]:
        lines: list[str] = []
        for name in self.missing:
            src = SOURCE_BY_OURS.get(name)
            lines.append(f"[欠測] {name} が作れませんでした")
            if src is None:
                continue
            lines.append(f"  意味    : {src.meaning}")
            lines.append(f"  上流候補: {', '.join(src.candidates)}")
            lines.append(f"  確認    : {src.how_to_check}")
            lines.append("  対処    : 見つけた名前を SOURCES の candidates に足す（1行）")
        if self.missing:
            lines.append(
                "**欠測を 0 で埋めてはいけません。** 0 を返すとオートスケールは"
                "「待ちが無い」と判断して動きません（セッション9 の <unknown> と同じ状態）")
        return lines


def adapt(text: str, *, slots: int = SLOTS,
          gateway_stats: dict | None = None,
          sources: tuple[SourceMetric, ...] = SOURCES) -> AdaptResult:
    """上流の `/metrics` を本書の名前に直す。

    キュー長の作り方は3段構えである。
      1. 上流に直接それらしい項目があれば使う
      2. 無ければ「ゲートウェイが投げた件数 − サーバが処理中の件数」で作る
      3. どちらも無ければ **欠測**にする（0 を入れない）
    """
    samples = parse_exposition(text)
    values: dict[str, float] = {}
    used: dict[str, str] = {}
    missing: list[str] = []

    for src in sources:
        for candidate in src.candidates:
            found = gauge(samples, candidate)
            if found is not None:
                values[src.ours] = found
                used[src.ours] = candidate
                break
        else:
            if src.required:
                missing.append(src.ours)

    derived: list[str] = []
    active = values.get("inference_active_requests")
    if active is not None:
        if slots < 1:
            raise ValueError("slots は 1 以上を指定してください")
        # スロット使用率は上流に無いことがあるので必ず自分で作る
        values["inference_slot_utilization"] = min(active / slots, 1.0)
        derived.append("inference_slot_utilization")

    inflight = (gateway_stats or {}).get("inflight")
    if "inference_queue_length" in missing and active is not None and inflight is not None:
        values["inference_queue_length"] = max(float(inflight) - active, 0.0)
        derived.append("inference_queue_length")
        missing.remove("inference_queue_length")

    return AdaptResult(values, used, tuple(missing), tuple(derived))


def render_gateway(stats: dict) -> str:
    """ゲートウェイの `/stats`（JSON）を Prometheus のテキスト形式に直す。"""
    lines: list[str] = []
    for name, kind, help_text, key in GATEWAY_METRICS:
        if key not in stats:
            continue
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {kind}")
        lines.append(f"{name} {_fmt_value(float(stats[key]))}")
    cache = stats.get("cache") or {}
    if "hit_rate" in cache:
        lines.append("# HELP inference_cache_hit_ratio 応答キャッシュのヒット率")
        lines.append("# TYPE inference_cache_hit_ratio gauge")
        lines.append(f"inference_cache_hit_ratio {_fmt_value(float(cache['hit_rate']))}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. 分布で見る（ヒストグラム）
# ---------------------------------------------------------------------------

TTFT_BOUNDS: tuple[float, ...] = (0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0)
"""TTFT のバケット境界（秒）。**SLO の 1.0 秒を境界に入れてある。**

境界に SLO を置いておくと、違反率が「累積件数の引き算」だけで出る。
境界に無い値の違反率は、この実装ではわざとエラーにする（推測させない）。
"""

TPOT_BOUNDS: tuple[float, ...] = (0.01, 0.02, 0.0426, 0.08, 0.16, 0.32)
"""TPOT のバケット境界（秒）。0.0426 秒は総時間の SLO から逆算した上限。

総時間 p95 ≦ 3,000 ms のうち TTFT に 1,000 ms を使うと、残りは 2,000 ms。
48 トークン出すなら 2,000 ÷ 47 ＝ 42.6 ms/トークンが上限になる。
"""


@dataclass(frozen=True)
class LatencyHistogram:
    """バケットで持つ分布。**バケットは累積で公開する**のが Prometheus の約束。

    `counts` は「そのバケットに入った件数」（累積ではない）で持ち、
    公開するときだけ累積に直す。人が数えるときは非累積のほうが楽なためである。
    """

    name: str
    bounds: tuple[float, ...]
    counts: tuple[int, ...]
    sum_seconds: float
    help_text: str = ""

    def __post_init__(self) -> None:
        if len(self.counts) != len(self.bounds) + 1:
            raise ValueError(
                f"counts は bounds より1つ多く必要です（最後が +Inf のバケット）: "
                f"bounds {len(self.bounds)} / counts {len(self.counts)}")
        if list(self.bounds) != sorted(self.bounds):
            raise ValueError("bounds は昇順で指定してください")
        if any(c < 0 for c in self.counts):
            raise ValueError("counts に負の数は入りません")

    @property
    def total(self) -> int:
        return sum(self.counts)

    def cumulative(self) -> list[int]:
        out: list[int] = []
        running = 0
        for count in self.counts:
            running += count
            out.append(running)
        return out

    @property
    def average_seconds(self) -> float:
        """`_sum ÷ _count`。**平均はここでしか出せない**（バケットからは出ない）。"""
        return self.sum_seconds / self.total if self.total else 0.0

    def quantile(self, q: float) -> float:
        """バケット内を直線で補間して分位点を出す（Prometheus と同じ考え方）。

        最上位のバケット（+Inf）に落ちたときは **+Inf を返す**。境界の設計を
        間違えると p95 が出ないことを、黙って隠さずに見せるためである。
        """
        if not 0.0 < q < 1.0:
            raise ValueError("q は 0 と 1 の間で指定してください")
        total = self.total
        if total == 0:
            return 0.0
        rank = q * total
        cumulative = 0
        lower = 0.0
        for index, count in enumerate(self.counts):
            previous = cumulative
            cumulative += count
            if cumulative >= rank:
                if index >= len(self.bounds):
                    return math.inf
                upper = self.bounds[index]
                if count == 0:
                    return upper
                return lower + (upper - lower) * (rank - previous) / count
            if index < len(self.bounds):
                lower = self.bounds[index]
        return math.inf

    def at_most(self, bound: float) -> float:
        """`bound` 以下だった割合。**境界に無い値は推測せずエラーにする。**"""
        try:
            index = self.bounds.index(bound)
        except ValueError:
            raise ValueError(
                f"{bound} はバケットの境界にありません（境界: {list(self.bounds)}）。"
                "SLO の値を境界に入れておくと、違反率が引き算だけで出ます") from None
        total = self.total
        return self.cumulative()[index] / total if total else 0.0

    def violation_ratio(self, slo_seconds: float) -> float:
        """SLO を超えた割合。"""
        return 1.0 - self.at_most(slo_seconds)

    def render(self) -> str:
        lines: list[str] = []
        if self.help_text:
            lines.append(f"# HELP {self.name} {self.help_text}")
        lines.append(f"# TYPE {self.name} histogram")
        for bound, cumulative in zip(self.bounds, self.cumulative()):
            lines.append(f'{self.name}_bucket{{le="{bound}"}} {cumulative}')
        lines.append(f'{self.name}_bucket{{le="+Inf"}} {self.total}')
        lines.append(f"{self.name}_sum {self.sum_seconds}")
        lines.append(f"{self.name}_count {self.total}")
        return "\n".join(lines)

    def summary(self) -> str:
        return (f"{self.name}: n={self.total} "
                f"平均={self.average_seconds * 1000:.0f}ms "
                f"p50={self.quantile(0.5) * 1000:.0f}ms "
                f"p95={self.quantile(0.95) * 1000:.0f}ms")

    @classmethod
    def from_values(cls, name: str, values_seconds: list[float],
                    bounds: tuple[float, ...] = TTFT_BOUNDS,
                    help_text: str = "") -> LatencyHistogram:
        counts = [0] * (len(bounds) + 1)
        for value in values_seconds:
            for index, bound in enumerate(bounds):
                if value <= bound:
                    counts[index] += 1
                    break
            else:
                counts[-1] += 1
        return cls(name, tuple(bounds), tuple(counts),
                   float(sum(values_seconds)), help_text)

    @classmethod
    def from_exposition(cls, text: str, name: str,
                        help_text: str = "") -> LatencyHistogram:
        """公開した形（累積）から読み戻す。ダッシュボードが見ている形の検算に使う。"""
        samples = parse_exposition(text)
        pairs = bucket_counts(samples, name)
        finite = [(le, value) for le, value in pairs if math.isfinite(le)]
        total = next((value for le, value in pairs if math.isinf(le)), None)
        if total is None:
            raise ValueError(f"{name}_bucket の +Inf が見つかりません")
        counts: list[int] = []
        previous = 0.0
        for _, value in finite + [(math.inf, total)]:
            counts.append(int(round(value - previous)))
            previous = value
        total_sum = gauge(samples, f"{name}_sum")
        return cls(name, tuple(le for le, _ in finite), tuple(counts),
                   total_sum if total_sum is not None else 0.0, help_text)


# 分布の「読み方」を練習するための値（**実測ではない**。20 件ぶんの作り物）。
# 平均は SLO の中に見えるのに p95 は SLO の2倍という、いちばん危ない形を作ってある。
TTFT_EXAMPLE = LatencyHistogram(
    name="inference_ttft_seconds",
    bounds=TTFT_BOUNDS,
    counts=(0, 10, 5, 2, 1, 1, 1, 0),
    sum_seconds=6.0,
    help_text="最初のトークンが返るまでの時間の分布",
)

# TPOT も同じ形（**実測ではない**。20 件ぶんの作り物）。
# 平均 30ms は上限 42.6ms の内側なのに、10% が上限を超えている。
# 「遅いのは一部のリクエストだけ」を分布で見るための例である。
TPOT_EXAMPLE = LatencyHistogram(
    name="inference_tpot_seconds",
    bounds=TPOT_BOUNDS,
    counts=(0, 14, 4, 1, 1, 0, 0),
    sum_seconds=0.6,
    help_text="1トークンあたりの生成時間の分布",
)


# ---------------------------------------------------------------------------
# 4. 同梱サンプル（通信しない）
# ---------------------------------------------------------------------------

SAMPLE_SATURATED = """\
# HELP llamacpp:prompt_tokens_total Number of prompt tokens processed.
# TYPE llamacpp:prompt_tokens_total counter
llamacpp:prompt_tokens_total 12480
# HELP llamacpp:tokens_predicted_total Number of generation tokens processed.
# TYPE llamacpp:tokens_predicted_total counter
llamacpp:tokens_predicted_total 960
# HELP llamacpp:requests_processing Number of requests processing.
# TYPE llamacpp:requests_processing gauge
llamacpp:requests_processing 2
# HELP llamacpp:requests_deferred Number of requests deferred.
# TYPE llamacpp:requests_deferred gauge
llamacpp:requests_deferred 2
# HELP llamacpp:kv_cache_usage_ratio KV-cache usage ratio.
# TYPE llamacpp:kv_cache_usage_ratio gauge
llamacpp:kv_cache_usage_ratio 0.35
"""
"""並列4（飽和した状態）に対応する例。スロット2 が埋まり、2 件が待っている。"""

SAMPLE_HEALTHY = """\
# TYPE llamacpp:requests_processing gauge
llamacpp:requests_processing 2
# TYPE llamacpp:requests_deferred gauge
llamacpp:requests_deferred 0
# TYPE llamacpp:kv_cache_usage_ratio gauge
llamacpp:kv_cache_usage_ratio 0.18
"""
"""並列2（健全な状態）に対応する例。スロットは埋まっているが待ちが無い。"""

SAMPLE_NO_DEFERRED = """\
# TYPE llamacpp:requests_processing gauge
llamacpp:requests_processing 2
"""
"""待ちを表す項目が無い版の例。ゲートウェイの件数から作るしかない。"""

SAMPLE_RENAMED = """\
# 項目名が変わった（あるいは別の実装に載せ替えた）例
server_requests_in_flight 2
server_kv_cache_ratio 0.18
"""
"""上流の名前が変わった例。**黙って 0 を返さず欠測として報告する**ことを見る。"""

SAMPLES = {
    "saturated": SAMPLE_SATURATED,
    "healthy": SAMPLE_HEALTHY,
    "no-deferred": SAMPLE_NO_DEFERRED,
    "renamed": SAMPLE_RENAMED,
}


# ---------------------------------------------------------------------------
# 5. CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="推論サーバの /metrics を本書の名前に直す")
    parser.add_argument("--sample", choices=sorted(SAMPLES), default=None,
                        help="同梱サンプルから作る（通信しない）")
    parser.add_argument("--file", default=None, help="保存済みの /metrics を読む")
    parser.add_argument("--url", default=None,
                        help="/metrics の URL（例 http://llama:8080/metrics）")
    parser.add_argument("--slots", type=int, default=SLOTS, help="-np に渡した値")
    parser.add_argument("--gateway-inflight", type=float, default=None,
                        help="ゲートウェイの inflight（キュー長の代替に使う）")
    args = parser.parse_args(argv)

    if args.url:
        import httpx  # 通信するときだけ読み込む

        text = httpx.get(args.url, timeout=5.0).text
    elif args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    else:
        text = SAMPLES[args.sample or "saturated"]

    stats = None if args.gateway_inflight is None else {"inflight": args.gateway_inflight}
    result = adapt(text, slots=args.slots, gateway_stats=stats)
    body = result.render()
    if body:
        print(body)
    for line in result.advice():
        print(line, file=sys.stderr)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
