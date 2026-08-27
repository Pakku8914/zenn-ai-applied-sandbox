"""セッション2：測った数字を読むための小さな道具箱。

`infrakit` は章をまたいで凍結しているので、章で足す計算はこちらに置く。
すべて純関数で、推論サーバもモデルも要らない。だから単体で検証できる。
"""

from __future__ import annotations

import math

# レポートを同じ表に並べてよいか判定するときに、一致していてほしい条件
COMPARE_KEYS = ("max_tokens", "warmup", "model", "n_ctx", "slots")


def split_tpot(total_ms: float, ttft_ms: float, tokens_out: int) -> float:
    """総時間から TTFT を引いて、2トークン目以降の1トークンあたりの時間を出す。

    最初のトークンだけは「入力をまとめて処理する時間」を含む。割る前に引かないと、
    入力が長いリクエストほど TPOT が悪く見える別物の数字になってしまう。
    1トークンしか出ていないときは TPOT を定義できないので 0.0 を返す。
    """
    if tokens_out <= 1:
        return 0.0
    return (total_ms - ttft_ms) / (tokens_out - 1)


def rebuild_total(ttft_ms: float, tpot_ms: float, tokens_out: int) -> float:
    """TTFT と TPOT から総時間を組み立て直す。出力長を変えた見積もりに使う。"""
    return ttft_ms + tpot_ms * max(tokens_out - 1, 0)


def tokens_per_second(tokens_out: int, elapsed_ms: float) -> float:
    """スループット（トークン/秒）。「どれだけ生成できたか」を測る。"""
    return tokens_out / (elapsed_ms / 1000.0) if elapsed_ms > 0 else 0.0


def requests_per_second(n: int, elapsed_ms: float) -> float:
    """スループット（リクエスト/秒）。「何件さばけたか」を測る。"""
    return n / (elapsed_ms / 1000.0) if elapsed_ms > 0 else 0.0


def spread(stats: dict[str, float]) -> float:
    """p95 ÷ p50。1 に近いほど安定、大きいほど「たまに極端に遅い」。"""
    p50 = stats.get("p50", 0.0)
    return stats.get("p95", 0.0) / p50 if p50 else 0.0


def min_samples(quantile: float) -> int:
    """その分位点を「実際に観測した値」で語るのに最低限必要な件数。

    p95 なら 20 件、p99 なら 100 件。これ未満で p95 と名乗ってはいけない。

    9桁で丸めてから切り上げるのは、二進小数の誤差対策。素直に書くと
    1 / (1 - 0.90) が 10.000000000000002 になり、11 件と返ってしまう。
    """
    if not 0.0 < quantile < 1.0:
        raise ValueError("quantile は 0 と 1 の間で指定してください")
    return math.ceil(round(1.0 / (1.0 - quantile), 9))


def effective_quantile(n: int, quantile: float = 0.95) -> float:
    """`infrakit.load.percentiles` の p95 が、その件数では実際に何分位かを返す。

    件数が足りないと、p95 と名乗った値が実際には p80 でしかない。
    """
    if n <= 0:
        return 0.0
    index = max(int(n * quantile) - 1, 0)
    return (index + 1) / n


def comparable(a: dict, b: dict, keys: tuple[str, ...] = COMPARE_KEYS) -> list[str]:
    """2つのレポートの conditions を比べ、揃っていない項目名を返す。

    空リストなら並べて比較してよい。1つでも返ってきたら、その2本は別の実験。
    """
    return [k for k in keys if a.get(k) != b.get(k)]


def check_slo(observed: dict, slo: dict[str, float]) -> list[str]:
    """SLO を超えた項目を「指標.分位点」の形で返す。空リストなら合格。

    observed: {"ttft": {"p50": ..., "p95": ...}, "total": {...}}（レポートそのまま）
    slo:      {"ttft.p95": 500.0, "total.p95": 3000.0}
    """
    violations: list[str] = []
    for key in sorted(slo):
        metric, _, quantile = key.partition(".")
        value = observed.get(metric, {}).get(quantile)
        if value is not None and value > slo[key]:
            violations.append(key)
    return violations
