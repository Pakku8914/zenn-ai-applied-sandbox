"""実装問題 7：ベースラインと並べて報告する（セッション15・17・20 の準備）。

使い方:
    docker compose exec lab python src/review02/q7_baseline_gap.py
"""

from __future__ import annotations

from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression

from common import (
    MAX_ITER,
    RANDOM_STATE,
    fit_and_score,
    fit_pipeline,
    load_review_table,
    positive_proba,
    split_classification,
    threshold_table,
)


def step1_population(df, y_train, y_test) -> None:
    """母集団と正例率を最初に宣言する（セッション15）。"""
    print("■ 1. 母集団と正例率（この章のすべての問題で同じ分割を使う）")
    print(f"  学習に使うレビュー: {len(df):,} 件")
    print(f"  訓練 {len(y_train):,} 件 / 評価 {len(y_test):,} 件")
    print(f"  正例率（訓練）: {y_train.mean():.4f}")
    print(f"  正例率（評価）: {y_test.mean():.4f}")


def step2_compare(X_train, X_test, y_train, y_test) -> dict[str, dict[str, float]]:
    """ベースラインと本命のモデルを同じ分割・同じ前処理で比べる（セッション15・17）。"""
    base = fit_and_score(
        DummyClassifier(strategy="most_frequent", random_state=RANDOM_STATE),
        X_train, y_train, X_test, y_test,
    )
    model = fit_and_score(
        LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE),
        X_train, y_train, X_test, y_test,
    )
    gain = model["accuracy"] - base["accuracy"]

    print("■ 2. ベースラインと並べる")
    print(f"  ベースライン（多数クラス予測）: accuracy {base['accuracy']:.4f} / ROC AUC {base['roc_auc']:.4f}")
    print(f"  ロジスティック回帰: accuracy {model['accuracy']:.4f} / ROC AUC {model['roc_auc']:.4f}")
    print(f"  accuracy の差: {gain:+.4f}（{gain * 100:.1f} ポイント）")
    print(f"  ROC AUC は {base['roc_auc']:.4f} → {model['roc_auc']:.4f}")
    print(f"  ロジスティック回帰の対数損失: {model['log_loss']:.4f}")
    print(f"  検算 ベースラインの accuracy = 評価データの正例率: {abs(base['accuracy'] - float(y_test.mean())) < 1e-9}")
    print(f"  検算 accuracy の改善が 3 ポイント未満: {gain < 0.03}")
    print(f"  検算 ベースラインの対数損失のほうが大きい: {base['log_loss'] > model['log_loss']}")
    return {"base": base, "model": model}


def step3_thresholds(X_train, X_test, y_train, y_test, model_accuracy: float) -> None:
    """accuracy 1 つでは見えないものを、閾値を動かして見る（セッション17）。"""
    pipeline = fit_pipeline(
        LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE), X_train, y_train
    )
    proba = positive_proba(pipeline, X_test)
    table = threshold_table(y_test, proba)

    print("■ 3. 閾値を動かす（0.5 は既定値であって正解ではない）")
    for row in table.itertuples(index=False):
        print(
            f"  閾値 {row.threshold:.1f}: 適合率 {row.precision:.4f} / 再現率 {row.recall:.4f}"
            f" / F1 {row.f1:.4f} / accuracy {row.accuracy:.4f}"
        )
    at_half = float(table.loc[table["threshold"] == 0.5, "accuracy"].iloc[0])
    best_f1 = table.loc[table["f1"].idxmax(), "threshold"]
    print(f"  検算 閾値 0.5 の accuracy がモデルの accuracy と一致: {abs(at_half - model_accuracy) < 1e-9}")
    print(f"  F1 が最大になる閾値: {best_f1:.1f}")


def step4_report(scores: dict[str, dict[str, float]], y_test) -> None:
    """ベースラインを併記した報告文を、数値を埋め込んで組み立てる（セッション15）。"""
    base, model = scores["base"], scores["model"]
    gain = model["accuracy"] - base["accuracy"]
    print("■ 4. 報告文（ベースラインを併記した形）")
    for line in [
        f"評価データ {len(y_test):,} 件（正例率 {y_test.mean():.4f}）で比べました。",
        f"何も学習しないベースライン（多数クラス予測）は accuracy {base['accuracy']:.4f}・ROC AUC {base['roc_auc']:.4f} です。",
        f"ロジスティック回帰は accuracy {model['accuracy']:.4f} で、ベースラインとの差は {gain * 100:.1f} ポイントでした。",
        f"一方 ROC AUC は {base['roc_auc']:.4f} から {model['roc_auc']:.4f} に上がっています。",
        "このモデルの成果は「当たる件数が増えたこと」ではなく、",
        "「高評価になりやすいレビューを上位に並べられるようになったこと」です。",
        "accuracy だけを報告すると、この成果は見えません。",
    ]:
        print(f"  {line}")


def main() -> None:
    df = load_review_table()
    X_train, X_test, y_train, y_test = split_classification(df)
    step1_population(df, y_train, y_test)
    scores = step2_compare(X_train, X_test, y_train, y_test)
    step3_thresholds(X_train, X_test, y_train, y_test, scores["model"]["accuracy"])
    step4_report(scores, y_test)


if __name__ == "__main__":
    main()
