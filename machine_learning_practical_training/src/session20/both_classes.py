"""両方のクラスを見る ― accuracy 0.8422 の裏側で何が起きているかを数える。

使い方:
    docker compose exec lab python src/session20/both_classes.py
"""

from __future__ import annotations

from common import (
    DEFAULT_THRESHOLD,
    NEGATIVE_LABEL,
    average_scores,
    baseline_scores,
    class_metrics,
    confusion_parts,
    fit_high_rating,
    load_review_table,
    per_class_table,
    predict_at,
    print_per_class_table,
)


def main() -> None:
    df = load_review_table()
    y_test, proba = fit_high_rating(df)
    y_pred = predict_at(proba, DEFAULT_THRESHOLD)

    table = per_class_table(y_test, y_pred)
    print("■ クラスごとの指標（閾値 0.5）")
    print_per_class_table(table)
    print()

    scores = average_scores(y_test, y_pred)
    print("■ 平均の取り方で値が変わる")
    print(f"macro F1（クラスを平等に平均）    : {scores['macro_f1']:.4f}")
    print(f"weighted F1（件数で重みづけ）     : {scores['weighted_f1']:.4f}")
    print(f"micro F1（全件をまとめて数える）  : {scores['micro_f1']:.4f}")
    print(f"accuracy                          : {scores['accuracy']:.4f}")
    print()

    base = baseline_scores(y_test)
    print("■ ベースライン（全部「高評価」と答えるだけ）との比較")
    print(f"ベースラインの accuracy : {base['accuracy']:.4f}")
    print(f"モデルの accuracy       : {scores['accuracy']:.4f}")
    print(f"改善幅                  : {scores['accuracy'] - base['accuracy']:+.4f}")
    print()

    parts = confusion_parts(y_test, y_pred)
    low = class_metrics(y_test, y_pred, NEGATIVE_LABEL)
    print("■ 低評価レビューを何件見つけられたか（不満の芽を拾う用途で使うなら、ここが本番）")
    print(f"実際に低評価だったレビュー: {low['support']:,} 件")
    print(f"そのうち見つけられた件数  : {parts['tn']:,} 件（再現率 {low['recall']:.4f}）")
    print(f"高評価だと判定して見送った: {parts['fp']:,} 件")
    print(f"低評価と判定したときの的中率（適合率）: {low['precision']:.4f}")


if __name__ == "__main__":
    main()
