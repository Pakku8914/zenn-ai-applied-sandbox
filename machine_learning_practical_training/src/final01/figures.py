"""課題10: 報告に使う図 4 枚を作る。

図は「結論を先に決めてから」作ります。作ってから結論を考えると、
説明に使わない図が増えて、読む人の時間を奪います。

使い方:
    docker compose exec lab python src/final01/figures.py
"""

from __future__ import annotations

import matplotlib.pyplot as plt

from common import (
    CAPACITY,
    MODELS,
    baseline,
    capacity_plan,
    fitted,
    leak_audit,
    pr_curve,
    save_figure,
    shap_local,
    sweep,
)

FIGURES = (
    "final01_pr_curve.png",
    "final01_threshold_budget.png",
    "final01_shap_local.png",
    "final01_leak_check.png",
)
TOP_N = 8  # SHAP の図に並べる列の数


def figure_pr_curve() -> str:
    """図1: PR 曲線とベースライン。PR-AUC の基準が正例率であることを見せる。"""
    base = baseline()
    fig, ax = plt.subplots(figsize=(7, 5))
    for kind in MODELS:
        precision, recall = pr_curve(kind)
        bundle = fitted(kind)
        ax.plot(recall, precision, label=f"{bundle['label']}（PR-AUC {bundle['pr_auc']:.4f}）")
    ax.axhline(
        base["pr_auc"],
        color="gray",
        linestyle="--",
        label=f"ベースライン（正例率 {base['pr_auc']:.4f}）",
    )
    ax.set_xlabel("再現率（実際に再購入した人のうち、捕まえられた割合）")
    ax.set_ylabel("適合率（送った人のうち、実際に再購入した割合）")
    ax.set_title("再購入予測の PR 曲線 ― ベースラインは正例率")
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.05)
    ax.legend(loc="lower left")
    ax.grid(alpha=0.3)
    return save_figure(fig, FIGURES[0])


def figure_threshold_budget() -> str:
    """図2: 閾値と「送る通数」「適合率・再現率」。予算の線を引くのが要点。"""
    table = sweep("lgbm")
    plan = capacity_plan()
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))

    axes[0].plot(table["threshold"], table["n_sent"], marker="o", label="送る通数")
    axes[0].axhline(CAPACITY, color="crimson", linestyle="--", label=f"送れる上限 {CAPACITY:,} 通")
    axes[0].axvline(plan["threshold"], color="seagreen", linestyle=":", label=f"選んだ閾値 {plan['threshold']:.1f}")
    axes[0].set_xlabel("閾値")
    axes[0].set_ylabel("クーポンを送る人数（人）")
    axes[0].set_title("閾値と送る通数 ― 予算の線より下だけが候補")
    axes[0].legend()
    axes[0].grid(alpha=0.3)

    axes[1].plot(table["threshold"], table["precision"], marker="o", label="適合率")
    axes[1].plot(table["threshold"], table["recall"], marker="s", label="再現率")
    axes[1].axvline(plan["threshold"], color="seagreen", linestyle=":", label=f"選んだ閾値 {plan['threshold']:.1f}")
    axes[1].set_xlabel("閾値")
    axes[1].set_ylabel("割合")
    axes[1].set_ylim(0.0, 1.0)
    axes[1].set_title("閾値と適合率・再現率 ― 逆に動く")
    axes[1].legend()
    axes[1].grid(alpha=0.3)
    return save_figure(fig, FIGURES[1])


def figure_shap_local() -> str:
    """図3: 1 人分の予測の分解。押し上げと押し下げを色で分ける。"""
    local = shap_local().head(TOP_N).iloc[::-1]
    colors = ["tab:blue" if value > 0 else "tab:orange" for value in local["shap"]]
    labels = [f"{name}\n（値 {value}）" for name, value in zip(local["feature"], local["value"])]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(labels, local["shap"], color=colors)
    ax.axvline(0.0, color="black", linewidth=0.8)
    ax.set_xlabel("SHAP 値（対数オッズへの寄与。正なら確率を押し上げる）")
    ax.set_title(f"1 人分の予測の分解 ― 寄与の大きい上位 {TOP_N} 列")
    ax.grid(alpha=0.3, axis="x")
    return save_figure(fig, FIGURES[2])


def figure_leak_check() -> str:
    """図4: リークありとリークなしの比較。1.0000 が「良い結果」ではないことを見せる。"""
    audit = leak_audit()
    base = baseline()
    labels = ["ベースライン", "ロジスティック回帰", "LightGBM", "リーク版（失格）"]
    values = [
        base["roc_auc"],
        fitted("logistic")["roc_auc"],
        audit["clean_roc_auc"],
        audit["leaked_roc_auc"],
    ]
    colors = ["gray", "tab:blue", "tab:green", "crimson"]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    bars = ax.bar(labels, values, color=colors)
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.01, f"{value:.4f}", ha="center")
    ax.set_ylabel("ROC AUC")
    ax.set_ylim(0.0, 1.15)
    ax.set_title("ROC AUC の比較 ― 1.0000 は成果ではなくリークの合図")
    ax.grid(alpha=0.3, axis="y")
    return save_figure(fig, FIGURES[3])


def main() -> None:
    names = [
        figure_pr_curve(),
        figure_threshold_budget(),
        figure_shap_local(),
        figure_leak_check(),
    ]
    for name in names:
        print(f"保存しました: outputs/{name}")
    print()
    print("読み取れること")
    print("[図1] PR 曲線は右下がり。ベースラインの水平線より上にある幅が、モデルの取り分です。")
    print("[図2] 左は閾値を下げると通数が跳ね上がること、右は適合率と再現率が逆に動くこと。")
    print("[図3] 1 人分の確率が、どの列にどれだけ押し上げ・押し下げられたか。")
    print("[図4] リーク版だけが 1.0000 に張り付きます。棒が高いほど良い、ではありません。")
    print()
    print(f"（図は {len(names)} 枚。ホスト側の outputs/ フォルダからそのまま開けます）")


if __name__ == "__main__":
    main()
