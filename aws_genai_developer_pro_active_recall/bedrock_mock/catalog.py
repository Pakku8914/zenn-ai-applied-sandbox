"""モック環境が提供する基盤モデル（FM）のカタログと擬似価格表。

:::注意:::
ここに書かれている単価は **教材のコスト計算演習を決定的にするための固定値** です。
2026-09-08 時点で公開されていたオンデマンド価格を参考にしていますが、
実際の請求額を見積もる用途には使えません（Bedrock の価格は改定されます）。
学習の狙いは「絶対額」ではなく「モデル間の桁の差」と「入力／出力の非対称」を体で覚えることです。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    provider: str
    modality: tuple[str, ...]  # 入力として受け付けるモダリティ
    context_window: int  # トークン
    max_output_tokens: int
    input_usd_per_1m: float
    output_usd_per_1m: float
    supports_converse: bool = True
    supports_streaming: bool = True
    supports_tool_use: bool = False
    latency_class: str = "standard"  # standard | optimized
    embedding_dimensions: tuple[int, ...] = field(default_factory=tuple)
    notes: str = ""


# 教材で扱うモデルだけを載せた最小カタログ。
# 「安い小型モデル」「中位」「高性能」「埋め込み」「レイテンシ最適化」を必ず1つ以上含める
# ——モデルカスケード／ティア分けの演習（ドメイン4）が成立しなくなるため。
MODELS: dict[str, ModelSpec] = {
    "amazon.nova-micro-v1:0": ModelSpec(
        model_id="amazon.nova-micro-v1:0",
        provider="Amazon",
        modality=("TEXT",),
        context_window=128_000,
        max_output_tokens=5_000,
        input_usd_per_1m=0.035,
        output_usd_per_1m=0.14,
        supports_tool_use=True,
        latency_class="optimized",
        notes="テキスト専用の最小モデル。分類・ルーティング・抽出向け",
    ),
    "amazon.nova-lite-v1:0": ModelSpec(
        model_id="amazon.nova-lite-v1:0",
        provider="Amazon",
        modality=("TEXT", "IMAGE", "VIDEO"),
        context_window=300_000,
        max_output_tokens=5_000,
        input_usd_per_1m=0.06,
        output_usd_per_1m=0.24,
        supports_tool_use=True,
        latency_class="optimized",
        notes="低コストのマルチモーダル。既定の実験用モデル",
    ),
    "amazon.nova-pro-v1:0": ModelSpec(
        model_id="amazon.nova-pro-v1:0",
        provider="Amazon",
        modality=("TEXT", "IMAGE", "VIDEO"),
        context_window=300_000,
        max_output_tokens=5_000,
        input_usd_per_1m=0.80,
        output_usd_per_1m=3.20,
        supports_tool_use=True,
        notes="Nova 系の上位。エージェントのプランナー役に使う",
    ),
    "anthropic.claude-3-5-haiku-20241022-v1:0": ModelSpec(
        model_id="anthropic.claude-3-5-haiku-20241022-v1:0",
        provider="Anthropic",
        modality=("TEXT", "IMAGE"),
        context_window=200_000,
        max_output_tokens=8_192,
        input_usd_per_1m=0.80,
        output_usd_per_1m=4.00,
        supports_tool_use=True,
        latency_class="optimized",
        notes="安価で速い。要約・分類・ツール呼び出しの実務標準",
    ),
    "anthropic.claude-sonnet-4-5-20250929-v1:0": ModelSpec(
        model_id="anthropic.claude-sonnet-4-5-20250929-v1:0",
        provider="Anthropic",
        modality=("TEXT", "IMAGE"),
        context_window=200_000,
        max_output_tokens=64_000,
        input_usd_per_1m=3.00,
        output_usd_per_1m=15.00,
        supports_tool_use=True,
        notes="推論の質が要る工程に。クロスリージョン推論プロファイル経由でも呼べる",
    ),
    "meta.llama3-3-70b-instruct-v1:0": ModelSpec(
        model_id="meta.llama3-3-70b-instruct-v1:0",
        provider="Meta",
        modality=("TEXT",),
        context_window=128_000,
        max_output_tokens=8_192,
        input_usd_per_1m=0.72,
        output_usd_per_1m=0.72,
        notes="入力と出力が同単価。オープンウェイト系の代表として置いている",
    ),
    "amazon.titan-embed-text-v2:0": ModelSpec(
        model_id="amazon.titan-embed-text-v2:0",
        provider="Amazon",
        modality=("TEXT",),
        context_window=8_192,
        max_output_tokens=0,
        input_usd_per_1m=0.02,
        output_usd_per_1m=0.0,
        supports_converse=False,
        supports_streaming=False,
        embedding_dimensions=(256, 512, 1024),
        notes="埋め込み専用。次元数を選べる（既定 1024）",
    ),
}

# クロスリージョン推論プロファイルの接頭辞。
# 実 Bedrock では地理ごとに `us.` / `eu.` / `apac.` を付けた ID を使う。
# モックでは接頭辞を剥がして同じモデルに解決し、レスポンスに解決結果を記録する。
CROSS_REGION_PREFIXES = ("us.", "eu.", "apac.", "jp.")


def resolve(model_id: str) -> tuple[ModelSpec, str | None]:
    """モデル ID を解決し、(仕様, 使われた地理接頭辞) を返す。

    未知の ID は呼び出し側で ValidationException にする。
    """
    for prefix in CROSS_REGION_PREFIXES:
        if model_id.startswith(prefix):
            base = model_id[len(prefix) :]
            if base in MODELS:
                return MODELS[base], prefix.rstrip(".")
            break
    if model_id in MODELS:
        return MODELS[model_id], None
    raise KeyError(model_id)


def cost_usd(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """入出力トークン数から擬似コストを計算する（小数第6位で丸め）。"""
    spec, _ = resolve(model_id)
    usd = (
        input_tokens * spec.input_usd_per_1m + output_tokens * spec.output_usd_per_1m
    ) / 1_000_000
    return round(usd, 6)


def summary_rows() -> list[dict[str, object]]:
    """本文の比較表にそのまま貼れる形でカタログを返す。"""
    return [
        {
            "modelId": spec.model_id,
            "provider": spec.provider,
            "modality": "/".join(spec.modality),
            "contextWindow": spec.context_window,
            "inputUsdPer1M": spec.input_usd_per_1m,
            "outputUsdPer1M": spec.output_usd_per_1m,
            "latencyClass": spec.latency_class,
            "toolUse": spec.supports_tool_use,
        }
        for spec in MODELS.values()
    ]
