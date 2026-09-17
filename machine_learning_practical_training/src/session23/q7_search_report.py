"""問題7（実践）: 探索の実験ノートを 1 枚にまとめ、点検表で自分の手順を監査する。

実行:
    docker compose exec lab python src/session23/q7_search_report.py
"""

from __future__ import annotations

from common import fit_count, load_review_table
from default_baseline import baseline
from final_test import final
from grid_search import PARAM_GRID, search as run_grid_search
from random_search import PARAM_DIST, N_ITER, search as run_random_search

# 点検表の問い（順番も内容も変えずに使い回す）
CHECKS = [
    "C1 探索は訓練データの中だけで行ったか",
    "C2 選定は交差検証（5 分割）で行ったか",
    "C3 探索範囲は等比（対数スケール）で張ったか",
    "C4 探索なしの成績を上回ったか",
    "C5 上位の差がばらつきの中に収まっていないか確認したか",
    "C6 より単純なモデルと比べたか",
]


def ratios(values: list[float]) -> list[float]:
    return [round(float(values[i + 1] / values[i]), 4) for i in range(len(values) - 1)]


def report_rows(baseline_result: dict, grid_result: dict, random_result: dict, final_result: dict) -> list[dict]:
    """実験ノートの本体。どのデータで測った数値なのかを必ず併記する。"""
    return [
        {
            "label": "① 探索なし（既定値）",
            "measured_on": "訓練データの交差検証",
            "score": float(baseline_result["mean"]),
            "fits": int(baseline_result["n_fits"]),
        },
        {
            "label": "② グリッドサーチ 12 通り",
            "measured_on": "訓練データの交差検証",
            "score": float(grid_result["best_cv"]),
            "fits": int(grid_result["n_fits"]),
        },
        {
            "label": f"③ ランダムサーチ {N_ITER} 通り",
            "measured_on": "訓練データの交差検証",
            "score": float(random_result["best_cv"]),
            "fits": int(random_result["n_fits"]),
        },
        {
            "label": "④ ② の設定をテストで 1 回",
            "measured_on": "テストデータ（最後の 1 回）",
            "score": float(final_result["tuned_test"]),
            "fits": 1,
        },
        {
            "label": "⑤ ロジスティック回帰（S17）",
            "measured_on": "テストデータ（最後の 1 回）",
            "score": float(final_result["linear_test"]),
            "fits": 1,
        },
    ]


def audit(baseline_result: dict, grid_result: dict, random_result: dict, final_result: dict) -> list[dict]:
    """点検表。判定は「そう書いたから True」ではなく、結果の中身から計算する。"""
    rate_ratios = ratios(PARAM_DIST["model__learning_rate"])
    top3 = grid_result["table"][:3]
    findings = [
        (
            not any("test" in key for key in grid_result) and not any("test" in key for key in random_result),
            "探索の結果にテストデータのスコアが 1 つも含まれていない",
        ),
        (
            grid_result["n_fits"] == fit_count(PARAM_GRID),
            f"12 通り × 5 分割 = {grid_result['n_fits']} 回の学習",
        ),
        (
            max(rate_ratios) / min(rate_ratios) <= 1.5,
            f"learning_rate の倍率 {rate_ratios}",
        ),
        (
            grid_result["best_cv"] > float(baseline_result["mean"]),
            f"{baseline_result['mean']:.4f} → {grid_result['best_cv']:.4f}",
        ),
        (
            (top3[0]["mean"] - top3[2]["mean"]) < top3[0]["std"],
            f"上位 3 件の差 {top3[0]['mean'] - top3[2]['mean']:.4f} < 標準偏差 {top3[0]['std']:.4f}",
        ),
        (
            "linear_test" in final_result,
            f"線形モデルとの差 {final_result['gap_to_linear']:+.4f}",
        ),
    ]
    return [
        {"label": label, "ok": bool(ok), "note": note} for label, (ok, note) in zip(CHECKS, findings)
    ]


def analyze(df) -> dict[str, object]:
    """実験を順に走らせて、ノートと点検表を作る。"""
    baseline_result = baseline(df)
    grid_result = run_grid_search(df)
    random_result = run_random_search(df)
    final_result = final(df, grid_result["best_params"])
    rows = report_rows(baseline_result, grid_result, random_result, final_result)
    checks = audit(baseline_result, grid_result, random_result, final_result)
    return {
        "rows": rows,
        "checks": checks,
        "all_ok": all(check["ok"] for check in checks),
        "total_fits": sum(row["fits"] for row in rows),
        "linear_wins": bool(final_result["linear_wins"]),
    }


def main() -> None:
    df = load_review_table()
    result = analyze(df)

    print("■ 実験ノート（高評価レビューの分類・ROC AUC）")
    print("実験                        | 測った場所                 | ROC AUC | 学習回数")
    for row in result["rows"]:
        print(f"{row['label']:<26} | {row['measured_on']:<24} | {row['score']:.4f}  | {row['fits']:>3} 回")
    print(f"合計の学習回数 : {result['total_fits']} 回")
    print()

    print("■ 点検表")
    for check in result["checks"]:
        mark = "OK " if check["ok"] else "NG "
        print(f"{mark} {check['label']}")
        print(f"     根拠: {check['note']}")
    print(f"すべて OK : {result['all_ok']}")
    print()

    print("■ 結論（3 行）")
    print("1. 探索には意味があった（交差検証 0.8020 → 0.8143）。既定値のまま報告してはいけない。")
    print("2. ただし上位の差はばらつきの中にあり、『どの設定が最良か』は言い切れない。")
    print("3. 探索してもロジスティック回帰（0.8265）には届かない。探索はモデル選択の代わりにならない。")
    print(f"   線形モデルの勝ち : {result['linear_wins']}")


if __name__ == "__main__":
    main()
