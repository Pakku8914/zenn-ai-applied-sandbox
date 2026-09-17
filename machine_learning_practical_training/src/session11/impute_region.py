"""region の欠損を 3 つの方針で処理し、件数と分布がどう変わるかを見比べる。

使い方:
    docker compose exec lab python src/session11/impute_region.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # 画面を持たないコンテナで図を PNG として保存するための設定
import matplotlib.pyplot as plt

from common import MISSING_LABEL, OUT_DIR, REGIONS, load_customers, load_orders, region_missing_revenue


def save_figure(deleted, filled, n_deleted: int, n_filled: int) -> None:
    """「削除した場合」と「最頻値で埋めた場合」の地域分布を並べて保存する。"""
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.8), sharey=True)
    panels = [
        (axes[0], deleted, f"行を削除（{n_deleted:,} 人）"),
        (axes[1], filled, f"最頻値で代入（{n_filled:,} 人）"),
    ]
    for ax, series, title in panels:
        counts = series.value_counts().reindex(REGIONS)
        ax.bar(REGIONS, counts.to_numpy(), color="#4c78a8")
        ax.set_title(title)
        ax.set_xlabel("地域")
        ax.tick_params(axis="x", rotation=45)
    axes[0].set_ylabel("人数")
    axes[1].annotate(
        "東京だけ 392 人ぶん積み増される",
        xy=(0, int((filled == "東京").sum())),
        xytext=(1.2, 3400),
        arrowprops={"arrowstyle": "->", "color": "#e45756"},
        color="#e45756",
    )
    fig.suptitle("region の欠損 392 件を「削除」した場合と「最頻値で代入」した場合")
    fig.tight_layout()
    OUT_DIR.mkdir(exist_ok=True)
    fig.savefig(OUT_DIR / "s11_region_impute.png", dpi=120)
    plt.close(fig)


def main() -> None:
    customers = load_customers()
    orders = load_orders()

    # 方針 A: 欠損のある行を削除する（リストワイズ削除）
    deleted = customers.dropna(subset=["region"])
    lost = round(region_missing_revenue(customers, orders))
    print("■ 方針 A: 行を削除する")
    print(f"  {len(customers):,} 人 → {len(deleted):,} 人（{len(customers) - len(deleted):,} 人を捨てた）")
    print(f"  捨てた顧客の売上: {lost:,} 円（地域別の集計から消える）")

    # 方針 B: 定数で埋める（「不明」という 1 つのカテゴリにする）
    constant = customers.assign(region=customers["region"].fillna(MISSING_LABEL))
    print("■ 方針 B: 定数で埋める")
    print(
        f"  {len(constant):,} 人（カテゴリ数 {customers['region'].nunique()}"
        f" → {constant['region'].nunique()}）"
    )
    print(f"  {MISSING_LABEL}: {int((constant['region'] == MISSING_LABEL).sum()):,} 人")

    # 方針 C: 最頻値で埋める
    mode_value = customers["region"].mode().iloc[0]
    filled = customers.assign(region=customers["region"].fillna(mode_value))
    before = int((deleted["region"] == mode_value).sum())
    after = int((filled["region"] == mode_value).sum())
    print("■ 方針 C: 最頻値で埋める")
    print(f"  最頻値: {mode_value}")
    print(f"  {mode_value}: {before:,} 人 → {after:,} 人")
    print(
        f"  {mode_value} の構成比: {before / len(deleted):.2%}（削除・分母 {len(deleted):,}）"
        f" → {after / len(filled):.2%}（代入・分母 {len(filled):,}）"
    )
    counts = filled["region"].value_counts().reindex(REGIONS)
    print("  代入後の分布: " + " / ".join(f"{name} {int(value):,}" for name, value in counts.items()))

    save_figure(deleted["region"], filled["region"], len(deleted), len(filled))
    print("■ 図を保存しました: outputs/s11_region_impute.png")


if __name__ == "__main__":
    main()
