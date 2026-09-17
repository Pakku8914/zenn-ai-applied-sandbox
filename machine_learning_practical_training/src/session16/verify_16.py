"""セッション 16 の検証スクリプト。

「セッション16：線形回帰と正則化」の本文・練習問題・解答に載せた数値と挙動が、
いまこの環境で再現できるかを確認します。期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/session16/verify_16.py
"""

from __future__ import annotations

import contextlib
import importlib
import io
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import numpy as np
from sklearn.linear_model import Lasso, Ridge

from common import (
    CORE_FEATURES,
    DATA_DIR,
    FEATURES,
    LASSO_ALPHAS,
    OUT_DIR,
    RIDGE_ALPHAS,
    TARGET,
    add_pages_dup,
    coef_series,
    fit_linear,
    fit_ols,
    fit_penalized,
    line_pred,
    load_rated_reviews,
    make_toy_line,
    regression_scores,
    split_xy,
    sse,
    standardize,
    vif_table,
    zero_columns,
)

TOLERANCE = 0.005  # 指標の許容誤差
COEF_TOLERANCE = 0.0005  # 係数の許容誤差
VIF_RELATIVE = 0.01  # VIF は桁が大きいので相対誤差で見る

DUP_FEATURES = CORE_FEATURES + ["pages_dup"]

failures: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    ok = actual == expected
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual}")
    if not ok:
        print(f"     期待値: {expected}")
        failures.append(label)


def check_close(label: str, actual: float, expected: float, tol: float = TOLERANCE) -> None:
    ok = abs(actual - expected) <= tol
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual:.4f}")
    if not ok:
        print(f"     期待値: {expected:.4f} ± {tol}")
        failures.append(label)


def check_coef(label: str, actual: float, expected: float, tol: float = COEF_TOLERANCE) -> None:
    """係数の検証。桁が小さいので専用の許容誤差を使う。"""
    ok = abs(actual - expected) <= tol
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual:+.6f}")
    if not ok:
        print(f"     期待値: {expected:+.6f} ± {tol}")
        failures.append(label)


def check_rel(label: str, actual: float, expected: float, rel: float = VIF_RELATIVE) -> None:
    """VIF のように桁が大きい値の検証（相対誤差）。"""
    ok = abs(actual - expected) <= abs(expected) * rel
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual:,.3f}")
    if not ok:
        print(f"     期待値: {expected:,.3f} ± {rel:.0%}")
        failures.append(label)


def check_range(label: str, actual: float, low: float, high: float) -> None:
    """p 値のように「桁だけ」を確認したい値の検証。"""
    ok = low <= actual <= high
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual:.2e}")
    if not ok:
        print(f"     期待値: {low:.2e} 〜 {high:.2e}")
        failures.append(label)


missing = [name for name in ("books", "reviews") if not (Path(DATA_DIR) / f"{name}.csv").exists()]
if missing:
    print(f"NG   データが未生成です: {missing}")
    print("     先に `python tools/make_datasets.py` を実行してください。")
    raise SystemExit(1)

# ------------------------------------------------------------------
# 1. 最小二乗法（5 点の練習データ）
# ------------------------------------------------------------------
toy = make_toy_line()
check("練習データの行数", len(toy), 5)
check_close("候補 傾き2.0/切片0.0 の SSE", sse(toy["y"], line_pred(toy["x"], 2.0, 0.0)), 2.0)
check_close("候補 傾き1.5/切片1.5 の SSE", sse(toy["y"], line_pred(toy["x"], 1.5, 1.5)), 1.5)
check_close("候補 傾き1.7/切片0.9 の SSE", sse(toy["y"], line_pred(toy["x"], 1.7, 0.9)), 1.1)
check_close("平均だけを返す線の SSE", sse(toy["y"], line_pred(toy["x"], 0.0, float(toy["y"].mean()))), 30.0)
toy_model = fit_linear(toy[["x"]], toy["y"])
check_close("最小二乗法が選んだ傾き", float(toy_model.coef_[0]), 1.7)
check_close("最小二乗法が選んだ切片", float(toy_model.intercept_), 0.9)
check_close("最小の SSE", sse(toy["y"], toy_model.predict(toy[["x"]])), 1.1)
check_close("練習データの R2", float(toy_model.score(toy[["x"]], toy["y"])), 0.9633)
check_close("残差の合計", float((toy["y"] - toy_model.predict(toy[["x"]])).sum()), 0.0)

# ------------------------------------------------------------------
# 2. 4 つの特徴量で星を予測する（生スケールの係数と当てはまり）
# ------------------------------------------------------------------
df = load_rated_reviews()
check("星が入っているレビューの件数", len(df), 14169)
check("使う特徴量", FEATURES, ["price", "pages", "published_year", "body_length"])

X_train, X_test, y_train, y_test = split_xy(df)
check("訓練データの件数", len(X_train), 10626)
check("評価データの件数", len(X_test), 3543)
check("分割の合計が 14,169 件になること", len(X_train) + len(X_test), 14169)

model = fit_linear(X_train, y_train)
raw_coefs = coef_series(model, X_train.columns)
check_coef("price の係数（生スケール）", float(raw_coefs["price"]), -0.000455)
check_coef("pages の係数（生スケール）", float(raw_coefs["pages"]), 0.001524)
check_coef("published_year の係数（生スケール）", float(raw_coefs["published_year"]), -0.001784)
check_coef("body_length の係数（生スケール）", float(raw_coefs["body_length"]), -0.002498)
check_close("切片", float(model.intercept_), 8.1589)

# 本文で読みかえている「現実的な差」あたりの効果
check_close("価格 +1,000 円あたりの星の変化", float(raw_coefs["price"] * 1000), -0.455)
check_close("ページ +100 あたりの星の変化", float(raw_coefs["pages"] * 100), 0.152)
check_close("本文 +100 文字あたりの星の変化", float(raw_coefs["body_length"] * 100), -0.250)
check_close("刊行年 +10 年あたりの星の変化", float(raw_coefs["published_year"] * 10), -0.018)

scores = regression_scores(model, X_test, y_test)
check_close("評価データの R2", scores["r2"], 0.2060)
check_close("評価データの MAE", scores["mae"], 0.3954)
check_close("評価データの RMSE", scores["rmse"], 0.5267)
baseline_rmse = scores["rmse"] / np.sqrt(1 - scores["r2"])
check_close("平均だけを返すモデルの RMSE（逆算）", float(baseline_rmse), 0.5910)
check_close("評価データの星の標準偏差", float(y_test.std(ddof=0)), 0.5910)

# ------------------------------------------------------------------
# 3. 標準化してから係数を比べる
# ------------------------------------------------------------------
X_train_s, X_test_s, _ = standardize(X_train, X_test)
check_close("標準化後の訓練データの平均（price）", float(X_train_s["price"].mean()), 0.0)
check_close("標準化後の訓練データの標準偏差（price）", float(X_train_s["price"].std(ddof=0)), 1.0)
std_model = fit_linear(X_train_s, y_train)
std_coefs = coef_series(std_model, X_train_s.columns)
check_close("price の係数（標準化後）", float(std_coefs["price"]), -0.4227)
check_close("pages の係数（標準化後）", float(std_coefs["pages"]), 0.2429)
check_close("published_year の係数（標準化後）", float(std_coefs["published_year"]), -0.0060)
check_close("body_length の係数（標準化後）", float(std_coefs["body_length"]), -0.1687)
check_close("標準化しても R2 は変わらない", regression_scores(std_model, X_test_s, y_test)["r2"], 0.2060)
check_close(
    "price は body_length の何倍か（標準化後）",
    abs(float(std_coefs["price"])) / abs(float(std_coefs["body_length"])),
    2.5,
    tol=0.05,
)
check(
    "標準化後の切片が訓練データの星の平均と一致すること",
    bool(np.isclose(std_model.intercept_, y_train.mean())),
    True,
)
check(
    "生スケールと標準化後で「絶対値がいちばん大きい列」が違うこと",
    [str(raw_coefs.abs().idxmax()), str(std_coefs.abs().idxmax())],
    ["body_length", "price"],
)

# ------------------------------------------------------------------
# 4. statsmodels で係数の確かさを見る（訓練データ）
# ------------------------------------------------------------------
result = fit_ols(X_train, y_train)
check("statsmodels の観測数", int(result.nobs), 10626)
check_close("statsmodels の R2（訓練データ）", float(result.rsquared), 0.1921)
check_close("statsmodels の調整済み R2", float(result.rsquared_adj), 0.1918)
check(
    "scikit-learn と statsmodels の係数が一致すること",
    bool(np.allclose(raw_coefs.to_numpy(), result.params[FEATURES].to_numpy())),
    True,
)
check_range("price の p 値", float(result.pvalues["price"]), 1e-84, 1e-82)
check_range("pages の p 値", float(result.pvalues["pages"]), 1e-29, 1e-28)
check_range("body_length の p 値", float(result.pvalues["body_length"]), 1e-224, 1e-222)
check_close("published_year の p 値", float(result.pvalues["published_year"]), 0.2425)
check(
    "p < 0.05 だった列",
    [name for name in FEATURES if result.pvalues[name] < 0.05],
    ["price", "pages", "body_length"],
)
conf = result.conf_int()  # 列名に頼らず位置（1 列目が下限・2 列目が上限）で取り出す
check_coef("price の 95% 信頼区間の下限", float(conf.loc["price"].iloc[0]), -0.000501)
check_coef("price の 95% 信頼区間の上限", float(conf.loc["price"].iloc[1]), -0.000409)
check(
    "published_year の信頼区間が 0 をまたぐこと",
    bool(conf.loc["published_year"].iloc[0] < 0 < conf.loc["published_year"].iloc[1]),
    True,
)
check("LinearRegression に p 値の属性が無いこと", hasattr(model, "pvalues"), False)

# ------------------------------------------------------------------
# 5. 多重共線性（14,169 件すべてを使う。データそのものの性質だから）
# ------------------------------------------------------------------
vif = vif_table(df[FEATURES])
check_rel("price の VIF", float(vif["price"]), 17.432)
check_rel("pages の VIF", float(vif["pages"]), 17.432)
check_rel("published_year の VIF", float(vif["published_year"]), 1.000)
check_rel("body_length の VIF", float(vif["body_length"]), 1.000)
check_close("corr(pages, price)", float(df["pages"].corr(df["price"])), 0.9709)
check("VIF が 10 を超えた列", [str(name) for name, value in vif.items() if value > 10], ["price", "pages"])

dup = add_pages_dup(df)
check("pages_dup を足したあとの行数", len(dup), 14169)
vif_after = vif_table(dup[DUP_FEATURES])
check_rel("pages の VIF（写しあり）", float(vif_after["pages"]), 911199.0)
check_rel("pages_dup の VIF（写しあり）", float(vif_after["pages_dup"]), 911107.0)
check(
    "VIF が 10 を超えた列（写しあり）",
    [str(name) for name, value in vif_after.items() if value > 10],
    ["price", "pages", "pages_dup"],
)

y_all = df[TARGET]
base_all = fit_ols(df[FEATURES], y_all)
core_all = fit_ols(df[CORE_FEATURES], y_all)
shaken = fit_ols(dup[DUP_FEATURES], y_all)
check_coef("published_year を外しても pages の係数は動かない", float(core_all.params["pages"]), 0.001524)
check_coef("写しなし（4 列）の pages の係数", float(base_all.params["pages"]), 0.001524)
check_coef("写しあり（+ pages_dup）の pages の係数", float(shaken.params["pages"]), -0.00915)
check_close("写しありの pages の p 値", float(shaken.pvalues["pages"]), 0.7311)
check("写しありで pages が有意でないこと", bool(shaken.pvalues["pages"] >= 0.05), True)
check_coef("写しありの price の係数", float(shaken.params["price"]), -0.00046)
check_coef("写しありの body_length の係数", float(shaken.params["body_length"]), -0.0025)
check_close("写しありの切片", float(shaken.params["const"]), 4.56051, tol=0.002)
check(
    "写しを足しても当てはまり（R2）はほとんど変わらないこと",
    bool(abs(core_all.rsquared - shaken.rsquared) < 0.001),
    True,
)
check(
    "pages の係数の符号が反転すること",
    bool(core_all.params["pages"] > 0 > shaken.params["pages"]),
    True,
)

# ------------------------------------------------------------------
# 6. Ridge ― この場面ではほとんど効かない
# ------------------------------------------------------------------
expected_ridge = {0.1: (-0.4226, 0.2060), 1.0: (-0.4217, 0.2060), 10.0: (-0.4122, 0.2060), 100.0: (-0.3405, 0.2047)}
for alpha in RIDGE_ALPHAS:
    coefs, r2 = fit_penalized(Ridge(alpha=alpha), X_train_s, y_train, X_test_s, y_test)
    expected_coef, expected_r2 = expected_ridge[alpha]
    check_close(f"Ridge α={alpha} の price の係数", float(coefs["price"]), expected_coef)
    check_close(f"Ridge α={alpha} の R2", r2, expected_r2)
    check(f"Ridge α={alpha} でゼロになった列が無いこと", zero_columns(coefs), [])

# ------------------------------------------------------------------
# 7. Lasso ― α を上げると係数がゼロになっていく（変数選択）
# ------------------------------------------------------------------
expected_lasso = {
    0.001: (4, [], 0.2057),
    0.01: (2, ["pages", "published_year"], 0.1945),
    0.1: (2, ["pages", "published_year"], 0.1314),
    1.0: (0, ["price", "pages", "published_year", "body_length"], 0.0),
}
for alpha in LASSO_ALPHAS:
    coefs, r2 = fit_penalized(Lasso(alpha=alpha), X_train_s, y_train, X_test_s, y_test)
    expected_nonzero, expected_zeros, expected_r2 = expected_lasso[alpha]
    check(f"Lasso α={alpha} の非ゼロの数", len(coefs) - len(zero_columns(coefs)), expected_nonzero)
    check(f"Lasso α={alpha} でゼロになった列", zero_columns(coefs), expected_zeros)
    check_close(f"Lasso α={alpha} の R2", r2, expected_r2)

strongest = Lasso(alpha=1.0).fit(X_train_s, y_train)
check(
    "Lasso α=1.0 の予測が訓練データの星の平均と一致すること",
    bool(np.allclose(strongest.predict(X_test_s), y_train.mean())),
    True,
)

# ------------------------------------------------------------------
# 8. 本文と練習問題のスクリプトが動き、図が保存されること
# ------------------------------------------------------------------
OUT_DIR.mkdir(parents=True, exist_ok=True)
FIGURES = [
    "s16_least_squares.png",
    "s16_coef_scale.png",
    "s16_vif_shock.png",
    "s16_conf_int.png",
    "s16_alpha_path.png",
    "s16_q5_regularization.png",
]
SCRIPTS = [
    "least_squares",
    "fit_star_rating",
    "coef_scale",
    "multicollinearity",
    "ols_inference",
    "regularization",
    "q1_least_squares",
    "q2_read_coefficients",
    "q3_read_summary",
    "q4_vif_check",
    "q5_regularization_table",
    "q6_stability",
]
executed: list[str] = []
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        for name in SCRIPTS:
            importlib.import_module(name).main()  # 例外が出ればここで検証が止まる
            executed.append(name)
    glyph_warnings = [w for w in caught if "Glyph" in str(w.message) or "missing from" in str(w.message)]
check("例外なく動いたスクリプトの数", len(executed), len(SCRIPTS))
check("日本語フォントの欠落警告の数", len(glyph_warnings), 0)
for name in FIGURES:
    path = OUT_DIR / name
    check(f"図 {name} が保存されていること", path.exists() and path.stat().st_size > 0, True)

# ------------------------------------------------------------------
# 9. 練習問題の解答コードが、本文と同じ数値を出すこと
# ------------------------------------------------------------------
q1 = importlib.import_module("q1_least_squares")
q1_toy = q1.make_toy()
check_close("問題1 傾き2.0/切片0.0 の SSE", q1.sse_of_line(q1_toy, 2.0, 0.0), 2.0)
check_close("問題1 傾き1.5/切片1.5 の SSE", q1.sse_of_line(q1_toy, 1.5, 1.5), 1.5)
check_close("問題1 傾き1.7/切片0.9 の SSE", q1.sse_of_line(q1_toy, 1.7, 0.9), 1.1)
grid_slope, grid_sse = q1.best_slope_by_grid(q1_toy, q1.GRID_SLOPES)
check("問題1 総当たりで最小になった傾き", grid_slope, 1.7)
check_close("問題1 そのときの SSE", grid_sse, 1.1)
formula_slope, formula_intercept, s_xy, s_xx = q1.slope_by_formula(q1_toy)
check_close("問題1 Sxy", s_xy, 17.0)
check_close("問題1 Sxx", s_xx, 10.0)
check_close("問題1 公式の傾き", formula_slope, 1.7)
check_close("問題1 公式の切片", formula_intercept, 0.9)

q2 = importlib.import_module("q2_read_coefficients")
effects = dict(q2.readable_effects(raw_coefs))
check_close("問題2 価格 +1,000 円", effects["価格が 1,000 円高い"], -0.455)
check_close("問題2 ページ +100", effects["ページ数が 100 ページ多い"], 0.152)
check_close("問題2 本文 +100 文字", effects["本文が 100 文字長い"], -0.250)
check_close("問題2 刊行年 +10 年", effects["刊行年が 10 年新しい"], -0.018)
check("問題2 生スケールの順位", q2.rank_by_abs(raw_coefs), ["body_length", "published_year", "pages", "price"])
check("問題2 標準化後の順位", q2.rank_by_abs(std_coefs), ["price", "pages", "body_length", "published_year"])

q3 = importlib.import_module("q3_read_summary")
q3_table = q3.summary_table(result)
check_coef("問題3 price の係数", float(q3_table.loc["price", "coef"]), -0.000455)
check_close("問題3 published_year の p 値", float(q3_table.loc["published_year", "p_value"]), 0.2425)
check_coef("問題3 price の信頼区間の下限", float(q3_table.loc["price", "ci_low"]), -0.000501)
check_coef("問題3 price の信頼区間の上限", float(q3_table.loc["price", "ci_high"]), -0.000409)
check_close("問題3 price の信頼区間の幅", float(q3_table.loc["price", "ci_high"] - q3_table.loc["price", "ci_low"]), 0.000092, tol=0.00001)
check(
    "問題3 0 をまたぐ列",
    [str(name) for name, row in q3_table.iterrows() if q3.crosses_zero(row)],
    ["published_year"],
)

q4 = importlib.import_module("q4_vif_check")
check_rel("問題4 自作 VIF（price）", q4.vif_by_hand(df[FEATURES], "price"), 17.432)
check_rel("問題4 自作 VIF（pages）", q4.vif_by_hand(df[FEATURES], "pages"), 17.432)
check(
    "問題4 自作 VIF が statsmodels と一致すること",
    bool(np.allclose(q4.vif_all_by_hand(df[FEATURES])[FEATURES].to_numpy(), vif[FEATURES].to_numpy())),
    True,
)
check_rel("問題4 写しあり VIF（pages）", float(q4.vif_table(dup[DUP_FEATURES])["pages"]), 911199.0)

q5 = importlib.import_module("q5_regularization_table")
ridge_table = q5.penalty_table(lambda a: Ridge(alpha=a), RIDGE_ALPHAS, X_train_s, y_train, X_test_s, y_test)
lasso_table = q5.penalty_table(lambda a: Lasso(alpha=a), LASSO_ALPHAS, X_train_s, y_train, X_test_s, y_test)
check_close("問題5 Ridge α=100 の price の係数", float(ridge_table.loc[3, "price"]), -0.3405)
check("問題5 Ridge はどの α でも 4 つ非ゼロ", list(ridge_table["n_nonzero"]), [4, 4, 4, 4])
check("問題5 Lasso の非ゼロの数", list(lasso_table["n_nonzero"]), [4, 2, 2, 0])
check("問題5 Lasso α=0.01 で落ちる列", lasso_table.loc[1, "zeros"], ["pages", "published_year"])
check_close("問題5 Lasso α=1.0 の R2", float(lasso_table.loc[3, "r2"]), 0.0)

q6 = importlib.import_module("q6_stability")
X6_train, _, y6_train, _ = split_xy(dup, DUP_FEATURES)
plain_blocks = q6.pages_coefs_by_block(X6_train, y6_train, CORE_FEATURES)
dup_blocks = q6.pages_coefs_by_block(X6_train, y6_train, DUP_FEATURES)
print(f"---  参考（ブロックごとの pages の係数）: 写しなし {[round(v, 5) for v in plain_blocks]}")
print(f"---  参考（ブロックごとの pages の係数）: 写しあり {[round(v, 5) for v in dup_blocks]}")
check("問題6 ブロックの数", len(plain_blocks), 4)
check(
    "問題6 写しありでばらつきが 10 倍以上に広がること",
    bool(q6.spread(dup_blocks) > q6.spread(plain_blocks) * 10),
    True,
)
check("問題6 写しなしのばらつきが 0.002 未満であること", bool(q6.spread(plain_blocks) < 0.002), True)
check(
    "問題6 写しありで pages の標準誤差が 10 倍以上になること",
    bool(
        q6.standard_error(X6_train, y6_train, DUP_FEATURES)
        > q6.standard_error(X6_train, y6_train, CORE_FEATURES) * 10
    ),
    True,
)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("セッション 16 のすべての検証に成功しました。")
