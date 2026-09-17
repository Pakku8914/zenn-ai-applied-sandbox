"""課題10 の解答: 報告カードを表示し、レポート本文を outputs/ に書き出す。

このスクリプトは課題1〜課題9 の関数をすべて呼ぶため、内部で 20 回ほど学習します
（数十秒かかります）。同じプロセスの中では学習結果を使い回しています。

実行:
    docker compose exec lab python src/mid02/report.py
"""

from __future__ import annotations

from pathlib import Path

from common import (
    BUSINESS_DAYS,
    CALLS_PER_DAY,
    N_SPLITS,
    OPERATORS,
    OUT_DIR,
    cancel_probabilities,
    describe_split,
    format_calls,
    load_order_table,
    print_report_card,
    report_card,
)
from features import add_all_features, run_steps
from leak_audit import CHECKLIST, audit
from sampling import compare_sampling
from thresholds import capacity_plan
from validate import cross_check

REPORT_NAME = "mid02_report.md"


def gather() -> dict[str, object]:
    """レポートに書く数値を 1 か所に集める（本文には手打ちの数値を書かない）。"""
    df = load_order_table()
    y_test, proba = cancel_probabilities("plain")
    plan = capacity_plan()
    chosen = plan["chosen"]
    return {
        "counts": describe_split(df),
        "card": report_card(y_test, proba, chosen["threshold"]),
        "plan": plan,
        "steps": run_steps(add_all_features(df)),
        "cv": cross_check(),
        "leak": audit(),
        "sampling": compare_sampling(),
    }


def build_report(data: dict[str, object] | None = None) -> str:
    """レポート本文（Markdown）を組み立てて返す。"""
    data = gather() if data is None else data
    counts, card, plan = data["counts"], data["card"], data["plan"]
    steps, cv, leak, sampling = data["steps"], data["cv"], data["leak"], data["sampling"]
    chosen = plan["chosen"]
    base_step = next(step for step in steps if step["key"] == "②")
    leaked = leak["leaked"]

    lines = [
        "# キャンセル予測モデルの報告（中間プロジェクト②）",
        "",
        "## 0. 予測タスクと母集団",
        "",
        "- 予測するもの: 入った注文が、あとでキャンセルされるかどうか（陽性 = キャンセル）",
        "- 使う場面: キャンセルされそうな注文に、確認の連絡を入れる",
        f"- 母集団: 重複した order_id を落とした注文 {counts['n_rows']:,} 件"
        f"（キャンセル {counts['n_positive']:,} 件・正例率 {counts['rate_all']:.4f}）",
        f"- 分割: 訓練 {counts['n_train']:,} 件 / 評価 {counts['n_test']:,} 件"
        f"（test_size=0.25・random_state=42・層化あり。評価データの正例 {counts['n_test_positive']:,} 件）",
        f"- 特徴量: {base_step['n_features']} 列（単価・数量・値引き率・登録からの経過日数・流入経路）",
        "- モデル: LightGBM（n_estimators=200・random_state=42）",
        "",
        "## 1. 報告する指標",
        "",
        f"- PR-AUC: **{card['pr_auc']:.4f}**"
        f"（ベースライン = 正例率 {card['positive_rate']:.4f} の {card['pr_lift']:.1f} 倍）",
        f"- ROC AUC: {card['roc_auc']:.4f}（参考値。不均衡データでは楽観的に見える）",
        f"- Brier スコア: {card['brier']:.5f}（予測確率の平均 {card['mean_proba']:.4f}"
        f" / 実際の正例率 {card['positive_rate']:.4f}）",
        f"- accuracy は報告しない: 全件を「キャンセルされない」と答えても"
        f" {card['accuracy_not_reported']:.4f} になり、モデルの値と一致するため",
        "",
        "## 2. 運用する閾値とその根拠",
        "",
        f"- 前提: オペレーター {OPERATORS} 名 × 1 日 {CALLS_PER_DAY} 件 × {BUSINESS_DAYS} 営業日"
        f" = 月 {card['capacity']:,} 件まで連絡できる",
        f"- 選んだ閾値: **{chosen['threshold']:.1f}**"
        f"（枠に収まる閾値のうち再現率が最大。陽性 {chosen['n_positive']:,} 件で"
        f" {card['headroom']:,} 件の余裕）",
        f"- 適合率 {chosen['precision']:.4f} / 再現率 {chosen['recall']:.4f}"
        f"（連絡 {format_calls(chosen['calls_per_catch'])}で 1 件が当たり）",
        f"- 混同行列: 捕まえた {card['tp']:,} 件 / 見逃した {card['fn']:,} 件"
        f" / 空振り {card['fp']:,} 件",
        f"- 既定の 0.5 を使わない理由: 陽性が {plan['rows'][-1]['n_positive']:,} 件しかなく、"
        f"実際のキャンセル {card['n_positive']:,} 件のうち {plan['rows'][-1]['tp']:,} 件しか捕まえられない"
        f"（再現率 {plan['rows'][-1]['recall']:.4f}）",
        f"- 閾値 0.1 を使わない理由: 陽性 {plan['rows'][0]['n_positive']:,} 件は枠の"
        f" {plan['rows'][0]['load_ratio']:.2f} 倍で、連絡しきれない",
        "- 図: outputs/mid02_pr_curve.png・outputs/mid02_threshold_tradeoff.png",
        "",
        "## 3. 特徴量の増分実験",
        "",
        "| 段階 | 列数 | ROC AUC | PR-AUC |",
        "| :--- | ---: | ---: | ---: |",
    ]
    lines += [
        f"| {step['label']} | {step['n_features']} | {step['roc_auc']:.4f} | {step['pr_auc']:.4f} |"
        for step in steps
    ]
    lines += [
        "",
        f"- 採用: ②（{base_step['n_features']} 列）。③〜⑥ は足しても PR-AUC が上がらなかったので戻した",
        "- ⑦ は採用しない（リーク。理由は 4 節）",
        "",
        "## 4. 交差検証とリークの点検",
        "",
        f"- 層化 {N_SPLITS} 分割の交差検証: PR-AUC の平均 {cv['pr_mean']:.4f}"
        f"（標準偏差 {cv['pr_std']:.4f}）",
        f"- ホールドアウト 1 回の {cv['holdout_pr_auc']:.4f} と近いか: {cv['consistent']}"
        f" / どの fold もベースラインを上回ったか: {cv['all_above_baseline']}",
        f"- リークの再現: ⑦（全期間のキャンセル数）を足すと PR-AUC が {leaked['pr_auc']:.4f} に跳ねた"
        f"（⑥ の {leak['clean']['pr_auc']:.4f} の {leak['pr_ratio']:.1f} 倍）",
        f"- その列は予測時点で手に入らない（その注文自身の結果を含む）。"
        f"値が 0 の行のキャンセル率は {leak['zero_rows_cancel_rate']:.2%}",
        f"- 採用したモデルは跳ねていない（疑う段階: {' '.join(leak['suspicious_keys'])} のみ）",
        "- 点検したこと:",
    ]
    lines += [f"  {index}. {item}" for index, item in enumerate(CHECKLIST, start=1)]
    lines += [
        "",
        "## 5. この予測で言えないこと",
        "",
        f"- 見逃しは {card['fn']:,} 件ある。この閾値は「連絡できる件数」で決めたので、"
        "見逃しを減らすには人を増やすしかない",
        "- なぜキャンセルされるかは説明できない（相関を因果として読まない）",
        f"- class_weight=\"balanced\" や 1:1 アンダーサンプリングは PR-AUC を改善せず"
        f"（{sampling['pr_improved']['balanced']} / {sampling['pr_improved']['under']}）、"
        f"予測確率の平均が {sampling['scores']['balanced']['mean_proba']:.4f} /"
        f" {sampling['scores']['under']['mean_proba']:.4f} に膨らむため採用しない",
        "- 連絡したことでキャンセルが減るかどうかは、このデータからは分からない（介入の効果は測っていない）",
        "",
        "## 6. 次の一歩",
        "",
        "- 連絡した注文の結果を記録して、次の学習データにする（今のデータには連絡の履歴がない）",
        "- 前処理と学習を Pipeline にまとめ、手順の抜けを防ぐ",
        "- 月ごとに PR-AUC と予測確率の平均を測り、下がったら学習をやり直す",
        "",
    ]
    return "\n".join(lines)


def write_report(text: str) -> Path:
    """レポート本文をファイルに書き出す（何度実行しても同じ内容になる）。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / REPORT_NAME
    path.write_text(text, encoding="utf-8")
    return path


def main() -> None:
    data = gather()
    card = data["card"]

    print_report_card(card, "キャンセル予測・基準モデル")
    print()

    print("■ 検算")
    print(f"報告カードに accuracy が入っていないこと : {'accuracy' not in card}")
    print(f"陽性と予測 = 捕まえた + 空振り : "
          f"{card['n_predicted_positive'] == card['tp'] + card['fp']}"
          f"（{card['n_predicted_positive']:,} = {card['tp']:,} + {card['fp']:,}）")
    print(f"捕まえた + 見逃した = 実際のキャンセル : "
          f"{card['tp'] + card['fn'] == card['n_positive']}"
          f"（{card['tp']:,} + {card['fn']:,} = {card['n_positive']:,}）")
    print()

    path = write_report(build_report(data))
    print(f"レポートを書き出しました: outputs/{path.name}")


if __name__ == "__main__":
    main()
