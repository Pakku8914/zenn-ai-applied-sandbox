"""問題2: 欠損の仕組みを検定で見極める（region と rating）。

使い方:
    docker compose exec lab python src/session11/q2_mechanism_check.py
"""

from __future__ import annotations

from common import (
    ALPHA,
    CHANNELS,
    chi2_compare,
    load_customers,
    load_orders,
    load_reviews,
    order_count_per_customer,
    welch_compare,
)


def main() -> None:
    customers = load_customers()
    orders = load_orders()  # 重複を除いた 60,031 行が母集団（本書の規約）
    customers = customers.assign(order_count=order_count_per_customer(customers, orders).to_numpy())
    missing = customers["region"].isna()

    print("■ 帰無仮説 H0: 欠損群と非欠損群で、その列の分布は同じ")
    print(f"  欠損群 {int(missing.sum()):,} 人 / 非欠損群 {int((~missing).sum()):,} 人")

    # カテゴリ列はカイ二乗検定
    channel = chi2_compare(customers["channel"], missing)
    ratio = channel["ratio"][CHANNELS]
    for name in CHANNELS:
        print(f"  channel={name}: 欠損群 {ratio.loc[True, name]:.4f}"
              f" / 非欠損群 {ratio.loc[False, name]:.4f}")
    print(f"  chi2 = {channel['chi2']:.4f} / dof = {channel['dof']} / p = {channel['p']:.4f}")

    # 数値列は Welch の t 検定。桁数は本書が実測値として確定させた桁に合わせる
    reviews = load_reviews()
    numeric = [
        ("birth_year", welch_compare(customers["birth_year"], missing), 2),
        ("注文回数", welch_compare(customers["order_count"], missing), 3),
        ("body_length（rating の欠損）", welch_compare(reviews["body_length"], reviews["rating"].isna()), 1),
    ]
    for label, result, digits in numeric:
        print(f"  {label}: 欠損群 {result['mean_a']:.{digits}f}"
              f" / 非欠損群 {result['mean_b']:.{digits}f} / p = {result['p']:.4f}")

    p_values = [channel["p"]] + [result["p"] for _, result, _ in numeric]
    print(f"■ 有意水準 {ALPHA} を下回った検定の数: {sum(p < ALPHA for p in p_values)} / {len(p_values)}")
    print("■ 結論: 調べた列では差が見つからなかった（MCAR と矛盾しない）。")
    print("  MCAR であることの証明ではなく、MNAR はこの手順では判定できない。")


if __name__ == "__main__":
    main()
