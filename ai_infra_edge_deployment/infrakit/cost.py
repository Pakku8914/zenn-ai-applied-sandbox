"""コスト計算（セッション10・16の参照実装）。

自前ホスティングの単価は「インスタンス時間単価 ÷ その時間に処理できたリクエスト数」で決まる。
利用率が低いと単価が跳ねる、という構造を計算で見せる。

単価の前提（インスタンス時間単価・API のトークン単価）は**読者が入れる値**であり、
本書は特定クラウドの価格を書かない（最も速く陳腐化するため）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SelfHosted:
    """自前ホスティングの単価。"""

    hourly_cost: float          # インスタンス1台の1時間あたりコスト（読者が入れる）
    instances: int              # 台数
    rps_per_instance: float     # 1台が安定して処理できるリクエスト/秒（実測値を入れる）
    utilization: float          # 実際に使われている割合（0.0〜1.0）

    @property
    def requests_per_hour(self) -> float:
        return self.rps_per_instance * 3600 * self.instances * self.utilization

    @property
    def cost_per_hour(self) -> float:
        return self.hourly_cost * self.instances

    @property
    def cost_per_1k_requests(self) -> float:
        if self.requests_per_hour <= 0:
            return float("inf")
        return self.cost_per_hour / self.requests_per_hour * 1000


@dataclass(frozen=True)
class HostedAPI:
    """クラウドAPI の単価。"""

    input_price_per_1m: float   # 1Mトークンあたりの入力単価（読者が入れる）
    output_price_per_1m: float
    input_tokens: float         # 1リクエストの平均入力トークン
    output_tokens: float

    @property
    def cost_per_1k_requests(self) -> float:
        per_request = (self.input_tokens / 1_000_000 * self.input_price_per_1m
                       + self.output_tokens / 1_000_000 * self.output_price_per_1m)
        return per_request * 1000


def breakeven_requests_per_hour(self_hosted: SelfHosted, api: HostedAPI) -> float:
    """自前ホスティングが API より安くなる1時間あたりのリクエスト数。"""
    api_per_request = api.cost_per_1k_requests / 1000
    if api_per_request <= 0:
        return float("inf")
    return self_hosted.cost_per_hour / api_per_request


def utilization_table(base: SelfHosted, utilizations=(0.1, 0.2, 0.5, 0.7, 0.9)) -> list[dict]:
    """利用率を振ったときの単価。章の表に使う。"""
    rows = []
    for u in utilizations:
        variant = SelfHosted(base.hourly_cost, base.instances, base.rps_per_instance, u)
        rows.append({"utilization": u,
                     "requests_per_hour": round(variant.requests_per_hour),
                     "cost_per_1k_requests": round(variant.cost_per_1k_requests, 4)})
    return rows
