"""region と rating の欠損が「どういう仕組みで空いたのか」を検定で見極める。

欠損群（値が空いている行）と非欠損群（値が入っている行）で、
ほかの列の分布に差があるかを調べる。差がなければ MCAR と矛盾しない。

使い方:
    docker compose exec lab python src/session11/mechanism_check.py
"""

from __future__ import annotations

from common import (
    CHANNELS,
    chi2_compare,
    decide,
    load_customers,
    load_orders,
    load_reviews,
    order_count_per_customer,
    welch_compare,
)


def print_numeric(title: str, result: dict, digits: int) -> None:
    """数値列の比較結果を表示する。digits は「実測値として確定させた桁数」に合わせる。"""
    print(f"■ {title}")
    print(f"  欠損群 {result['n_a']:,} 件 / 非欠損群 {result['n_b']:,} 件")
    print(f"  平均: 欠損群 {result['mean_a']:.{digits}f} / 非欠損群 {result['mean_b']:.{digits}f}")
    print(f"  Welch の t 検定: p = {result['p']:.4f}")
    print(f"  {decide(result['p'])}")


def main() -> None:
    customers = load_customers()
    orders = load_orders()
    # 注文回数を顧客マスタの列として足す（母集団は重複を除いた 60,031 行）
    customers = customers.assign(order_count=order_count_per_customer(customers, orders).to_numpy())

    missing = customers["region"].isna()
    print(f"region の欠損群 {int(missing.sum()):,} 人 / 非欠損群 {int((~missing).sum()):,} 人")

    # 1. カテゴリ列（channel）の構成比を比べる → カイ二乗検定
    channel = chi2_compare(customers["channel"], missing)
    table = channel["table"][CHANNELS]
    ratio = channel["ratio"][CHANNELS]
    print("■ channel の構成比（欠損群 vs 非欠損群）")
    for name in CHANNELS:
        print(
            f"  {name}: 欠損群 {int(table.loc[True, name]):,} 人（{ratio.loc[True, name]:.4f}）"
            f" / 非欠損群 {int(table.loc[False, name]):,} 人（{ratio.loc[False, name]:.4f}）"
        )
    print(
        f"  カイ二乗検定: chi2 = {channel['chi2']:.4f}"
        f" / 自由度 {channel['dof']} / p = {channel['p']:.4f}"
    )
    print(f"  {decide(channel['p'])}")

    # 2. 数値列（birth_year）の平均を比べる → Welch の t 検定
    print_numeric("birth_year の平均（欠損群 vs 非欠損群）", welch_compare(customers["birth_year"], missing), 2)

    # 3. 別テーブルの情報（注文回数）も比べる。1 つの列だけ見て満足しない
    print_numeric("注文回数の平均（欠損群 vs 非欠損群）", welch_compare(customers["order_count"], missing), 3)

    # 4. rating の欠損も同じ手順で調べる。「本文を書く前に必ず両方やる」
    reviews = load_reviews()
    print_numeric(
        "rating が欠損した行の body_length（欠損群 vs 非欠損群）",
        welch_compare(reviews["body_length"], reviews["rating"].isna()),
        1,
    )


if __name__ == "__main__":
    main()
