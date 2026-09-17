"""特徴量を 1 段階ずつ足していき、そのたびに同じ条件で評価する（増分実験）。

使い方:
    docker compose exec lab python src/session14/add_features_step.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # 画面を持たないコンテナ内で図を PNG として保存するための設定
import matplotlib.pyplot as plt

from common import OUT_DIR, add_all_features, load_order_table, print_steps, run_steps


def save_figure(results: list[dict]) -> None:
    """段階ごとの ROC AUC と PR-AUC を棒グラフにして保存する。"""
    labels = ["①", "②", "③", "④", "⑤", "⑥", "⑦"]
    colors = ["#4c78a8"] * 6 + ["#c44e52"]  # ⑦（リーク）だけ色を変える
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
    for ax, key, title, top in [
        (axes[0], "roc_auc", "ROC AUC", 1.0),
        (axes[1], "pr_auc", "PR-AUC", 0.40),
    ]:
        ax.bar(labels, [r[key] for r in results], color=colors)
        ax.set_title(f"特徴量を足したときの {title}")
        ax.set_xlabel("段階（⑦はリーク）")
        ax.set_ylabel(title)
        ax.set_ylim(0, top)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "s14_feature_steps.png", dpi=110)
    plt.close(fig)
    print("\n図を保存しました: outputs/s14_feature_steps.png")


def main() -> None:
    df = add_all_features(load_order_table())
    results = run_steps(df)

    print("■ 段階ごとの結果（分割条件は全段階で同じ）")
    print_steps(results[:6])

    base = results[1]  # ② が基準モデル
    print("\n■ 基準モデル（②）と比べて改善したか")
    for r in results[2:6]:
        print(f"{r['label']} : ROC AUC {'改善' if r['roc_auc'] > base['roc_auc'] else '改善せず'}"
              f" / PR-AUC {'改善' if r['pr_auc'] > base['pr_auc'] else '改善せず'}")

    leak = results[6]
    print("\n■ 参考（リークした特徴量を入れた場合）")
    print(f"{leak['label']} : {leak['n_features']} 列 / ROC AUC {leak['roc_auc']:.4f} / PR-AUC {leak['pr_auc']:.4f}")
    print("→ この跳ね上がりは実力ではありません。次のスクリプトで正体を確かめます")

    save_figure(results)


if __name__ == "__main__":
    main()
