"""課題3: Pipeline に載せた 2 本のモデルを、同じ評価データで比べる。

比べるのは「ロジスティック回帰」と「LightGBM」の 2 本だけです。
探索はしません（セッション23 で、探しても大きくは変わらないことを確かめました）。

使い方:
    docker compose exec lab python src/final01/models.py
"""

from __future__ import annotations

from common import MODELS, baseline, dataset, fitted


def compare() -> dict:
    """2 本のモデルとベースラインを 1 つの表にまとめる。"""
    base = baseline()
    rows = []
    for kind in MODELS:
        bundle = fitted(kind)  # 前処理・分割・評価データは共通。変えるのはモデル本体だけ
        rows.append(
            {
                **bundle,
                "roc_gain": bundle["roc_auc"] - base["roc_auc"],
                "pr_gain": bundle["pr_auc"] - base["pr_auc"],
                "accuracy_gain": bundle["accuracy"] - base["accuracy"],
                "steps": [name for name, _ in bundle["model"].steps],
                "n_output_columns": int(
                    bundle["model"].named_steps["pre"].transform(dataset()["X_test"]).shape[1]
                ),
            }
        )
    best = max(rows, key=lambda row: row["roc_auc"])
    worst = min(rows, key=lambda row: row["roc_auc"])
    return {
        "base": base,
        "rows": rows,
        "best": best,
        "worst": worst,
        "gap": best["roc_auc"] - worst["roc_auc"],
        "simple_wins": best["kind"] == "logistic",
    }


def main() -> None:
    result = compare()
    base = result["base"]

    print("■ 1. Pipeline の形")
    for row in result["rows"]:
        print(f"{row['label']}: ステップ {row['steps']} / 前処理後の列数 {row['n_output_columns']}")
    print("（欠損補完 → 標準化 / One-Hot → モデル、までが 1 本に入っている）")
    print()

    print("■ 2. ベースラインと並べた指標")
    print(f"ベースライン: ROC AUC {base['roc_auc']:.4f} / PR-AUC {base['pr_auc']:.4f} / accuracy {base['accuracy']:.4f}")
    for row in result["rows"]:
        print(f"{row['label']}: ROC AUC {row['roc_auc']:.4f} / PR-AUC {row['pr_auc']:.4f} / accuracy {row['accuracy']:.4f}")
    print()

    print("■ 3. ベースラインからの改善幅")
    for row in result["rows"]:
        print(f"{row['label']}")
        print(f"    ROC AUC : +{row['roc_gain']:.4f}")
        print(f"    PR-AUC  : +{row['pr_gain']:.4f}")
        print(f"    accuracy: +{row['accuracy_gain']:.4f}（+{row['accuracy_gain'] * 100:.2f} ポイント）")
    print()

    print("■ 4. どちらが勝ったか")
    print(f"勝ち: {result['best']['label']}（ROC AUC {result['best']['roc_auc']:.4f}）")
    print(f"負け: {result['worst']['label']}（ROC AUC {result['worst']['roc_auc']:.4f}）")
    print(f"差  : {result['gap']:.4f}")
    print(f"線形モデルが勝ったか: {result['simple_wins']}")
    print()
    print("判断: 複雑なモデルが常に優れているわけではありません。")
    print("      本書では高評価レビューの分類（0.8265 > 0.7966 > 0.7705）でも同じ結果でした。")
    print("      ここで差が偶然でないかは、次の交差検証で確かめます。")


if __name__ == "__main__":
    main()
