"""問題2 の解答：両クラスの指標と 3 通りの平均を自作し、classification_report と突き合わせる。

使い方:
    docker compose exec lab python src/session20/q2_per_class_report.py
"""

from __future__ import annotations

from sklearn.metrics import classification_report

from common import (
    DEFAULT_THRESHOLD,
    NEGATIVE_LABEL,
    POSITIVE_LABEL,
    average_scores,
    baseline_scores,
    fit_high_rating,
    load_review_table,
    per_class_table,
    predict_at,
    print_per_class_table,
)


def hand_macro(table) -> float:
    """クラスごとの F1 を単純平均する（件数を無視するので少数クラスも 1 票）。"""
    return float(table["f1"].mean())


def hand_weighted(table) -> float:
    """クラスごとの F1 を件数で重みづけて平均する。"""
    return float((table["f1"] * table["support"]).sum() / table["support"].sum())


def report(df) -> dict[str, float]:
    """問題2 で報告する値をまとめて返す（verify から呼び出せるようにしておく）。"""
    y_test, proba = fit_high_rating(df)
    y_pred = predict_at(proba, DEFAULT_THRESHOLD)
    table = per_class_table(y_test, y_pred)
    scores = average_scores(y_test, y_pred)
    low = table[table["label"] == NEGATIVE_LABEL].iloc[0]
    high = table[table["label"] == POSITIVE_LABEL].iloc[0]
    return {
        "low_precision": float(low["precision"]),
        "low_recall": float(low["recall"]),
        "low_f1": float(low["f1"]),
        "low_support": int(low["support"]),
        "high_precision": float(high["precision"]),
        "high_recall": float(high["recall"]),
        "high_f1": float(high["f1"]),
        "high_support": int(high["support"]),
        "hand_macro_f1": hand_macro(table),
        "hand_weighted_f1": hand_weighted(table),
        "macro_f1": scores["macro_f1"],
        "weighted_f1": scores["weighted_f1"],
        "micro_f1": scores["micro_f1"],
        "accuracy": scores["accuracy"],
        "baseline_accuracy": baseline_scores(y_test)["accuracy"],
    }


def main() -> None:
    df = load_review_table()
    y_test, proba = fit_high_rating(df)
    y_pred = predict_at(proba, DEFAULT_THRESHOLD)
    table = per_class_table(y_test, y_pred)

    print("■ クラスごとの指標（閾値 0.5）")
    print_per_class_table(table)
    print()

    values = report(df)
    print("■ 平均の取り方を自分で計算する")
    print(f"macro F1（手計算）   : {values['hand_macro_f1']:.4f} / sklearn {values['macro_f1']:.4f}")
    print(f"weighted F1（手計算）: {values['hand_weighted_f1']:.4f} / sklearn {values['weighted_f1']:.4f}")
    print(f"micro F1             : {values['micro_f1']:.4f}（accuracy {values['accuracy']:.4f} と一致）")
    print(f"macro と weighted の差: {values['weighted_f1'] - values['hand_macro_f1']:+.4f}")
    print()

    print("■ sklearn の classification_report と突き合わせる")
    # クラス名は半角で付ける（日本語名だと列幅がずれて読みにくくなるため）
    print(
        classification_report(
            y_test,
            y_pred,
            labels=[NEGATIVE_LABEL, POSITIVE_LABEL],
            target_names=["low(0)", "high(1)"],
            digits=4,
            zero_division=0,
        )
    )

    print("■ この 1 行が言いたいこと")
    print(
        f"低評価 {values['low_support']:,} 件のうち見つけられたのは再現率 {values['low_recall']:.4f} 分だけ。"
        f"accuracy は {values['accuracy']:.4f}（ベースライン {values['baseline_accuracy']:.4f}）。"
    )


if __name__ == "__main__":
    main()
