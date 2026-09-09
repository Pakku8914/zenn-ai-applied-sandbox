#!/usr/bin/env python3
"""セッション16: 損益分岐を計算する（確約容量・バッチ・プロンプトキャッシュ）。

    docker compose exec app python src/session16/throughput.py

セッション9では「オンデマンド／バッチ推論／プロビジョンドスループット／
SageMaker エンドポイントのどれを選ぶか」を判断基準の表で決めました。
本章はその判断に**数字**を入れます。式は3つだけです。

* 1回あたりの費用 = (入力トークン × 入力単価 ＋ 出力トークン × 出力単価) ÷ 100万
* 確約容量の損益分岐（件/時）= 時間単価 ÷ 1回あたりの費用
* プロンプトキャッシュの損益分岐（回数）= (書き込み倍率 − 読み出し倍率) ÷ (1 − 読み出し倍率)

:::注意:::
プロビジョンドスループットの時間単価・バッチの割引率・キャッシュの倍率は、
**このファイルで宣言した仮定値**です（モックのカタログには時間単価がありません）。
実 Bedrock の価格はモデルとコミット期間で変わるため、絶対額ではなく
「どの入力が結論を動かすか」を読み取ってください。
"""

from __future__ import annotations

import math
import sys

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session01")
sys.path.insert(0, "/workspace/src/session02")
sys.path.insert(0, "/workspace/src/session09")

from bedrock_mock import catalog  # noqa: E402

import cascade  # noqa: E402

# セッション2・9と同じ参照ワークロード（入力1,000 / 出力300 トークン）。
# 章をまたいで同じ物差しを使うため、ここで定義し直さない
REFERENCE_WORKLOAD = cascade.REFERENCE_WORKLOAD

# 本文の表に出す短い呼び名（モデル ID は長いので表示だけ短くする）
SHORT_NAMES: dict[str, str] = {
    "amazon.nova-micro-v1:0": "Nova Micro",
    "amazon.nova-lite-v1:0": "Nova Lite",
    "amazon.nova-pro-v1:0": "Nova Pro",
    "anthropic.claude-3-5-haiku-20241022-v1:0": "Claude 3.5 Haiku",
    "anthropic.claude-sonnet-4-5-20250929-v1:0": "Claude Sonnet 4.5",
    "meta.llama3-3-70b-instruct-v1:0": "Llama 3.3 70B",
}

# ---------------------------------------------------------------------------
# 仮定値（実価格ではありません）
# ---------------------------------------------------------------------------

# プロビジョンドスループット1モデルユニットあたりの時間単価
ASSUMED_PROVISIONED_USD_PER_HOUR = 20.00
# バッチ推論の単価比（オンデマンドの何割か）
ASSUMED_BATCH_RATIO = 0.5
# プロンプトキャッシュの書き込み倍率・読み出し倍率
ASSUMED_CACHE_WRITE_MULTIPLIER = 1.25
ASSUMED_CACHE_READ_MULTIPLIER = 0.1

# 判定に使う想定トラフィック（ピーク時）
ASSUMED_REQUESTS_PER_HOUR = 5_000
# 1日の総件数（バッチとの比較に使う）
ASSUMED_REQUESTS_PER_DAY = 20_000


# ---------------------------------------------------------------------------
# 1. 1回あたりの費用と単価の非対称
# ---------------------------------------------------------------------------


def usd_per_request(model_id: str, workload: tuple[int, int] = REFERENCE_WORKLOAD) -> float:
    """参照ワークロード1回あたりの費用。すべての損益分岐の分母になる。"""
    return catalog.cost_usd(model_id, *workload)


def output_token_weight(model_id: str) -> float:
    """出力1トークンが入力何トークンぶんの費用か（出力単価 ÷ 入力単価）。"""
    spec, _ = catalog.resolve(model_id)
    if spec.input_usd_per_1m == 0:
        raise ValueError(f"入力単価が 0 のモデルです: {model_id}")
    return spec.output_usd_per_1m / spec.input_usd_per_1m


def input_cost_share(
    model_id: str, workload: tuple[int, int] = REFERENCE_WORKLOAD
) -> float:
    """入力が費用の何割を占めるか。**削る順番はこの値で決める。**"""
    spec, _ = catalog.resolve(model_id)
    in_usd = workload[0] * spec.input_usd_per_1m
    out_usd = workload[1] * spec.output_usd_per_1m
    return in_usd / (in_usd + out_usd)


# ---------------------------------------------------------------------------
# 2. 確約容量（プロビジョンドスループット）の損益分岐
# ---------------------------------------------------------------------------


def break_even_requests_per_hour(
    model_id: str,
    usd_per_hour: float = ASSUMED_PROVISIONED_USD_PER_HOUR,
    workload: tuple[int, int] = REFERENCE_WORKLOAD,
) -> float:
    """確約課金と等しくなる1時間あたりの件数。

    これを**超え続けて**いなければ、確約容量はオンデマンドより高くつきます。
    「超える」ではなく「超え続ける」であることが重要です。確約課金は
    呼んでいない時間にも発生するためです。
    """
    per_request = usd_per_request(model_id, workload)
    if per_request <= 0:
        raise ValueError(f"1回あたりの費用が 0 です: {model_id}")
    return usd_per_hour / per_request


def provisioned_verdict(
    model_id: str,
    requests_per_hour: int = ASSUMED_REQUESTS_PER_HOUR,
    usd_per_hour: float = ASSUMED_PROVISIONED_USD_PER_HOUR,
    workload: tuple[int, int] = REFERENCE_WORKLOAD,
) -> dict:
    """想定トラフィックで、確約とオンデマンドのどちらが安いかを判定する。"""
    per_request = usd_per_request(model_id, workload)
    break_even = break_even_requests_per_hour(model_id, usd_per_hour, workload)
    on_demand_per_hour = requests_per_hour * per_request
    return {
        "modelId": model_id,
        "usdPerRequest": per_request,
        "breakEvenPerHour": break_even,
        "breakEvenPerSecond": break_even / 3_600,
        "utilization": requests_per_hour / break_even,
        "onDemandUsdPerHour": round(on_demand_per_hour, 6),
        "cheaper": "provisioned" if on_demand_per_hour > usd_per_hour else "on_demand",
    }


# ---------------------------------------------------------------------------
# 3. バッチ推論
# ---------------------------------------------------------------------------


def batch_usd(
    model_id: str,
    requests: int = ASSUMED_REQUESTS_PER_DAY,
    ratio: float = ASSUMED_BATCH_RATIO,
    workload: tuple[int, int] = REFERENCE_WORKLOAD,
) -> float:
    """同じ件数をバッチ推論で流したときの費用（仮定の割引率で計算）。"""
    return round(requests * usd_per_request(model_id, workload) * ratio, 6)


def on_demand_usd(
    model_id: str,
    requests: int = ASSUMED_REQUESTS_PER_DAY,
    workload: tuple[int, int] = REFERENCE_WORKLOAD,
) -> float:
    return round(requests * usd_per_request(model_id, workload), 6)


# ---------------------------------------------------------------------------
# 4. プロンプトキャッシュの損益分岐
# ---------------------------------------------------------------------------


def cache_break_even_calls(
    write_multiplier: float = ASSUMED_CACHE_WRITE_MULTIPLIER,
    read_multiplier: float = ASSUMED_CACHE_READ_MULTIPLIER,
) -> int:
    """同じ接頭辞を何回使えばプロンプトキャッシュが得になるか。

    書き込みが割増（w > 1）なら、その割増ぶんを読み出しの割引で回収する
    必要があります。n ≥ (w − r) ÷ (1 − r) が条件です。
    **回数だけでなく「有効期間内に」その回数が来るか**で判断します。
    """
    if write_multiplier <= 1.0:
        return 1
    if read_multiplier >= 1.0:
        raise ValueError("読み出し倍率が 1 以上ではキャッシュに意味がありません")
    return math.ceil((write_multiplier - read_multiplier) / (1 - read_multiplier))


def cache_usd(
    model_id: str,
    *,
    calls: int,
    prefix_tokens: int,
    variable_tokens: int,
    output_tokens: int,
    cached: bool,
    write_multiplier: float = ASSUMED_CACHE_WRITE_MULTIPLIER,
    read_multiplier: float = ASSUMED_CACHE_READ_MULTIPLIER,
) -> float:
    """接頭辞をキャッシュした場合／しない場合の費用を返す。"""
    spec, _ = catalog.resolve(model_id)
    if cached:
        billed_input = (
            prefix_tokens * write_multiplier
            + prefix_tokens * read_multiplier * (calls - 1)
            + variable_tokens * calls
        )
    else:
        billed_input = (prefix_tokens + variable_tokens) * calls
    usd = (
        billed_input * spec.input_usd_per_1m
        + output_tokens * calls * spec.output_usd_per_1m
    ) / 1_000_000
    return round(usd, 6)


# ---------------------------------------------------------------------------
# 演習の本体
# ---------------------------------------------------------------------------


def main() -> None:
    print("=== 1. 入力単価と出力単価の非対称（参照ワークロード 入力1,000 / 出力300） ===")
    print("単価は 100万トークンあたりの USD（bedrock_mock/catalog.py の擬似単価）")
    for model_id, name in SHORT_NAMES.items():
        spec, _ = catalog.resolve(model_id)
        print(
            f"{name:<20}入力 {spec.input_usd_per_1m:>6.3f} / 出力"
            f" {spec.output_usd_per_1m:>6.3f} -> 出力の重み"
            f" {output_token_weight(model_id):>4.1f}倍 / 入力が費用の"
            f" {input_cost_share(model_id):>5.1%} / 1回"
            f" {usd_per_request(model_id):.6f} USD"
        )
    print("出力の重みが大きいモデルでは、入力を削るより出力を短くするほうが効きます")

    print()
    print("=== 2. 確約容量（プロビジョンドスループット）の損益分岐 ===")
    print(
        f"仮定: 1モデルユニット {ASSUMED_PROVISIONED_USD_PER_HOUR:.2f} USD/時"
        f" / 想定トラフィック {ASSUMED_REQUESTS_PER_HOUR:,} 件/時"
    )
    for model_id in (
        "amazon.nova-micro-v1:0",
        "amazon.nova-lite-v1:0",
        "amazon.nova-pro-v1:0",
        "anthropic.claude-sonnet-4-5-20250929-v1:0",
    ):
        v = provisioned_verdict(model_id)
        label = "プロビジョンド" if v["cheaper"] == "provisioned" else "オンデマンド"
        print(
            f"{SHORT_NAMES[model_id]:<20}損益分岐 {v['breakEvenPerHour']:>9,.0f} 件/時"
            f"（毎秒 {v['breakEvenPerSecond']:>5.1f}）"
            f" / 稼働率 {v['utilization']:>6.1%}"
            f" / オンデマンド {v['onDemandUsdPerHour']:>7.3f} USD/時 -> {label}"
        )
    print("確約は値引きではなく容量の予約です。単価の高いモデルほど早く元が取れます")

    print()
    print("=== 3. バッチ推論（仮定: オンデマンドの5割） ===")
    for model_id in ("amazon.nova-lite-v1:0", "anthropic.claude-sonnet-4-5-20250929-v1:0"):
        print(
            f"{SHORT_NAMES[model_id]:<20}{ASSUMED_REQUESTS_PER_DAY:,}件/日:"
            f" オンデマンド {on_demand_usd(model_id):.3f} USD"
            f" -> バッチ {batch_usd(model_id):.3f} USD"
        )
    print("待てる仕事を待てない経路で流すのが、いちばん多いむだです")

    print()
    print("=== 4. プロンプトキャッシュの損益分岐 ===")
    print(
        f"仮定: 書き込み {ASSUMED_CACHE_WRITE_MULTIPLIER}倍"
        f" / 読み出し {ASSUMED_CACHE_READ_MULTIPLIER}倍"
    )
    print(f"同じ接頭辞を何回使えば得になるか: {cache_break_even_calls()}回以上")
    print(
        "モックの会計（書き込みも読み出しも無料）では: "
        f"{cache_break_even_calls(0.0, 0.0)}回目から得"
    )
    scenario = {
        "calls": 10,
        "prefix_tokens": 2_000,
        "variable_tokens": 200,
        "output_tokens": 300,
    }
    model_id = "amazon.nova-lite-v1:0"
    plain = cache_usd(model_id, cached=False, **scenario)
    cached = cache_usd(model_id, cached=True, **scenario)
    mocked = cache_usd(
        model_id, cached=True, write_multiplier=0.0, read_multiplier=0.0, **scenario
    )
    print(
        f"接頭辞2,000 / 可変200 / 出力300 トークンを10回:"
        f" キャッシュなし {plain:.6f} USD"
        f" -> あり {cached:.6f} USD（{1 - cached / plain:.1%} 減）"
    )
    print(
        f"同じ条件をモックの会計で計算すると {mocked:.6f} USD"
        f"（{1 - mocked / plain:.1%} 減）。モックはキャッシュを実際より有利に見せます"
    )


if __name__ == "__main__":
    main()
