"""外れ値の線を IQR 法と 3σ 法の 2 通りで引き、結果の違いを見る。

使い方:
    docker compose exec lab python src/session09/outlier_lines.py
"""

from __future__ import annotations

from common import load_orders


def main() -> None:
    quantity = load_orders()["quantity"]

    # IQR 法：Q3 + 1.5 × IQR より大きい値を外れ値とする定番の手法
    q1 = quantity.quantile(0.25)
    q3 = quantity.quantile(0.75)
    iqr = q3 - q1
    iqr_upper = q3 + 1.5 * iqr

    # 3σ 法：平均 + 3 × 標準偏差より大きい値を外れ値とする
    mean = quantity.mean()
    std = quantity.std()
    sigma_upper = mean + 3 * std

    iqr_mask = quantity > iqr_upper
    sigma_mask = quantity > sigma_upper
    bulk_mask = quantity >= 15  # 生成時に仕込まれた「まとめ買い」

    print("■ quantity に外れ値の線を 2 通りの方法で引く（60,031 行）")
    print(f"IQR 法 : Q1 {q1:.1f} / Q3 {q3:.1f} / IQR {iqr:.1f} → 上限 {iqr_upper:.4f}")
    print(f"3σ 法  : 平均 {mean:.4f} / 標準偏差 {std:.4f} → 上限 {sigma_upper:.4f}")
    print(f"IQR 法が外れ値とする行 : {int(iqr_mask.sum()):,} 行（全体の {iqr_mask.mean():.1%}）")
    print(f"3σ 法が外れ値とする行  : {int(sigma_mask.sum()):,} 行（全体の {sigma_mask.mean():.1%}）")
    print(f"まとめ買い（15 冊以上）: {int(bulk_mask.sum()):,} 行")
    print(f"3σ 法の結果がまとめ買いと完全に一致するか : {bool(sigma_mask.equals(bulk_mask))}")


if __name__ == "__main__":
    main()
