#!/usr/bin/env python3
"""セッション2: 基盤モデルの選定表を、カタログの実データから作る。

選定の観点は7つ（能力・コンテキスト長・モダリティ・レイテンシクラス・単価・
ツール利用可否・提供リージョン）ですが、コードで機械的に絞れるのは
「提供リージョン」を除く6つです。リージョンは環境の情報なので、
モデル ID を解決する層（model_router.py）の設定側で扱います。

    docker compose exec app python src/session02/model_matrix.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/workspace")

from bedrock_mock import catalog  # noqa: E402

# 単価の比較は「どんな呼び出しを何回するか」を固定しないと意味を持たない。
# 参照ワークロード = 入力1,000トークン / 出力300トークン（1問1答のヘルプデスク想定）
REFERENCE_WORKLOAD = (1_000, 300)
# 出力が長い用途（下書き生成・展開型の要約）を比べるためのワークロード
OUTPUT_HEAVY_WORKLOAD = (200, 2_000)


def conversational() -> list["catalog.ModelSpec"]:
    """会話（Converse API）の候補になるモデルだけを返す。

    埋め込み専用モデルは `supports_converse=False` なのでここで必ず落ちます。
    「一番安いモデルを探す」処理に埋め込みモデルが混ざる事故を、
    価格で並べる前に構造で防ぐのが狙いです。
    """
    return [spec for spec in catalog.MODELS.values() if spec.supports_converse]


def call_cost_usd(
    model_id: str, workload: tuple[int, int] = REFERENCE_WORKLOAD
) -> float:
    """1回の呼び出しの推定コスト（USD）。単価は擬似価格表から取る。"""
    return catalog.cost_usd(model_id, workload[0], workload[1])


def matches(
    spec: "catalog.ModelSpec",
    *,
    modality: tuple[str, ...] = (),
    min_context_window: int = 0,
    min_output_tokens: int = 0,
    needs_tool_use: bool = False,
    needs_optimized_latency: bool = False,
) -> bool:
    """要件（能力の下限）を満たすかどうかを判定する。

    ここに書かれているのは「妥協できない条件」だけです。単価は入れません。
    **絞り込みと値段の比較を混ぜると、要件を満たさないモデルが
    「安いから」という理由で候補に残ります。**
    """
    if not set(modality) <= set(spec.modality):
        return False
    if spec.context_window < min_context_window:
        return False
    if spec.max_output_tokens < min_output_tokens:
        return False
    if needs_tool_use and not spec.supports_tool_use:
        return False
    if needs_optimized_latency and spec.latency_class != "optimized":
        return False
    return True


def select(
    *, workload: tuple[int, int] = REFERENCE_WORKLOAD, **requirements
) -> list[str]:
    """要件を満たす候補を、参照ワークロードの安い順に並べて返す。

    2段で決めるのが選定の型です。
      1段目: 要件で絞る（満たさないものは候補から消える）
      2段目: 残った候補を「同じ仕事をさせたときの費用」で並べる
    """
    hit = [spec for spec in conversational() if matches(spec, **requirements)]
    return [
        spec.model_id
        for spec in sorted(
            hit, key=lambda s: (call_cost_usd(s.model_id, workload), s.model_id)
        )
    ]


def cheapest(**kwargs) -> str | None:
    """要件を満たす中で最も安いモデル ID。候補が無ければ None。"""
    ids = select(**kwargs)
    return ids[0] if ids else None


def rows(workload: tuple[int, int] = REFERENCE_WORKLOAD) -> list[dict]:
    """選定表の行データ（安い順）。本文の比較表はこの出力です。"""
    table = [
        {
            "modelId": spec.model_id,
            "provider": spec.provider,
            "modality": "/".join(spec.modality),
            "contextWindow": spec.context_window,
            "maxOutputTokens": spec.max_output_tokens,
            "toolUse": spec.supports_tool_use,
            "latencyClass": spec.latency_class,
            "inputUsdPer1M": spec.input_usd_per_1m,
            "outputUsdPer1M": spec.output_usd_per_1m,
            "usdPerCall": call_cost_usd(spec.model_id, workload),
        }
        for spec in conversational()
    ]
    table.sort(key=lambda row: (row["usdPerCall"], row["modelId"]))
    return table


# 要件のパターン。試験で問われるのは「この要件ならどれか」なので、
# 要件を先に書き、候補は毎回コードに出させる
SCENARIOS: tuple[tuple[str, dict], ...] = (
    (
        "分類・ルーティング（テキストのみ・ツール不要）",
        {"modality": ("TEXT",), "min_context_window": 128_000},
    ),
    ("画像つき問い合わせ（スクリーンショットを読む）", {"modality": ("IMAGE",)}),
    (
        "対話 UI（ツール利用・体感速度・長い履歴）",
        {
            "modality": ("TEXT",),
            "min_context_window": 200_000,
            "needs_tool_use": True,
            "needs_optimized_latency": True,
        },
    ),
    ("長文の下書き生成（出力32,000トークン以上）", {"min_output_tokens": 32_000}),
    ("満たせない要件（コンテキスト長 500,000 以上）", {"min_context_window": 500_000}),
)


def main() -> None:
    print("=== 基盤モデル選定表（参照ワークロード: 入力1,000 / 出力300 トークン） ===")
    for row in rows():
        print(
            f"{row['modelId']} | {row['modality']}"
            f" | ctx {row['contextWindow']:,} | out {row['maxOutputTokens']:,}"
            f" | tool {'yes' if row['toolUse'] else 'no'} | {row['latencyClass']}"
            f" | {row['usdPerCall']:.6f} USD/call"
        )

    print()
    print("=== 要件から候補を絞る（安い順） ===")
    for label, requirement in SCENARIOS:
        ids = select(**requirement)
        print(f"[{label}]")
        if ids:
            print(f"  候補{len(ids)}件 / 最安: {ids[0]}")
        else:
            print("  候補なし（要件を見直すか、入力の分割・別サービスを検討する）")


if __name__ == "__main__":
    main()
