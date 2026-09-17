"""問題8 の解答: 誤った報告文を、PR-AUC・混同行列・Brier スコアを使って書き直す。

実行:
    docker compose exec lab python src/review03/q8_metric_report.py
"""

from __future__ import annotations

from common import (
    CANCEL_KINDS,
    CANCEL_THRESHOLDS,
    CONSTANT_GUESS,
    COST_GRID,
    KIND_NAMES,
    LGBM,
    LINEAR,
    MEAN,
    METRIC_KEYS,
    MODEL_ORDER,
    NEGATIVE_LABEL,
    POSITIVE_LABEL,
    STARS,
    average_scores,
    best_by,
    cancel_bundle,
    confusion_parts,
    constant_prediction,
    high_bundle,
    majority_baseline,
    outlier_effect,
    per_class_table,
    predict_at,
    regression_scores,
    residual_by_actual,
    save_fig,
    score_summary,
    star_regression,
    threshold_metrics,
    threshold_table,
)

FIGURE_NAME = "review03_metric_report.png"

WRONG_CLAIMS = [
    "キャンセル予測は accuracy 0.9640 なので、十分な性能です。",
    "星の予測は MAE がいちばん小さいモデルを採用しました。",
    "キャンセル予測は ROC AUC 0.79 なので、このまま実用できます。",
]


def cancel_report() -> dict:
    """不均衡データの報告カード（accuracy を「載せない指標」として扱う）。"""
    plain = cancel_bundle("plain")
    y_test = plain["y_test"]
    return {
        "base": majority_baseline(y_test, NEGATIVE_LABEL),
        "plain": score_summary(y_test, plain["proba"]),
        "kinds": {
            kind: score_summary(y_test, cancel_bundle(kind)["proba"]) for kind in CANCEL_KINDS
        },
        "n_fit": {kind: cancel_bundle(kind)["n_fit"] for kind in CANCEL_KINDS},
        "parts": confusion_parts(y_test, predict_at(plain["proba"])),
        "table": threshold_table(y_test, plain["proba"], CANCEL_THRESHOLDS),
        "y_test": y_test,
        "proba": plain["proba"],
        "n_train": plain["n_train"],
    }


def print_cancel(report: dict) -> None:
    base, plain, parts = report["base"], report["plain"], report["parts"]
    print("■ 1. キャンセル予測の報告カード（accuracy を主役にしない）")
    print(f"正例率（評価データ）      : {base['positive_rate']:.4f}（{base['n_positive']:,} / {base['n_rows']:,} 件）")
    print(f"PR-AUC                    : {plain['pr_auc']:.4f}")
    print(f"ROC AUC                   : {plain['roc_auc']:.4f}（参考。不均衡では楽観的に見える）")
    print(f"Brier スコア              : {plain['brier']:.5f}")
    print(f"予測確率の平均            : {plain['mean_proba']:.4f}（実際の正例率 {base['positive_rate']:.4f}）")
    print(f"accuracy（モデル）        : {plain['accuracy']:.4f}")
    print(f"accuracy（全部「しない」）: {base['accuracy']:.4f} ← 同じ値。だから accuracy では語れない")
    print(f"ROC AUC（全部「しない」） : {base['roc_auc']:.4f}")
    print()

    print("■ 2. 閾値 0.5 の混同行列（1 件も直さずに、まず件数を見る）")
    print("                予測: しない   予測: する")
    print(f"実測: しない   TN {parts['tn']:>8,}   FP {parts['fp']:>6,}")
    print(f"実測: する     FN {parts['fn']:>8,}   TP {parts['tp']:>6,}")
    print(f"→ 実際のキャンセル {parts['fn'] + parts['tp']:,} 件のうち、拾えたのは {parts['tp']:,} 件だけ")
    print()

    print("■ 3. 閾値を下げると何が変わるか")
    print("閾値 | 適合率 | 再現率 |   F1   | 陽性と予測 | 捕まえた | 見逃した")
    for row in report["table"].itertuples(index=False):
        print(
            f"{row.threshold:.1f}  | {row.precision:.4f} | {row.recall:.4f} | {row.f1:.4f} |"
            f" {row.n_positive:>6,} 件 | {row.tp:>5,} 件 | {row.fn:>5,} 件"
        )
    print()

    print("■ 4. クラス比をいじる 2 つの手の代償（順位はほぼ変わらず、確率が壊れる）")
    print("学習のしかた             | 学習件数 | ROC AUC | PR-AUC | 確率の平均 | Brier")
    for kind in CANCEL_KINDS:
        row = report["kinds"][kind]
        print(
            f"{KIND_NAMES[kind]:<24} | {report['n_fit'][kind]:>7,} | {row['roc_auc']:.4f}  |"
            f" {row['pr_auc']:.4f} |   {row['mean_proba']:.4f}   | {row['brier']:.5f}"
        )
    print("→ 順位付けの力（ROC AUC・PR-AUC）はほとんど変わらず、確率の当たり具合（Brier）だけ悪化します")
    print()


def regression_report() -> dict:
    """星の回帰。4 指標を並べ、指標ごとの 1 位が入れ替わることを確かめる。"""
    bundle = star_regression()
    y_test, preds, scores = bundle["y_test"], bundle["preds"], bundle["scores"]
    return {
        "scores": scores,
        "winners": {metric: best_by(scores, metric) for metric in METRIC_KEYS},
        "guess": regression_scores(y_test, constant_prediction(y_test, CONSTANT_GUESS)),
        "residual": residual_by_actual(y_test, preds[LGBM]),
        "outlier": outlier_effect(y_test, preds[LGBM]),
        "train_mean": bundle["train_mean"],
    }


def print_regression(report: dict) -> None:
    scores = report["scores"]
    print("■ 5. 星の回帰（同じ分割・同じ前処理で 3 モデル × 4 指標）")
    print("モデル     |  MAE   |  RMSE  |  MAPE  |   R2")
    for name in MODEL_ORDER:
        row = scores[name]
        print(f"{name:<10} | {row['mae']:.4f} | {row['rmse']:.4f} | {row['mape']:.4f} | {row['r2']:+.4f}")
    for metric in METRIC_KEYS:
        print(f"{metric.upper():<4} の 1 位: {report['winners'][metric]}")
    print(f"→ 平均予測（訓練データの星の平均 {report['train_mean']:.2f} を返すだけ）が MAE と MAPE で 1 位になります")
    print(f"   その平均予測の R2 は {scores[MEAN]['r2']:+.4f}（＝何も説明していない）")
    print(f"   全部 {CONSTANT_GUESS:.1f} と答えるモデルの R2 は {report['guess']['r2']:+.4f}（平均より当たらないので負）")
    print()

    print("■ 6. 残差（実測 − 予測）の偏りと、外れ値 1 件の影響")
    for star in STARS:
        row = report["residual"].loc[star]
        print(f"実測 星 {star:.0f}: 残差の平均 {row['residual_mean']:+.4f} / 予測の平均 {row['pred_mean']:.4f}")
    before, after = report["outlier"]["before"], report["outlier"]["after"]
    print(f"1 件を星 10 に差し替え: MAE {before['mae']:.4f} → {after['mae']:.4f} / RMSE {before['rmse']:.4f} → {after['rmse']:.4f}")
    print("→ 星 3 は高めに、星 5 は低めに外しています（平均へ引き寄せられている）")
    print()


def class_report() -> dict:
    """高評価分類をクラスごとに見る（多数クラスの陰に隠れた性能を出す）。"""
    bundle = high_bundle()
    y_pred = predict_at(bundle["proba"])
    return {
        "bundle": bundle,
        "table": per_class_table(bundle["y_test"], y_pred),
        "averages": average_scores(bundle["y_test"], y_pred),
        "base": majority_baseline(bundle["y_test"], POSITIVE_LABEL),
    }


def print_class(report: dict) -> None:
    print("■ 7. 高評価分類をクラスごとに見る（accuracy 0.8422 の内側）")
    print("クラス          | 適合率 | 再現率 |   F1   | 件数")
    for row in report["table"].itertuples(index=False):
        print(f"{row.name}  | {row.precision:.4f} | {row.recall:.4f} | {row.f1:.4f} | {row.support:>5,}")
    averages = report["averages"]
    print(f"accuracy {averages['accuracy']:.4f} / macro F1 {averages['macro_f1']:.4f} / weighted F1 {averages['weighted_f1']:.4f}")
    print(f"ベースライン（全部「高評価」）の accuracy {report['base']['accuracy']:.4f} / ROC AUC {report['base']['roc_auc']:.4f}")
    print("→ 陰性クラスの F1 は 0.4 を下回ります。macro を併記すると、この弱さが数値に出ます")
    print()


def rewrite(cancel: dict, regression: dict) -> list[str]:
    """3 つの誤った報告文を、根拠の数値を埋め込んだ形に書き直す。"""
    base, plain, parts = cancel["base"], cancel["plain"], cancel["parts"]
    low = threshold_metrics(cancel["y_test"], cancel["proba"], 0.1)
    scores = regression["scores"]
    return [
        (
            f"キャンセル率は {base['positive_rate']:.4f}（{base['n_positive']:,} / {base['n_rows']:,} 件）で、"
            f"「全件キャンセルされない」と答えるだけで accuracy は {base['accuracy']:.4f} になります。"
            f"モデルの accuracy {plain['accuracy']:.4f} は同じ水準で、性能の根拠になりません。"
            f"報告すべきは PR-AUC {plain['pr_auc']:.4f} と、閾値 0.5 の混同行列"
            f"（実際のキャンセル {parts['fn'] + parts['tp']:,} 件のうち捕まえたのは {parts['tp']:,} 件）です。"
        ),
        (
            f"MAE で 1 位になったのは {regression['winners']['mae']}（{scores[MEAN]['mae']:.4f}）ですが、"
            f"これは訓練データの星の平均を返すだけのモデルで、R2 は {scores[MEAN]['r2']:+.4f} です。"
            f"MAE だけを見ると「何も学習していないモデル」を採用してしまいます。"
            f"外れ方の大きさを重く見るなら RMSE（{LINEAR} {scores[LINEAR]['rmse']:.4f} < {LGBM} {scores[LGBM]['rmse']:.4f}"
            f" < {MEAN} {scores[MEAN]['rmse']:.4f}）と R2 を併記し、どの指標で選んだかを明記します。"
        ),
        (
            f"ROC AUC {plain['roc_auc']:.4f} は順位付けの力だけを表す値で、運用の可否は決められません。"
            f"同じモデルの PR-AUC は {plain['pr_auc']:.4f}、確率の当たり具合は Brier スコア {plain['brier']:.5f} です。"
            f"閾値 0.5 では {parts['fp'] + parts['tp']:,} 件しか陽性と予測せず、再現率は {plain['recall']:.4f} にとどまります。"
            f"閾値を 0.1 まで下げると再現率 {low['recall']:.4f}（適合率 {low['precision']:.4f}・陽性 {low['n_positive']:,} 件）となり、"
            f"「何件の空振りを許せるか」を決めてから実用の可否を判断します。"
        ),
    ]


def make_figure(cancel: dict, regression: dict) -> str:
    """左: キャンセル予測の閾値と適合率・再現率 / 右: 回帰 3 モデルの MAE と RMSE。"""
    import matplotlib.pyplot as plt
    import numpy as np

    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.2))

    rows = [threshold_metrics(cancel["y_test"], cancel["proba"], t) for t in COST_GRID]
    axes[0].plot([row["threshold"] for row in rows], [row["precision"] for row in rows], marker="o", label="適合率")
    axes[0].plot([row["threshold"] for row in rows], [row["recall"] for row in rows], marker="s", label="再現率")
    axes[0].axhline(cancel["base"]["positive_rate"], color="#7f8c8d", linestyle="--", linewidth=1, label="正例率（当て推量の適合率）")
    axes[0].set_xlabel("閾値")
    axes[0].set_ylabel("指標の値")
    axes[0].set_title("キャンセル予測: 閾値で適合率と再現率が入れ替わる")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(fontsize=8)

    names = MODEL_ORDER
    positions = np.arange(len(names), dtype="float64")
    mae = [regression["scores"][name]["mae"] for name in names]
    rmse = [regression["scores"][name]["rmse"] for name in names]
    axes[1].bar(positions - 0.18, mae, width=0.36, label="MAE", color="#2980b9")
    axes[1].bar(positions + 0.18, rmse, width=0.36, label="RMSE", color="#c0392b")
    for x, value in zip(positions - 0.18, mae):
        axes[1].text(x, value + 0.005, f"{value:.4f}", ha="center", fontsize=8)
    for x, value in zip(positions + 0.18, rmse):
        axes[1].text(x, value + 0.005, f"{value:.4f}", ha="center", fontsize=8)
    axes[1].set_xticks(positions)
    axes[1].set_xticklabels(names)
    axes[1].set_ylim(0.0, 0.70)
    axes[1].set_ylabel("誤差（星）")
    axes[1].set_title("星の回帰: MAE の 1 位と RMSE の 1 位が違う")
    axes[1].legend(fontsize=8)

    return save_fig(fig, FIGURE_NAME)


def main() -> None:
    cancel = cancel_report()
    print_cancel(cancel)
    regression = regression_report()
    print_regression(regression)
    print_class(class_report())

    print("■ 8. 誤った報告文を書き直す")
    for number, (wrong, fixed) in enumerate(zip(WRONG_CLAIMS, rewrite(cancel, regression)), start=1):
        print(f"({number}) 誤: {wrong}")
        print(f"    正: {fixed}")
    print()
    print(f"図を保存しました: outputs/{make_figure(cancel, regression)}")


if __name__ == "__main__":
    main()
