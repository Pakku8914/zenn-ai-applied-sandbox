"""問題3: 月次売上の折れ線 ― 不完全な期間を帯で示す／除いて描く。"""

from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd

from common import monthly_amount, save_fig


def main() -> None:
    monthly = monthly_amount()
    inner = monthly.iloc[1:-1]  # 最初と最後の月を位置で落とす（日付を書き込まない）

    print("■ 月次売上")
    print(f"月数: {len(monthly)} か月（両端を除くと {len(inner)} か月）")
    print(f"最大: {monthly.idxmax():%Y-%m} / {int(round(monthly.max())):,} 円")
    print(f"最小: {monthly.idxmin():%Y-%m} / {int(round(monthly.min())):,} 円")
    print(f"末尾: {monthly.index[-1]:%Y-%m} / {int(round(monthly.iloc[-1])):,} 円")

    fig, axes = plt.subplots(2, 1, figsize=(9.5, 6.0), sharey=True)

    axes[0].plot(monthly.index, monthly.to_numpy() / 10_000, marker="o", markersize=3, color="#4c78a8")
    axes[0].axvspan(monthly.index[0] - pd.Timedelta(days=30), monthly.index[0], color="#e45756", alpha=0.15)
    axes[0].axvspan(monthly.index[-2], monthly.index[-1], color="#e45756", alpha=0.15)
    axes[0].set_title("全期間（赤い帯は集計期間が不完全な最初と最後の月）")
    axes[0].set_ylabel("売上（万円）")

    axes[1].plot(inner.index, inner.to_numpy() / 10_000, marker="o", markersize=3, color="#54a24b")
    axes[1].set_title("両端の月を除いた完全な月だけ")
    axes[1].set_xlabel("月")
    axes[1].set_ylabel("売上（万円）")

    save_fig(fig, "s08_q3_monthly_line.png")
    print("\n読み取り1: 上の図は末尾が崖のように落ちるが、これは 1 日分しか集計されていないため")
    print("読み取り2: 下の図は一貫した増加だけが残り、増加の傾きを読み違えずに報告できる")


if __name__ == "__main__":
    main()
