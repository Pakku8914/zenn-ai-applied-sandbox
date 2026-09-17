"""列を足しても精度は動かない ― それでも Pipeline を使う理由（本文 7 節）。

カテゴリを category だけにした構成（セッション17 以降で使ってきた形）と、
region・channel を足した構成を、同じ Pipeline の形で比べます。

実行:
    docker compose exec lab python src/session25/feature_sets.py
"""

from __future__ import annotations

import numpy as np

from common import (
    CATEGORICAL,
    CATEGORICAL_S17,
    NUMERIC,
    build_pipeline,
    build_preprocess,
    cv_auc,
    features_target,
    fmt_scores,
    holdout_auc,
    load_review_table,
    save_figure,
    split,
    summarize,
)

FIGURE_NAME = "s25_feature_sets.png"


def evaluate(df, categorical: list[str], label: str) -> dict[str, object]:
    """1 つの特徴量セットについて、変換後の列数・ホールドアウト・交差検証をまとめて測る。"""
    X, y = features_target(df, NUMERIC, categorical)
    X_train, _, _, _ = split(X, y)
    n_columns = int(build_preprocess(NUMERIC, categorical).fit(X_train).transform(X_train).shape[1])
    scores = cv_auc(build_pipeline(NUMERIC, categorical), X, y)
    mean, std = summarize(scores)
    return {
        "label": label,
        "categorical": list(categorical),
        "n_input": int(X.shape[1]),
        "n_columns": n_columns,
        "holdout": holdout_auc(df, NUMERIC, categorical),
        "scores": [float(s) for s in scores],
        "mean": mean,
        "std": std,
    }


def compare(df) -> dict[str, object]:
    """2 つの特徴量セットを並べ、差がばらつきの中に収まるかを判定する。"""
    small = evaluate(df, CATEGORICAL_S17, "category だけ")
    large = evaluate(df, CATEGORICAL, "+ region + channel")
    return {
        "small": small,
        "large": large,
        "holdout_gap": large["holdout"] - small["holdout"],
        "mean_gap": small["mean"] - large["mean"],
        "gap_within_std": bool(abs(small["mean"] - large["mean"]) < min(small["std"], large["std"])),
        "region_missing": int(df["region"].isna().sum()),
        "region_missing_rate": float(df["region"].isna().mean()),
        "channel_missing": int(df["channel"].isna().sum()),
    }


def make_figure(result: dict) -> str:
    """ホールドアウト 1 回と交差検証の平均±標準偏差を、2 つの構成で並べる。"""
    import matplotlib.pyplot as plt

    rows = [result["small"], result["large"]]
    labels = [f"{row['label']}\n（変換後 {row['n_columns']} 列）" for row in rows]
    x = np.arange(len(rows))
    width = 0.36

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    holdout = ax.bar(
        x - width / 2, [row["holdout"] for row in rows], width, color="#2980b9", label="ホールドアウト 1 回"
    )
    cv = ax.bar(
        x + width / 2,
        [row["mean"] for row in rows],
        width,
        yerr=[row["std"] for row in rows],
        capsize=6,
        color="#7f8c8d",
        label="層化 5 分割の平均 ± 標準偏差",
    )
    for bars in (holdout, cv):
        for bar in bars:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.0015,
                f"{bar.get_height():.4f}",
                ha="center",
                fontsize=10,
            )
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(0.80, 0.84)
    ax.set_ylabel("ROC AUC")
    ax.set_title("列を 11 本足しても評価は動かない（縦軸は 0.80〜0.84 に拡大）")
    ax.legend(loc="lower right", fontsize=9)
    return save_figure(fig, FIGURE_NAME)


def main() -> None:
    df = load_review_table()
    result = compare(df)

    print("■ 1. 足した列の欠損")
    print(
        f"region の欠損  : {result['region_missing']:,} 件"
        f"（{result['region_missing_rate'] * 100:.2f}%）"
    )
    print(f"channel の欠損 : {result['channel_missing']:,} 件")
    print()

    print("■ 2. 2 つの構成")
    for key in ("small", "large"):
        row = result[key]
        print(f"[{row['label']}] カテゴリ列 {row['categorical']}")
        print(f"  入力 {row['n_input']} 列 -> 変換後 {row['n_columns']} 列")
        print(f"  ホールドアウト 1 回 : {row['holdout']:.4f}")
        print(f"  fold ごと           : {fmt_scores(row['scores'])}")
        print(f"  平均 / 標準偏差     : {row['mean']:.4f} / {row['std']:.4f}")
    print()

    print("■ 3. 差")
    print(f"ホールドアウトの差       : {result['holdout_gap']:+.4f}")
    print(f"交差検証の平均の差       : {result['mean_gap']:+.4f}")
    print(f"差が標準偏差より小さいか : {result['gap_within_std']}")
    print()

    print(f"図を保存しました: {make_figure(result)}")


if __name__ == "__main__":
    main()
