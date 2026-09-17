"""問題6 の解答：多クラス分類で平均の取り方を選び、層化分割できない理由も確かめる。

使い方:
    docker compose exec lab python src/session20/q6_multiclass_average.py
"""

from __future__ import annotations

import numpy as np

from common import (
    average_scores,
    fit_star_model,
    load_review_table,
    multiclass_confusion,
    print_multiclass_confusion,
    star_counts,
    stratify_error_message,
)


def report(df) -> dict[str, object]:
    """問題6 で報告する値をまとめて返す。"""
    y_test, y_pred, model = fit_star_model(df)
    labels, matrix = multiclass_confusion(y_test, y_pred)
    scores = average_scores(y_test, y_pred)
    return {
        "counts": {int(star): int(count) for star, count in star_counts(df).items()},
        "error_message": stratify_error_message(df),
        "known_classes": [int(v) for v in model.classes_],
        "true_classes": [int(v) for v in np.unique(y_test)],
        "predicted_classes": [int(v) for v in np.unique(y_pred)],
        "labels": labels,
        "matrix": matrix,
        "accuracy": scores["accuracy"],
        "macro_f1": scores["macro_f1"],
        "micro_f1": scores["micro_f1"],
        "weighted_f1": scores["weighted_f1"],
    }


def main() -> None:
    df = load_review_table()
    values = report(df)

    print("■ 星の件数")
    for star, count in values["counts"].items():
        print(f"星{star}: {count:>6,} 件")
    print(f"いちばん少ないクラスの件数: {min(values['counts'].values())} 件")
    print()

    print("■ 層化分割（stratify=y）を試すと")
    print(f"ValueError: {values['error_message']}")
    print(f"「least populated」という語が入っているか: {'least populated' in values['error_message']}")
    print()

    print("■ 3 通りの平均")
    print(f"accuracy    : {values['accuracy']:.4f}")
    print(f"macro F1    : {values['macro_f1']:.4f}")
    print(f"micro F1    : {values['micro_f1']:.4f}")
    print(f"weighted F1 : {values['weighted_f1']:.4f}")
    print(f"micro F1 は accuracy と一致するか: {abs(values['micro_f1'] - values['accuracy']) < 1e-9}")
    print(f"macro と weighted の差: {values['weighted_f1'] - values['macro_f1']:+.4f}")
    print()

    print("■ どのクラスが予測に現れたか")
    print(f"モデルが知っているクラス   : {values['known_classes']}")
    print(f"評価データにあったクラス   : {values['true_classes']}")
    print(f"予測に現れたクラス         : {values['predicted_classes']}")
    print(f"星1 は一度も予測されないか: {1 not in values['predicted_classes']}")
    print()

    print("■ 混同行列")
    print_multiclass_confusion(values["labels"], values["matrix"])
    print()

    print("■ どの平均を報告するか")
    print("星ごとに同じ重さで見たいなら macro（少数クラスの弱さが数字に出る）。")
    print("全体の当たり方を伝えたいなら weighted または accuracy（多数クラスの星4 に引っぱられる）。")
    print("どれか 1 つだけを書くのではなく、クラスごとの内訳と一緒に出す。")


if __name__ == "__main__":
    main()
