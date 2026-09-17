"""対数変換で分布の歪みがどう変わるかを数値と図で確かめる。

使い方:
    docker compose exec lab python src/session12/transform_skew.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # 画面を持たないコンテナ内で図を PNG として保存する
import matplotlib.pyplot as plt
import numpy as np

from common import BULK_THRESHOLD, CLIP_UPPER, OUT_DIR, load_orders


def main() -> None:
    quantity = load_orders()["quantity"]
    kept = quantity.loc[quantity < BULK_THRESHOLD]
    clipped = quantity.clip(upper=CLIP_UPPER)
    logged = np.log1p(quantity)  # log(1 + x)。0 が入っていても計算できる

    print(f"■ 歪度（右に裾が長いほど大きくなる）— {len(quantity):,} 行")
    print(f"そのまま   : {quantity.skew():.4f}")
    print(f"log1p 変換 : {logged.skew():.4f}")
    print()

    print("■ 対数変換は値の大小関係を変えない")
    for books_count in (1, 3, BULK_THRESHOLD, int(quantity.max())):
        print(f"{books_count:>2} 冊 → log1p {float(np.log1p(books_count)):.4f}")
    print(f"順序が保たれるか : {bool((np.log1p(quantity).rank() == quantity.rank()).all())}")
    print()

    # 4 通りの処置を並べて描く。件数の差が 3 桁あるので、縦軸は対数目盛にする
    panels = [
        ("そのまま", quantity, f"平均 {quantity.mean():.4f}"),
        (f"{BULK_THRESHOLD} 冊以上を除外", kept, f"平均 {kept.mean():.4f}"),
        (f"上限 {CLIP_UPPER} 冊でクリップ", clipped, f"平均 {clipped.mean():.4f}"),
        ("log1p 変換", logged, f"歪度 {logged.skew():.4f}"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(9, 6))
    for ax, (title, values, note) in zip(axes.ravel(), panels):
        ax.hist(values, bins=40, color="#4c78a8")
        ax.set_yscale("log")  # 118 件の山を見えるようにする
        ax.set_title(f"{title}（{note}）", fontsize=11)
        ax.set_xlabel("注文冊数" if title != "log1p 変換" else "log1p(注文冊数)")
        ax.set_ylabel("件数（対数目盛）")
    fig.suptitle("外れ値への 4 通りの処置と quantity の分布", fontsize=13)
    fig.tight_layout()
    OUT_DIR.mkdir(exist_ok=True)
    fig.savefig(OUT_DIR / "s12_treatment_compare.png", dpi=100)
    plt.close(fig)
    print("図を保存しました: outputs/s12_treatment_compare.png")


if __name__ == "__main__":
    main()
