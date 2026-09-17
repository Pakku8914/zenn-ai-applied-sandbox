"""セッション 25 の検証スクリプト。

「セッション25：Pipeline と ColumnTransformer ― 前処理と学習をひとつにまとめる」の
本文・練習問題・解答に載せた数値と挙動が、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/session25/verify_25.py
"""

from __future__ import annotations

import contextlib
import io
import warnings
from pathlib import Path

import by_hand_vs_pipeline
import custom_transformers
import feature_sets
import inspect_pipeline
import leak_by_design
import pipeline_basics
import q1_build_pipeline
import q2_feature_names
import q3_hand_vs_pipeline
import q4_cross_val
import q5_selection_leak
import q6_log_transform
import q7_frequency_encoder
from common import CATEGORICAL, DATA_DIR, NUMERIC, OUT_DIR, load_review_table

TOLERANCE = 0.005  # 指標の許容誤差（本書共通）
TIGHT = 0.0005     # 標準偏差や「差」など、もともと小さい値に使う許容誤差

EXPECTED_NAMES = [
    "num__unit_price",
    "num__pages",
    "num__published_year",
    "num__body_length",
    "cat__category_ビジネス",
    "cat__category_児童書",
    "cat__category_実用書",
    "cat__category_小説",
    "cat__category_技術書",
    "cat__region_北海道",
    "cat__region_大阪",
    "cat__region_宮城",
    "cat__region_広島",
    "cat__region_愛知",
    "cat__region_東京",
    "cat__region_福岡",
    "cat__channel_SNS",
    "cat__channel_メルマガ",
    "cat__channel_検索",
    "cat__channel_紹介",
]
FIGURES = [leak_by_design.FIGURE_NAME, feature_sets.FIGURE_NAME]

failures: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    ok = actual == expected
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual}")
    if not ok:
        print(f"     期待値: {expected}")
        failures.append(label)


def check_close(label: str, actual: float, expected: float, tol: float = TOLERANCE) -> None:
    ok = abs(float(actual) - expected) <= tol
    print(f"{'OK  ' if ok else 'NG  '} {label}: {float(actual):.4f}")
    if not ok:
        print(f"     期待値: {expected:.4f} ± {tol}")
        failures.append(label)


missing = [
    name for name in ("books", "customers", "orders", "reviews") if not (Path(DATA_DIR) / f"{name}.csv").exists()
]
if missing:
    print(f"NG   データが未生成です: {missing}")
    print("     先に `python tools/make_datasets.py` を実行してください。")
    raise SystemExit(1)

df = load_review_table()

# ------------------------------------------------------------------
# 0. 本文と練習問題のスクリプトが最後まで動くこと（出力は抑制する）
# ------------------------------------------------------------------
for name in FIGURES:
    (Path(OUT_DIR) / name).unlink(missing_ok=True)

modules = [
    pipeline_basics,
    by_hand_vs_pipeline,
    leak_by_design,
    custom_transformers,
    inspect_pipeline,
    feature_sets,
    q1_build_pipeline,
    q2_feature_names,
    q3_hand_vs_pipeline,
    q4_cross_val,
    q5_selection_leak,
    q6_log_transform,
    q7_frequency_encoder,
]
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    with contextlib.redirect_stdout(io.StringIO()):
        for module in modules:
            module.main()
    glyph_warnings = [w for w in caught if "Glyph" in str(w.message) or "missing from" in str(w.message)]
check("スクリプトが最後まで動いた数", len(modules), 13)
check("図の描画で出たフォント欠落の警告の数", len(glyph_warnings), 0)

for name in FIGURES:
    path = Path(OUT_DIR) / name
    size = path.stat().st_size if path.exists() else 0
    print(f"---  {name}: {size:,} バイト")
    check(f"{name} が保存され、サイズが 0 より大きいこと", size > 0, True)

# ------------------------------------------------------------------
# 1. 母集団（src/verify_setup.py の 5 節と同じ表に region・channel を足しただけであること）
# ------------------------------------------------------------------
basics = pipeline_basics.basics(df)
check("高評価分類に使うレビュー件数", basics["n_rows"], 14169)
check("訓練データの件数", basics["n_train"], 10626)
check("評価データの件数", basics["n_test"], 3543)
check_close("高評価（星 4 以上）の割合", float(df["is_high"].mean()), 0.8167, tol=TIGHT)
check("結合後の region の欠損", basics["region_missing"], 729)
check_close("結合後の region の欠損率", basics["region_missing_rate"], 0.0515, tol=TIGHT)

# ------------------------------------------------------------------
# 2. Pipeline と ColumnTransformer の形（本文 1 節・2 節）
# ------------------------------------------------------------------
check("最小の Pipeline のステップ名", basics["small_steps"], ["impute", "scale", "model"])
check("最小の Pipeline の predict_proba の形", basics["proba_shape"], (3543, 2))
check("組み立てた Pipeline のステップ名", basics["full_steps"], ["pre", "model"])
check("入力の列数", basics["n_input"], 7)
check("変換後の列数", basics["n_output"], 20)
check("category の水準の数", basics["levels"]["category"], 5)
check("region の水準の数", basics["levels"]["region"], 7)
check("channel の水準の数", basics["levels"]["channel"], 4)
check("変換後の列名", " / ".join(basics["names"]), " / ".join(EXPECTED_NAMES))
check_close("Pipeline のテスト ROC AUC", basics["auc"], 0.8265)

# ------------------------------------------------------------------
# 3. 手続き版と Pipeline 版が一致すること（本文 3 節）
# ------------------------------------------------------------------
hand = by_hand_vs_pipeline.compare(df)
check("手続き版の変換後の形", hand["hand_shape"], (10626, 20))
check("Pipeline 版の変換後の形", hand["pipe_shape"], (10626, 20))
check("訓練データの行列が一致すること", hand["same_train"], True)
check("評価データの行列が一致すること", hand["same_test"], True)
check_close("手続き版の ROC AUC", hand["hand_auc"], 0.8265)
check_close("Pipeline 版の ROC AUC", hand["pipeline_auc"], 0.8265)
check_close("2 つの ROC AUC の差", hand["auc_gap"], 0.0000, tol=TIGHT)
check("Pipeline 版の列名に接頭辞が付くこと", hand["pipe_columns"][0], "num__unit_price")
check("手続き版の列名は接頭辞なしであること", hand["hand_columns"][0], "unit_price")

# ------------------------------------------------------------------
# 4. Pipeline がリークを構造的に防ぐこと（本文 4 節・この章の山場）
# ------------------------------------------------------------------
scaler = leak_by_design.scaler_leak(df)
check("category だけの構成の変換後の列数", scaler["n_columns"], 9)
check_close("スケーラ: Pipeline に載せた場合", scaler["correct"], 0.8265)
check_close("スケーラ: 分割前に全データで fit した場合", scaler["leaked"], 0.8265)
check_close("スケーラのリークで生まれた差", scaler["gap"], 0.0000, tol=TIGHT)

selection = leak_by_design.selection_leak(df)
check("ノイズ列の形", selection["shape"], (14169, 500))
check_close("特徴量選択: 分割前に選んだ場合", selection["leaked"], 0.5591)
check_close("特徴量選択: Pipeline に入れた場合", selection["correct"], 0.5086)
check_close("特徴量選択のリークで生まれた差", selection["gap"], 0.0505)
check("Pipeline のまま交差検証すると当て推量の近くに戻ること", selection["cv_is_chance"], True)

# ------------------------------------------------------------------
# 5. 自作の変換（本文 5 節）
# ------------------------------------------------------------------
custom = custom_transformers.analyze(df)
check("log1p の枝を足しても列数は変わらないこと", custom["log_n_columns"], 20)
check(
    "log1p の枝の列名",
    custom["log_names"][:4],
    ["log__body_length", "num__unit_price", "num__pages", "num__published_year"],
)
check("FunctionTransformer の中身が np.log1p と一致すること", custom["log_matches_manual"], True)
check("log1p 版が当て推量を上回ること", custom["log_auc"] > 0.5, True)
check("QuantileClipper が覚えた列", custom["clip_columns"], NUMERIC)
check("QuantileClipper の get_feature_names_out", custom["clip_names_out"], NUMERIC)
check("評価データに訓練データの上限より大きい値があること", custom["test_had_larger_values"], True)
check("変換後は訓練データの上限を超えないこと", custom["test_within_train_bounds"], True)
check("クリップ版が当て推量を上回ること", custom["clip_cv_mean"] > 0.5, True)

# ------------------------------------------------------------------
# 6. Pipeline の中をたどる（本文 6 節）
# ------------------------------------------------------------------
inspected = inspect_pipeline.inspect(df)
check("get_feature_names_out が返す列数", inspected["n_names"], 20)
check("num__ で始まる列の数", inspected["n_numeric_names"], 4)
check("cat__ で始まる列の数", inspected["n_categorical_names"], 16)
check("水準の数（category / region / channel）", inspected["n_levels"], {"category": 5, "region": 7, "channel": 4})
check("係数の形", inspected["coef_shape"], (1, 20))
check("列名の数と係数の数が一致すること", inspected["names_match_coef"], True)
check("前処理だけを取り出した出力の形", inspected["transformed_shape"], (10626, 20))
check("set_params の前の C", inspected["c_before"], 1.0)
check("set_params の後の C", inspected["c_after"], 0.05)
check("再学習したモデルに反映された C", inspected["c_in_model"], 0.05)

# ------------------------------------------------------------------
# 7. 列を足しても評価は動かないこと（本文 7 節）
# ------------------------------------------------------------------
sets = feature_sets.compare(df)
check("7 節: category だけの構成の変換後の列数", sets["small"]["n_columns"], 9)
check("region・channel を足した構成の変換後の列数", sets["large"]["n_columns"], 20)
check_close("category だけのホールドアウト", sets["small"]["holdout"], 0.8265)
check_close("region・channel を足したホールドアウト", sets["large"]["holdout"], 0.8265)
check_close("ホールドアウトの差", sets["holdout_gap"], 0.0000)
check_close("category だけの交差検証の平均", sets["small"]["mean"], 0.8240)
check_close("category だけの交差検証の標準偏差", sets["small"]["std"], 0.0084, tol=TIGHT)
check_close("region・channel を足した交差検証の平均", sets["large"]["mean"], 0.8232)
check_close("region・channel を足した交差検証の標準偏差", sets["large"]["std"], 0.0083, tol=TIGHT)
check_close("交差検証の平均の差", sets["mean_gap"], 0.0008, tol=TIGHT)
check("差が標準偏差より小さいこと", sets["gap_within_std"], True)
check("region の欠損（再確認）", sets["region_missing"], 729)
check("channel の欠損", sets["channel_missing"], 0)

# ------------------------------------------------------------------
# 8. 練習問題の解答
# ------------------------------------------------------------------
q1 = q1_build_pipeline.analyze(df)
check("問題1 の変換後の列数", q1["n_output"], 20)
check("問題1 の変換前の region の欠損", q1["region_missing_before"], 729)
check("問題1 の変換後に残った欠損", q1["missing_after"], 0)
check_close("問題1 の ROC AUC", q1["auc"], 0.8265)

q2 = q2_feature_names.analyze(df)
check("問題2 の列数", q2["n_names"], 20)
check("問題2 の num__ の列数", q2["n_numeric"], 4)
check("問題2 の cat__ の列数", q2["n_onehot"], 16)
check("問題2 の列ごとの内訳", q2["per_column"], {"category": 5, "region": 7, "channel": 4})
check("問題2 の水準の数の合計", q2["levels_sum"], 16)
check("問題2 の係数の形", q2["coef_shape"], (1, 20))
check("問題2 の対応表の行数", q2["table_rows"], 20)

q3 = q3_hand_vs_pipeline.analyze(df)
check(
    "問題3 の各段の形",
    [shape for _, shape in q3["stages"]],
    [(10626, 4), (10626, 4), (10626, 3), (10626, 16)],
)
check("問題3 の手続き版の形", q3["hand_shape"], (10626, 20))
check("問題3 の訓練データの一致", q3["same_train"], True)
check("問題3 の評価データの一致", q3["same_test"], True)
check_close("問題3 の手続き版の ROC AUC", q3["hand_auc"], 0.8265)
check_close("問題3 の Pipeline 版の ROC AUC", q3["pipeline_auc"], 0.8265)
check_close("問題3 の ROC AUC の差", q3["auc_gap"], 0.0000, tol=TIGHT)

q4 = q4_cross_val.analyze(df)
check_close("問題4 の平均（region・channel あり）", q4["large"]["mean"], 0.8232)
check_close("問題4 の標準偏差（region・channel あり）", q4["large"]["std"], 0.0083, tol=TIGHT)
check_close("問題4 の平均（category だけ）", q4["small"]["mean"], 0.8240)
check_close("問題4 の標準偏差（category だけ）", q4["small"]["std"], 0.0084, tol=TIGHT)
check_close("問題4 の平均の差", q4["mean_gap"], 0.0008, tol=TIGHT)
check("問題4 の差が標準偏差より小さいこと", q4["gap_within_std"], True)
check_close("問題4 のホールドアウト − 交差検証の平均", q4["holdout_minus_cv"], 0.0033, tol=0.001)
check("問題4 の fit の呼び出し回数", q4["fit_calls"], 5)
check("問題4 の 1 回あたりの訓練件数", q4["fit_sizes"], [11335, 11336])

q5 = q5_selection_leak.analyze(df)
check("問題5 のノイズ列の形", q5["shape"], (14169, 500))
check_close("問題5 の Pipeline の外で選んだ場合", q5["leaked"], 0.5591)
check_close("問題5 の Pipeline の中で選んだ場合", q5["correct"], 0.5086)
check_close("問題5 の差", q5["gap"], 0.0505)
check("問題5 のリーク版が当て推量を 0.05 以上上回ること", q5["leaked_beats_chance"], True)
check("問題5 の正しい手順が当て推量から 0.01 以内であること", q5["correct_is_chance"], True)
check("問題5 の交差検証が当て推量の近くに戻ること", q5["cv_is_chance"], True)

q6 = q6_log_transform.analyze(df)
check("問題6 の列数", q6["n_names"], 20)
check("問題6 の log__ の列", q6["log_names"], ["log__unit_price", "log__body_length"])
check("問題6 の num__ の列", q6["num_names"], ["num__pages", "num__published_year"])
check("問題6 の cat__ の列数", q6["n_cat_names"], 16)
check("問題6 の log1p が手計算と一致すること", q6["matches_manual"], True)
check_close("問題6 の log1p なしの ROC AUC", q6["plain_auc"], 0.8265)
check("問題6 の log1p ありが当て推量を上回ること", q6["log_beats_chance"], True)

q7 = q7_frequency_encoder.analyze(df)
check("問題7 の列数", q7["n_names"], 7)
check(
    "問題7 の比率の列名",
    q7["freq_names"],
    ["cat__category_freq", "cat__region_freq", "cat__channel_freq"],
)
check("問題7 の水準の数", q7["n_levels"], {"category": 5, "region": 7, "channel": 4})
for column in CATEGORICAL:
    check_close(f"問題7 の比率の合計（{column}）", q7["sums"][column], 1.0, tol=TIGHT)
check_close("問題7 の未知の水準に当たる値", q7["unknown_value"], 0.0, tol=TIGHT)
check("問題7 の既知の水準がすべて 0 より大きいこと", q7["known_values_positive"], True)
check("問題7 で試した C の数", len(q7["rows"]), 3)
check("問題7 のどの C でも当て推量を上回ること", q7["all_beat_chance"], True)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("セッション 25 のすべての検証に成功しました。")
