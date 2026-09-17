"""SHAP で「1 件の予測」を特徴量ごとの寄与に分解し、加法性を検算する。

使い方:
    docker compose exec lab python src/session26/shap_local.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (
    SHAP_ROWS,
    save_figure,
    shap_bundle,
    shap_local,
    shap_local_check,
    shap_mean_abs,
)

ROW = 0  # 説明するお客さま（先頭の 1 行）


def draw(path_name: str) -> str:
    """基準値から出発して寄与を積み上げる waterfall 風の図を描く。"""
    table = shap_local(ROW)
    check = shap_local_check(ROW)
    # 効いている順（絶対値の大きい順）に積む
    ordered = table.reindex(table["shap"].abs().sort_values(ascending=False).index)

    fig, ax = plt.subplots(figsize=(8.5, 4.4))
    start = check["base"]
    labels = []
    for position, row in enumerate(ordered.itertuples(index=False)):
        ax.barh(
            position,
            row.shap,
            left=start,
            color="#e45756" if row.shap > 0 else "#4c78a8",
            height=0.6,
        )
        labels.append(f"{row.feature} = {int(row.value)}")
        start += row.shap

    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.axvline(check["base"], color="#888888", linestyle="--", linewidth=1.0)
    ax.axvline(check["logit"], color="#333333", linewidth=1.0)
    ax.set_xlabel("対数オッズ（左の破線が基準値・右の実線が最終の予測）")
    ax.set_title(
        f"1 行目の予測の分解：基準値 {check['base']:.4f} ＋ 寄与の合計 {check['total']:.4f}"
        f" = {check['logit']:.4f} → 確率 {check['proba_from_shap']:.4f}"
    )
    fig.tight_layout()
    path = save_figure(fig, path_name)
    plt.close(fig)
    return path.name


def main() -> None:
    bundle = shap_bundle()

    print(f"■ 1. TreeExplainer で先頭 {SHAP_ROWS} 行を説明する")
    print("出た警告（全文は長いので冒頭だけ表示します）:")
    for message in bundle["warnings"]:
        print(message)
    print(f"shap_values の形     : {bundle['values'].shape}")
    print(
        f"expected_value       : {bundle['base']:.4f}"
        f"（dtype {bundle['base_dtype']}・形 {bundle['base_shape']} のスカラー）"
    )
    print()

    print("■ 2. 平均絶対値 ― 全体としてどの列が効いたか")
    print(f"{'順位':<4}{'特徴量':<16}平均絶対値")
    for rank, row in enumerate(shap_mean_abs().itertuples(index=False), start=1):
        print(f"{str(rank) + '位':<4}{row.feature:<16}{row.mean_abs:.4f}")
    print()

    print("■ 3. 1 行目のレビューを分解する（局所的説明）")
    print(f"{'特徴量':<16}{'値':>6}{'SHAP 値':>10}")
    for row in shap_local(ROW).itertuples(index=False):
        print(f"{row.feature:<16}{int(row.value):>6}{row.shap:>+10.4f}")
    print()

    check = shap_local_check(ROW)
    print("■ 4. 加法性を検算する（これが『1 件ごとの説明』の根拠）")
    print(f"SHAP 値の合計        : {check['total']:.4f}")
    print(f"基準値 expected_value: {check['base']:.4f}")
    print(f"合計 ＋ 基準値       : {check['logit']:.4f}（対数オッズ）")
    print(f"シグモイド関数で確率 : {check['proba_from_shap']:.4f}")
    print(f"predict_proba の値   : {check['proba_from_model']:.4f}")
    print(f"一致するか           : {check['matches']}")

    name = draw("s26_shap_local.png")
    print(f"図を保存しました: outputs/{name}")


if __name__ == "__main__":
    main()
