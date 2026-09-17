"""課題11: 報告カードとレポートを書き上げる。

数値はすべて集計結果から f 文字列で埋めます。手打ちした数値は、データを
作り直した瞬間に古くなり、しかも誰も気づきません。

使い方:
    docker compose exec lab python src/final01/report.py
"""

from __future__ import annotations

from common import (
    AS_OF,
    CAPACITY,
    COUPON_COST_YEN,
    CUTOFF,
    HORIZON_DAYS,
    LABEL_START,
    LEAK_COLUMN,
    MONTHLY_BUDGET_YEN,
    NUMERIC,
    REPORT_PATH,
    baseline,
    capacity_plan,
    cv_scores,
    dataset,
    decide,
    fitted,
    leak_audit,
    monitoring_plan,
    predict_one,
    record_digest,
    sample_record,
    shap_additivity,
)
from explain import sentence
from figures import FIGURES

SERVED = "lgbm"     # 運用に載せるモデル（説明の要件があるので木のモデルにした）
REFERENCE = "logistic"  # 指標がいちばん良かったモデル（比較のために必ず報告する）


def gather() -> dict:
    """報告に必要な数値を 1 か所に集める。"""
    data = dataset()
    base = baseline()
    served = fitted(SERVED)
    reference = fitted(REFERENCE)
    plan = capacity_plan()
    audit = leak_audit()
    record = sample_record()
    proba = predict_one(served["model"], record)
    return {
        "data": data,
        "base": base,
        "served": served,
        "served_cv": cv_scores(SERVED),
        "reference": reference,
        "reference_cv": cv_scores(REFERENCE),
        "plan": plan,
        "audit": audit,
        "record": record,
        "proba": proba,
        "shap": shap_additivity(),
    }


def card(info: dict) -> list[tuple[str, str]]:
    """報告カード。順番を毎回同じにしておくと、読む人が差分を追える。"""
    data, base, served, plan = info["data"], info["base"], info["served"], info["plan"]
    return [
        ("予測タスク", f"cutoff {CUTOFF.date()} までの履歴から、{LABEL_START.date()}〜{AS_OF.date()} の再購入を当てる"),
        ("母集団", f"{data['n_customers']:,} 人（訓練 {data['n_train']:,} / 評価 {data['n_test']:,}）"),
        ("正例率", f"{data['positive_rate']:.4f}（再購入 {data['n_positive']:,} 人）"),
        ("ベースライン", f"accuracy {base['accuracy']:.4f} / ROC AUC {base['roc_auc']:.4f}"),
        ("採用モデル", f"{served['label']}（ROC AUC {served['roc_auc']:.4f} / PR-AUC {served['pr_auc']:.4f}）"),
        ("交差検証", f"{info['served_cv']['mean']:.4f} ± {info['served_cv']['std']:.4f}（層化 5 分割）"),
        ("accuracy", f"{served['accuracy']:.4f}（ベースライン {base['accuracy']:.4f} に対して +{(served['accuracy'] - base['accuracy']) * 100:.2f} ポイント）"),
        ("運用する閾値", f"{plan['threshold']:.1f}（送れる上限 {plan['capacity']:,} 通から逆算）"),
        ("その閾値の成績", f"適合率 {plan['precision']:.4f} / 再現率 {plan['recall']:.4f}"),
        ("件数", f"送る {plan['n_sent']:,} 人 / 当たり {plan['tp']:,} 人 / 空振り {plan['n_sent'] - plan['tp']:,} 人 / 見逃し {plan['fn']:,} 人"),
        ("費用", f"{plan['cost_yen']:,} 円（予算 {MONTHLY_BUDGET_YEN:,} 円・残り {plan['left_yen']:,} 円）"),
        ("リークの点検", f"予測期間の注文数を入れると ROC AUC {info['audit']['leaked_roc_auc']:.4f} → 不採用"),
    ]


def checks(info: dict) -> list[tuple[str, bool]]:
    """自分のための検算。件数の足し算が合わないなら、どこかがずれている。"""
    data, plan, served, base = info["data"], info["plan"], info["served"], info["base"]
    text = build_report(info)
    return [
        ("accuracy が単独で書かれていない（ベースラインと並べている）",
         f"{served['accuracy']:.4f}" in text and f"{base['accuracy']:.4f}" in text),
        ("送る = 当たり + 空振り", plan["n_sent"] == plan["tp"] + plan["fp"]),
        ("当たり + 見逃し = 評価データの再購入者", plan["tp"] + plan["fn"] == data["n_positive_test"]),
        ("費用が予算に収まっている", plan["cost_yen"] <= MONTHLY_BUDGET_YEN),
        ("図のファイル名がレポートに書かれている", all(name in text for name in FIGURES)),
    ]


def build_report(info: dict) -> str:
    """提出するレポート本文を組み立てる（見出しは 8 つ）。"""
    data, base, served, reference, plan, audit = (
        info["data"],
        info["base"],
        info["served"],
        info["reference"],
        info["plan"],
        info["audit"],
    )
    rules = "\n".join(
        f"- {rule['name']}: {rule['rule']} → {rule['action']}（{rule['cycle']}）"
        for rule in monitoring_plan()
    )
    return f"""# 再購入予測モデルの報告

## 0. 予測タスクと期間の切り方

cutoff を {CUTOFF.date()}（基準日 {AS_OF.date()} の {HORIZON_DAYS} 日前）に置き、
観測期間（〜{CUTOFF.date()}）の履歴だけで特徴量を作り、予測期間（{LABEL_START.date()}〜{AS_OF.date()}）の
再購入を目的変数にした。対象は cutoff までに有効注文がある顧客 {data['n_customers']:,} 人で、
そのうち {data['n_positive']:,} 人が再購入している（正例率 {data['positive_rate']:.4f}）。
特徴量は {len(NUMERIC)} 列の数値と 2 列のカテゴリで、すべて cutoff 以前の情報だけから作った。

## 1. ベースラインと比べた結果

何も学習しない予測（全員に「再購入する」と答える）は accuracy {base['accuracy']:.4f} / ROC AUC {base['roc_auc']:.4f} /
PR-AUC {base['pr_auc']:.4f} だった。業務の言葉に直すと「全員にクーポンを送る」方針である。
採用したモデルの accuracy は {served['accuracy']:.4f} で、ベースラインに対して
+{(served['accuracy'] - base['accuracy']) * 100:.2f} ポイントにすぎない。accuracy 単独では性能を語らない。

## 2. モデルの比較と採用したモデル

| モデル | ROC AUC | PR-AUC | accuracy | 交差検証（層化 5 分割） |
| :--- | :--- | :--- | :--- | :--- |
| ベースライン | {base['roc_auc']:.4f} | {base['pr_auc']:.4f} | {base['accuracy']:.4f} | — |
| {reference['label']} | {reference['roc_auc']:.4f} | {reference['pr_auc']:.4f} | {reference['accuracy']:.4f} | {info['reference_cv']['mean']:.4f} ± {info['reference_cv']['std']:.4f} |
| {served['label']} | {served['roc_auc']:.4f} | {served['pr_auc']:.4f} | {served['accuracy']:.4f} | {info['served_cv']['mean']:.4f} ± {info['served_cv']['std']:.4f} |

指標がいちばん良いのは {reference['label']} である（ROC AUC の差 {reference['roc_auc'] - served['roc_auc']:.4f}）。
差は交差検証の標準偏差より大きく、分け方の運では説明できない。
それでも運用に載せるのは {served['label']} とした。**1 人ごとの説明を毎回出す**という要件があり、
木のモデルなら SHAP（TreeExplainer）で安く分解できるためである。
説明の要件が無い場合は {reference['label']} を選ぶ。図: `{FIGURES[0]}`

## 3. 運用する閾値と予算の根拠

クーポン 1 通 {COUPON_COST_YEN:,} 円・予算 {MONTHLY_BUDGET_YEN:,} 円なので、送れるのは {CAPACITY:,} 通までである。
閾値 {plan['best_f1_threshold']:.1f} は F1 が最大（{plan['best_f1']:.4f}）だが送る通数が {plan['best_f1_n_sent']:,} 人で、
{plan['best_f1_over']:,} 通あふれるため選べない。採用する閾値は {plan['threshold']:.1f} で、
送る {plan['n_sent']:,} 人・当たり {plan['tp']:,} 人・空振り {plan['n_sent'] - plan['tp']:,} 人・見逃し {plan['fn']:,} 人、
適合率 {plan['precision']:.4f} / 再現率 {plan['recall']:.4f}、費用 {plan['cost_yen']:,} 円（残り {plan['left_yen']:,} 円）。
同じ枠を無作為に配ると当たりは約 {plan['random_hits']:,} 人で、通数が少ないのに当たりが多い。図: `{FIGURES[1]}`

## 4. リークの点検

予測期間の注文数（`{LEAK_COLUMN}`）を特徴量に足すと ROC AUC は {audit['leaked_roc_auc']:.4f} になる。
エラーも警告も出ない。この列は目的変数そのものから作られており
（`{LEAK_COLUMN} > 0` が答えと一致: {audit['is_target_itself']}）、予測時点では手に入らない。
報告する数値は、跳ねていない側（ROC AUC {audit['clean_roc_auc']:.4f}）である。図: `{FIGURES[3]}`

## 5. 1 人分の予測の説明

{sentence()}

加法性（SHAP 値の合計 + 基準値 = 対数オッズ）が成り立つことも確認した
（分解から復元した確率 {info['shap']['proba_from_shap']:.4f} = モデルの確率 {info['shap']['proba_from_model']:.4f}）。図: `{FIGURES[2]}`

## 6. 運用と監視

Pipeline とメタデータを 1 つのファイルに保存し、1 件推論は dict を検証してから渡す
（例: {record_digest(info['record'])} → 確率 {info['proba']:.4f} → {decide(info['proba'])}）。
監視は次の条件を先に決めた。

{rules}

## 7. この予測で言えないこと / 次の一歩

- 見逃した {plan['fn']:,} 人は、このモデルでは拾えない。閾値を下げれば拾えるが予算に収まらない。
- **クーポンを送ると再購入が増えるか**は、このデータからは言えない。過去に配信した記録がなく、
  「再購入しそうな人」と「配信で動く人」は別物である。効果を知るには配信する / しないを
  無作為に分けた比較が必要になる。
- cutoff を 1 つしか置いていないため、季節の影響と区別できていない。次は cutoff を複数置いて測る。
- 正解（再購入したか）は 90 日後にしか分からない。それまでは入力の分布（PSI）を監視する。
"""


def write_report(text: str) -> str:
    """レポートを outputs/ に書き出す（何度実行しても同じ内容になる）。"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(text, encoding="utf-8")
    return REPORT_PATH.name


def main() -> None:
    info = gather()

    print("■ 1. 報告カード")
    for label, value in card(info):
        print(f"{label}: {value}")
    print()

    print("■ 2. 検算")
    for label, ok in checks(info):
        print(f"[{'OK' if ok else 'NG'}] {label}")
    print()

    text = build_report(info)
    name = write_report(text)
    n_headings = text.count("\n## ")
    print("■ 3. レポートの書き出し")
    print(f"書き出しました: outputs/{name}")
    print(f"見出しの数: {n_headings}")
    print()
    print("判断: この 1 枚があれば、半年後の担当者が同じ判断を再現できます。")
    print("      再現できない報告は、どれだけ精度が高くても引き継げません。")


if __name__ == "__main__":
    main()
