"""4 種類の分割（層化・層化なし・グループ・時系列）を同じデータで比べる（本文 2 節）。

実行:
    docker compose exec lab python src/session22/split_strategies.py
"""

from __future__ import annotations

from common import (
    OUT_DIR,
    cv_auc,
    fmt_scores,
    fold_positive_rates,
    group_cv,
    load_review_table,
    plain_cv,
    save_figure,
    series_cv,
    stratified_cv,
    summarize,
)

FIGURE_NAME = "s22_fold_scores.png"


def strategies(df) -> list[dict]:
    """4 つの分割で交差検証を回し、fold ごとのスコアと平均・標準偏差を集める。"""
    groups = df["customer_id"]
    # 時系列分割だけは「時間順に並べてから」渡す（並び順そのものが分割の条件になる）
    ordered = df.sort_values("reviewed_at")

    rows = [
        {"label": "① 層化 5 分割", "scores": cv_auc(df, stratified_cv())},
        {"label": "② 層化なし 5 分割", "scores": cv_auc(df, plain_cv())},
        {"label": "③ 顧客単位のグループ分割", "scores": cv_auc(df, group_cv(), groups=groups)},
        {"label": "④ 時系列分割", "scores": cv_auc(ordered, series_cv())},
    ]
    for row in rows:
        row["mean"], row["std"] = summarize(row["scores"])
    return rows


def group_facts(df) -> dict[str, int]:
    """グループ分割を考えるために、顧客の重なり具合を数える。"""
    counts = df["customer_id"].value_counts()
    return {
        "reviews": len(df),
        "customers": int(counts.size),
        "max_per_customer": int(counts.max()),
    }


def make_figure(rows: list[dict]) -> str:
    """fold ごとのスコアを 4 本の折れ線で重ねて描く。"""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    folds = [1, 2, 3, 4, 5]
    markers = ["o", "s", "^", "D"]
    for row, marker in zip(rows, markers):
        ax.plot(folds, row["scores"], marker=marker, label=f"{row['label']}（平均 {row['mean']:.4f}）")
    ax.set_xticks(folds)
    ax.set_xlabel("fold 番号")
    ax.set_ylabel("ROC AUC")
    ax.set_title("分割の型ごとの fold スコア（同じデータ・同じモデル）")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, loc="lower right")
    path = save_figure(fig, FIGURE_NAME)
    return str(path.relative_to(OUT_DIR.parent))


def main() -> None:
    df = load_review_table()
    rows = strategies(df)

    print("■ 4 つの分割で測った ROC AUC")
    print("分割の型                 | 平均     | 標準偏差")
    for row in rows:
        print(f"{row['label']:<24} | {row['mean']:.4f}   | {row['std']:.4f}")
    print()

    print("■ ① 層化 5 分割の内訳")
    print(f"fold ごとの ROC AUC : {fmt_scores(rows[0]['scores'])}")
    strat_rates = fold_positive_rates(df, stratified_cv())
    overall = float(df["is_high"].mean())
    worst = max(abs(rate - overall) for rate in strat_rates)
    print(f"全体の正例率 {overall:.4f} と各 fold の正例率の差（最大）: {worst:.4f}")
    print()

    print("■ ② 層化なし 5 分割の内訳")
    plain_rates = fold_positive_rates(df, plain_cv())
    print(f"fold ごとの正例率   : {fmt_scores(plain_rates)}")
    print(f"最大 − 最小         : {max(plain_rates) - min(plain_rates):.4f}")
    print()

    print("■ ③ グループ分割の前提")
    facts = group_facts(df)
    print(f"顧客 {facts['customers']} 人 / レビュー {facts['reviews']} 件 / 1 顧客あたり最大 {facts['max_per_customer']} 件")
    print()

    print("■ ④ 時系列分割の内訳")
    print(f"fold ごとの ROC AUC : {fmt_scores(rows[3]['scores'])}")
    print()

    print(f"図を保存しました: {make_figure(rows)}")


if __name__ == "__main__":
    main()
