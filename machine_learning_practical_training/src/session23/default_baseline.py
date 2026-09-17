"""既定値のまま交差検証すると何点になるかを測る（本文 1 節）。

探索の「出発点」を先に決めておくためのスクリプトです。ここより良くならない
探索は、時間を捨てているだけということになります。

実行:
    docker compose exec lab python src/session23/default_baseline.py
"""

from __future__ import annotations

from common import build_model, cv_auc, fmt_scores, load_review_table, split_train_test, summarize

# LightGBM の既定値（セッション19 で役割を確認した 3 つ）
DEFAULT_PARAMS = {"n_estimators": 100, "learning_rate": 0.1, "num_leaves": 31}


def baseline(df) -> dict[str, object]:
    """既定値のモデルを訓練データだけで交差検証する（テストデータには触らない）。"""
    X_train, X_test, y_train, _ = split_train_test(df)
    scores = cv_auc(build_model(), X_train, y_train)
    mean, std = summarize(scores)
    return {
        "n_train": len(X_train),
        "n_test": len(X_test),
        "scores": scores,
        "mean": mean,
        "std": std,
        "n_fits": len(scores),  # 5 fold ぶん = 5 回の学習
    }


def main() -> None:
    df = load_review_table()
    result = baseline(df)

    print("■ 探索なし（LightGBM の既定値）の交差検証")
    print(f"訓練データ {result['n_train']} 件 / テストデータ {result['n_test']} 件（テストは最後まで触らない）")
    print(f"既定値: {DEFAULT_PARAMS}")
    print(f"fold ごとの ROC AUC : {fmt_scores(result['scores'])}")
    print(f"平均                : {result['mean']:.4f}")
    print(f"標準偏差            : {result['std']:.4f}")
    print(f"学習した回数        : {result['n_fits']} 回")
    print()
    print("この 0.8020 が探索の出発点です。ここを超えられない探索は時間の無駄です。")


if __name__ == "__main__":
    main()
