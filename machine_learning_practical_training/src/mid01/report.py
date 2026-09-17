"""中間プロジェクト①の検算を表示し、レポート本文を書き出す。

    docker compose exec lab python src/mid01/report.py
    → 標準出力に検算とレポート本文、outputs/mid01_report.md に同じレポート

レポートの行は build_report() だけで作ります。画面用と保存用にコードを分けると、
必ずどちらかが古くなって数値が食い違います。
"""

from __future__ import annotations

from analysis import (
    age_segment,
    age_share,
    category_summary,
    cross_revenue,
    population,
    region_revenue,
)
from common import CATEGORY_ORDER, OUT_DIR, yen

REPORT_NAME = "mid01_report.md"
# 「検索が占める割合」を比べるカテゴリ（売上上位 3 つ）
SHARE_TARGETS = ["技術書", "ビジネス", "実用書"]


def print_checks() -> None:
    """作業中の検算。レポートに載せる数値を 1 画面で確認する。"""
    pop = population()
    summary = category_summary()
    share = age_share()
    segment = age_segment()
    age_cross, channel_cross = cross_revenue("年代"), cross_revenue("channel")
    by_region, missing = region_revenue()
    total = float(pop["total_revenue"])
    breakdown = sum(round(float(v)) for v in summary["revenue"])
    in_table = float(by_region.sum())

    print("■ 検算（レポートに載せる数値の確認）")
    print(
        f"母集団      : 生 {pop['raw_orders']:,.0f} 件 → 重複除外 {pop['unique_orders']:,.0f} 件"
        f" → 有効注文 {pop['valid_orders']:,.0f} 件 / 売上 {yen(total)}"
    )
    print(
        f"顧客        : 全 {pop['all_customers']:,.0f} 人 / 注文あり {pop['ordered_customers']:,.0f} 人"
        f" / 有効注文あり {pop['valid_customers']:,.0f} 人 / アクティブ {pop['active_customers']:,.0f} 人"
    )
    print("カテゴリ売上: " + " / ".join(
        f"{name} {yen(v)}" for name, v in summary["revenue"].sort_values(ascending=False).items()
    ))
    print("カテゴリ注文数: " + " / ".join(
        f"{name} {v:,.0f} 件" for name, v in summary["orders"].sort_values(ascending=False).items()
    ))
    print("1 注文あたり: " + " / ".join(
        f"{name} {v:,.1f} 円"
        for name, v in summary["mean_amount"].sort_values(ascending=False).items()
    ))
    print(
        f"丸め        : 丸めた内訳の合計 {breakdown:,} 円 / 総額 {round(total):,} 円"
        f"（差 {breakdown - round(total):+,} 円）"
    )
    print("年代×カテゴリ: " + " / ".join(
        f"{age} × {category} {yen(v)}"
        for (age, category), v in age_cross.stack().sort_values(ascending=False).head(5).items()
    ))
    print("技術書の年代別: " + " / ".join(
        f"{age} {yen(v)}" for age, v in age_cross["技術書"].items()
    ))
    print("技術書の構成比: " + " / ".join(
        f"{age} {v:.1f}%" for age, v in share["技術書"].items()
    ))
    print("構成比の幅  : " + " / ".join(
        f"{c} {share[c].min():.1f}〜{share[c].max():.1f}%" for c in reversed(CATEGORY_ORDER)
    ))
    print("行ごとの合計: " + " / ".join(
        f"{age} {v:.1f}%" for age, v in share.sum(axis=1).items()
    ))
    customers, price = segment["customers"], segment["mean_unit_price"]
    print(
        "年代別顧客数: "
        + " / ".join(f"{age} {v:,.0f} 人" for age, v in customers.items())
        + f"（合計 {customers.sum():,.0f} 人）"
    )
    print(
        f"顧客数の倍率: {customers.max() / customers.min():.2f} 倍"
        f"（{customers.idxmax()} {customers.max():,.0f} 人 ÷ {customers.idxmin()} {customers.min():,.0f} 人）"
    )
    print(f"平均単価    : 最小 {price.min():,.0f} 円 / 最大 {price.max():,.0f} 円")
    print("流入経路×カテゴリ: " + " / ".join(
        f"{channel} × {category} {yen(v)}"
        for (channel, category), v in channel_cross.stack().sort_values(ascending=False).head(5).items()
    ))
    print("検索の割合  : " + " / ".join(
        f"{name} {channel_cross.loc['検索', name] / summary.loc[name, 'revenue'] * 100:.1f}%"
        for name in SHARE_TARGETS
    ))
    print("地域別上位 3: " + " / ".join(f"{name} {yen(v)}" for name, v in by_region.head(3).items()))
    print(f"region 未入力: {yen(missing)}（地域別のどの行にも現れない）")
    print(f"検算        : 地域別の合計 + 未入力 = 総額 … {abs(in_table + missing - total) < 0.01}")
    print(
        f"東京の割合  : {by_region.iloc[0] / total * 100:.1f}%（総額を分母） / "
        f"{by_region.iloc[0] / in_table * 100:.1f}%（地域別の合計を分母）"
    )


def build_report() -> list[str]:
    """レポート本文（Markdown）の全行を返す。数値はすべて集計関数から埋める。"""
    pop = population()
    summary = category_summary()
    share = age_share()
    segment = age_segment()
    age_cross, channel_cross = cross_revenue("年代"), cross_revenue("channel")
    by_region, missing = region_revenue()

    total = float(pop["total_revenue"])
    tech, business = share["技術書"], share["ビジネス"]
    customers, price = segment["customers"], segment["mean_unit_price"]
    breakdown = sum(round(float(v)) for v in summary["revenue"])
    in_table = float(by_region.sum())
    ratio = customers.max() / customers.min()
    top_age, top_category = age_cross.stack().idxmax()
    top_channel, top_channel_category = channel_cross.stack().idxmax()
    channel_share = " / ".join(
        f"{name} {channel_cross.loc['検索', name] / summary.loc[name, 'revenue'] * 100:.1f}%"
        for name in SHARE_TARGETS
    )
    total_share = by_region.iloc[0] / total * 100
    table_share = by_region.iloc[0] / in_table * 100

    return [
        "# 分析レポート：どのカテゴリの本が、どの顧客層に売れているか",
        "",
        "## 0. 母集団と定義",
        "",
        f"- 母集団：有効注文 {pop['valid_orders']:,.0f} 件"
        f"（生データ {pop['raw_orders']:,.0f} 件から完全重複 30 件とキャンセルを除外）",
        "- 売上の定義：unit_price × quantity × (1 − discount_rate) を行ごとに丸めずに合計し、"
        f"表示のときだけ四捨五入する（総額 {yen(total)}）",
        f"- 顧客数：有効注文が 1 件以上ある顧客 {pop['valid_customers']:,.0f} 人を分母に使う"
        f"（全顧客 {pop['all_customers']:,.0f} 人・注文のある {pop['ordered_customers']:,.0f} 人ではない）",
        "- 年代：年齢（2026 − birth_year）を 5 区分（20代以下 / 30代 / 40代 / 50代 / 60代以上）",
        "- 集計コード：src/mid01/analysis.py ／ 図：src/mid01/figures.py",
        f"- 検算：丸めた内訳の合計 {breakdown:,} 円は総額と {abs(breakdown - round(total)):,} 円ずれる"
        "（内訳の合計を総額として使わない）",
        f"- 検算：地域別の合計 + region 未入力分 = 総額 … {abs(in_table + missing - total) < 0.01}",
        "",
        "## 1. 結論",
        "",
        f"1. 売上はカテゴリで大きく偏っている。技術書 {yen(summary.loc['技術書', 'revenue'])}は総額の"
        f" {summary.loc['技術書', 'revenue'] / total * 100:.1f}% を占め、5 カテゴリのうち最大である（図1a）。",
        "2. ただしそれは技術書がよく注文されているためではない。注文数は技術書"
        f" {summary.loc['技術書', 'orders']:,.0f} 件・小説 {summary.loc['小説', 'orders']:,.0f} 件でほぼ並び、"
        f"差は 1 注文あたりの金額（技術書 {summary.loc['技術書', 'mean_amount']:,.1f} 円・"
        f"小説 {summary.loc['小説', 'mean_amount']:,.1f} 円）にある（図1b）。",
        f"3. 絶対額で最大のセルは {top_age} × {top_category} {yen(age_cross.stack().max())}だが、"
        f"{top_age}は顧客数が最も多い年代（{customers.loc[top_age]:,.0f} 人）である（図2a）。",
        "4. 年代によってカテゴリの好みが違うとは言えない。売上構成比は技術書が"
        f" {tech.min():.1f}%〜{tech.max():.1f}%、ビジネスが {business.min():.1f}%〜{business.max():.1f}% と、"
        "どの年代でもほぼ同じである（図3）。",
        f"5. 年代別の売上の差は顧客数の差で説明できる。顧客数は {customers.idxmin()}"
        f" {customers.min():,.0f} 人から {customers.idxmax()} {customers.max():,.0f} 人まで {ratio:.2f} 倍"
        f"違うのに対し、注文 1 件あたりの平均単価は {price.min():,.0f} 円〜{price.max():,.0f} 円で"
        "差がない（図4）。",
        f"6. 流入経路でも同じ構造である。絶対額の最大は {top_channel} × {top_channel_category}"
        f" {yen(channel_cross.stack().max())}だが、検索が占める割合は {channel_share} で"
        "ほぼ一定である（図2b）。",
        f"7. 地域別では{by_region.index[0]}に集中している（{yen(by_region.iloc[0])}）。ただし region が"
        f"未入力の顧客の売上 {yen(missing)}は地域別のどの行にも入らないため、割合は分母によって"
        f" {total_share:.1f}%（総額）と {table_share:.1f}%（地域別の合計）に変わる。",
        "",
        "## 2. 図",
        "",
        "| 図 | 何の図か | 読み取れること | 注意 |",
        "| :--- | :--- | :--- | :--- |",
        "| 図1 mid01_fig1_category.png | カテゴリ別の売上と 1 注文あたりの平均金額 "
        "| 売上は技術書が最大だが、注文数では小説とほぼ並ぶ | 売上の順位を「人気の順位」と読まない |",
        "| 図2 mid01_fig2_crosstab.png | 年代 × カテゴリ・流入経路 × カテゴリの売上（絶対額） "
        f"| 濃いセルは {top_age} × {top_category}、{top_channel} × {top_channel_category} "
        "| 絶対額はセグメントの大きさに比例する |",
        "| 図3 mid01_fig3_age_share.png | 年代別のカテゴリ構成比（行ごとに 100%） "
        f"| 5 本の線がすべてほぼ水平（技術書 {tech.min():.1f}%〜{tech.max():.1f}%） "
        "| 構成比は分母（年代ごとの売上合計）を明示する |",
        "| 図4 mid01_fig4_segment_size.png | 年代別の顧客数と平均単価 "
        f"| 顧客数は {ratio:.2f} 倍違うが、平均単価はそろっている "
        "| 平均単価の軸は 0 から描く（切ると差があるように見える） |",
        "",
        "## 3. この分析で言えないこと",
        "",
        "- 「年代によって売れるカテゴリが違う」という当初の仮説は、このデータでは支持されなかった。"
        "ただしこれは違いが存在しないことの証明ではなく、今回の区切り（5 年代 × 5 カテゴリ）と"
        "今回の期間では違いが見えなかったという意味である。",
        "- 相関を因果として読まない。検索経由の売上が大きいことは「検索広告を増やせば売上が増える」を"
        "意味しない。流入経路は顧客が自分で選んだ結果であり、こちらで割り当てた実験ではない。",
        f"- 地域別の集計には region が未入力の顧客の売上 {yen(missing)}が入らない。割合を書くときは"
        "必ず分母を添える。",
        "- 評価（星）の差を検定した場合、「有意でない」を「差がない」と言い換えない"
        "（技術書 vs ビジネスは p = 0.1024 で有意ではないが、差が無いと確認できたわけではない）。",
        "",
        "## 4. 次の一歩",
        "",
        "- 顧客の属性（年代・流入経路・地域）では売れ方の違いを説明できなかった。次は購入間隔や"
        "過去に買ったカテゴリという「顧客の行動」を使い、集計して眺めるのではなく予測して"
        "確かめる段階に進む。",
    ]


def main() -> None:
    print_checks()
    lines = build_report()
    print("\n■ レポート本文（outputs/" + REPORT_NAME + " と同じ内容）\n")
    print("\n".join(lines))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / REPORT_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nレポートを書き出しました: outputs/{REPORT_NAME}")


if __name__ == "__main__":
    main()
