"""セッション 7 の検証スクリプト。

「セッション7：時系列を扱う ― 日時型・resample・移動平均」の本文・練習問題・解答に
載せた数値と挙動が、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/session07/verify_07.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from common import DATA_DIR, REFERENCE_DATE, WEEKDAY_JA, load_orders, load_valid_orders, make_toy

TOLERANCE = 0.005  # 指標の許容誤差

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


def check_yen(label: str, actual: int, expected: int) -> None:
    """金額の検証。端数の丸め方の違いで 1 円ずれることがあるため 1 円まで許容する。"""
    ok = abs(actual - expected) <= 1
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual:,} 円")
    if not ok:
        print(f"     期待値: {expected:,} 円 ± 1")
        failures.append(label)


missing = [name for name in ("customers", "orders") if not (Path(DATA_DIR) / f"{name}.csv").exists()]
if missing:
    print(f"NG   データが未生成です: {missing}")
    print("     先に `python tools/make_datasets.py` を実行してください。")
    raise SystemExit(1)

# ------------------------------------------------------------------
# 1. 日時型と期間の全体像
# ------------------------------------------------------------------
orders = load_orders()
ordered_at = orders["ordered_at"]
check("ordered_at の dtype", str(ordered_at.dtype), "datetime64[us]")
check("最初の注文日", f"{ordered_at.min():%Y-%m-%d}", "2024-01-09")
check("最後の注文（時刻まで）", str(ordered_at.max()), "2026-09-01 00:00:00")
check("期間の長さ（日）", (ordered_at.max() - ordered_at.min()).days + 1, 967)

as_text = ordered_at.astype("str")
check("astype('str') 後の dtype", str(as_text.dtype), "str")
try:
    as_text.dt.year
    dt_error = ""
except AttributeError as exc:
    dt_error = str(exc)
print(f"---  文字列に .dt を使ったときのメッセージ: {dt_error}")
check("文字列に .dt が使えないこと", "Can only use .dt accessor" in dt_error, True)

# pandas 3.0 は 0 時のタイムスタンプを "2024-01-09" と日付だけで文字列化するため、
# 時刻まで決め打ちした format では ValueError になる（本文の :::message alert で扱っている）
try:
    pd.to_datetime(as_text, format="%Y-%m-%d %H:%M:%S")
    strict_format_raises = False
except ValueError:
    strict_format_raises = True
check("時刻まで決め打ちした format では ValueError になること", strict_format_raises, True)
check("astype('str') が日付だけの文字列になること", as_text.iloc[0], "2024-01-09")
restored = pd.to_datetime(as_text, format="ISO8601")
check("文字列から復元したときの NaT の数", int(restored.isna().sum()), 0)
check("復元した列の先頭の年", int(restored.dt.year.iloc[0]), 2024)

raw = pd.Series(["2026-09-01", "2026-09-31", "不明", ""])
coerced = pd.to_datetime(raw, errors="coerce")
check("errors='coerce' で NaT になった数", int(coerced.isna().sum()), 3)
check("errors='coerce' で変換できた値", str(coerced.iloc[0]), "2026-09-01 00:00:00")
try:
    pd.to_datetime(raw)
    coerce_raises = False
except ValueError:
    coerce_raises = True
check("既定（errors='raise'）では例外になること", coerce_raises, True)

# ------------------------------------------------------------------
# 2. タイムゾーン
# ------------------------------------------------------------------
jst = REFERENCE_DATE.tz_localize("Asia/Tokyo")
check("JST を付けた基準日", str(jst), "2026-09-01 00:00:00+09:00")
check("UTC に変換した基準日", str(jst.tz_convert("UTC")), "2026-08-31 15:00:00+00:00")
check("UTC 換算では日付が前日になること", str(jst.tz_convert("UTC").date()), "2026-08-31")
try:
    _ = ordered_at > jst
    tz_error = ""
except TypeError as exc:
    tz_error = str(exc)
print(f"---  naive と aware を比べたときのメッセージ: {tz_error}")
check("naive と aware の比較が TypeError になること", "Invalid comparison" in tz_error, True)

# ------------------------------------------------------------------
# 3. dt アクセサ（練習用データ 6 件）
# ------------------------------------------------------------------
toy = make_toy()
check("練習用データの行数", len(toy), 6)
check("dt.year", toy["ordered_at"].dt.year.tolist(), [2026] * 6)
check("dt.month", toy["ordered_at"].dt.month.tolist(), [8] * 6)
check("dt.day", toy["ordered_at"].dt.day.tolist(), [24, 24, 25, 27, 30, 31])
check("dt.hour", toy["ordered_at"].dt.hour.tolist(), [9, 20, 11, 8, 22, 7])
check("dt.dayofweek（月曜 = 0）", toy["ordered_at"].dt.dayofweek.tolist(), [0, 0, 1, 3, 6, 0])
check(
    "曜日を日本語に直した結果",
    [WEEKDAY_JA[i] for i in toy["ordered_at"].dt.dayofweek],
    ["月", "月", "火", "木", "日", "月"],
)
check("dt.normalize() で時刻が落ちること", str(toy["ordered_at"].dt.normalize().iloc[0]), "2026-08-24 00:00:00")
check("dt.to_period('M') の表示", str(toy["ordered_at"].dt.to_period("M").iloc[0]), "2026-08")

# ------------------------------------------------------------------
# 4. resample（練習用データ）
# ------------------------------------------------------------------
toy_series = toy.set_index("ordered_at")["amount"]
toy_daily = toy_series.resample("D").sum()
check("日次の行数（空の日も作られる）", len(toy_daily), 8)
check("日次の合計", toy_daily.tolist(), [3000, 1500, 0, 3000, 0, 0, 2500, 4000])
check("日次の件数", toy_series.resample("D").size().tolist(), [2, 1, 0, 1, 0, 0, 1, 1])
check("空の日は sum なら 0", int(toy_daily.loc["2026-08-26"]), 0)
check("空の日は mean なら NaN", bool(pd.isna(toy_series.resample("D").mean().loc["2026-08-26"])), True)

toy_weekly = toy_series.resample("W").sum()
check("週次（日曜終わり）の行数", len(toy_weekly), 2)
check("週次のラベル", [f"{ts:%Y-%m-%d}" for ts in toy_weekly.index], ["2026-08-30", "2026-09-06"])
check("週次の合計", toy_weekly.tolist(), [10000, 4000])

toy_monthly = toy_series.resample("ME").sum()
check("月次の行数", len(toy_monthly), 1)
check("月次のラベル（月末）", f"{toy_monthly.index[0]:%Y-%m-%d}", "2026-08-31")
check("月次の合計", toy_monthly.tolist(), [14000])

try:
    toy_series.resample("M").sum()
    m_alias = "（例外なし）"
except Exception as exc:  # noqa: BLE001 - 型が変わっても「使えない」ことだけを確認する
    m_alias = type(exc).__name__
print(f'---  resample("M") の結果: {m_alias}')
check('resample("M") が pandas 3.0 では使えないこと', m_alias != "（例外なし）", True)

try:
    toy["amount"].resample("D").sum()  # インデックスが RangeIndex のまま
    index_error = ""
except TypeError as exc:
    index_error = str(exc)
print(f"---  RangeIndex で resample したときのメッセージ: {index_error}")
check("DatetimeIndex でないと resample できないこと", "Only valid with DatetimeIndex" in index_error, True)

# ------------------------------------------------------------------
# 5. rolling（練習用データ）
# ------------------------------------------------------------------
window3 = toy_daily.rolling(3).mean()
check("rolling(3) で NaN になる行数", int(window3.isna().sum()), 2)
check(
    "rolling(3) の値（小数 1 桁）",
    [None if pd.isna(v) else round(float(v), 1) for v in window3],
    [None, None, 1500.0, 1500.0, 1000.0, 1000.0, 833.3, 2166.7],
)
window3_min1 = toy_daily.rolling(3, min_periods=1).mean()
check(
    "min_periods=1 の先頭 2 行",
    [round(float(v), 1) for v in window3_min1.iloc[:2]],
    [3000.0, 2250.0],
)
centered = toy_daily.rolling(3, center=True).mean()
check("center=True で NaN になる位置", [i for i, v in enumerate(centered) if pd.isna(v)], [0, 7])
check("center=True の 2 行目", round(float(centered.iloc[1]), 1), 1500.0)
check("center=True の 7 行目", round(float(centered.iloc[6]), 1), 2166.7)

# ------------------------------------------------------------------
# 6. 実データの resample（売上）
# ------------------------------------------------------------------
valid = load_valid_orders()
check("有効注文の件数", len(valid), 57869)
series = valid.set_index("ordered_at")["amount"].sort_index()
check("売上合計（合計してから整数にする）", int(round(series.sum())), 127104442)

daily_amount = series.resample("D").sum()
weekly_amount = series.resample("W").sum()
monthly = series.resample("ME").sum().round().astype("int64")
check("日次の行数", len(daily_amount), 967)
check("週次の行数", len(weekly_amount), 139)
check("月次の行数", len(monthly), 33)
check("週次の最初のラベル", f"{weekly_amount.index[0]:%Y-%m-%d}", "2024-01-14")
check("週次の最後のラベル", f"{weekly_amount.index[-1]:%Y-%m-%d}", "2026-09-06")
check("最初の月", f"{monthly.index[0]:%Y-%m}", "2024-01")
check("両端を除いた完全な月の数", len(monthly.iloc[1:-1]), 31)
check("dt.month で数えた箱の数", int(valid["ordered_at"].dt.month.nunique()), 12)
check("dt.to_period('M') で数えた箱の数", int(valid["ordered_at"].dt.to_period("M").nunique()), 33)
check("月次売上が最大の月", f"{monthly.idxmax():%Y-%m}", "2026-08")
check_yen("月次売上の最大", int(monthly.max()), 18281617)
check("月次売上が最小の月", f"{monthly.idxmin():%Y-%m}", "2024-01")
check_yen("月次売上の最小", int(monthly.min()), 64583)
check("月次の最後の月", f"{monthly.index[-1]:%Y-%m}", "2026-09")
check_yen("末尾の月（2026-09）の売上", int(monthly.iloc[-1]), 84496)
last_month = valid.loc[valid["ordered_at"] >= "2026-09-01", "ordered_at"]
check("末尾の月に含まれる日数", int(last_month.dt.normalize().nunique()), 1)

# ------------------------------------------------------------------
# 7. 実データの日次注文数・年別・曜日別
# ------------------------------------------------------------------
daily_orders = valid.set_index("ordered_at").sort_index().resample("D").size()
check("日次注文数の行数", len(daily_orders), 967)
check_close("日次注文数の平均", float(daily_orders.mean()), 59.84)
check("日次注文数の最大", int(daily_orders.max()), 429)
check("7 日移動平均で NaN になる行数", int(daily_orders.rolling(7).mean().isna().sum()), 6)
check("28 日移動平均で NaN になる行数", int(daily_orders.rolling(28).mean().isna().sum()), 27)
check(
    "min_periods=1 なら NaN が無いこと",
    int(daily_orders.rolling(7, min_periods=1).mean().isna().sum()),
    0,
)

by_year = daily_orders.groupby(daily_orders.index.year).agg(["size", "sum", "mean"])
check("年ごとの日数", by_year["size"].tolist(), [358, 365, 244])
check("年別の有効注文件数", by_year["sum"].tolist(), [4842, 18622, 34405])
check_close("2024 年の 1 日平均", float(by_year.loc[2024, "mean"]), 13.53, tol=0.01)
check_close("2025 年の 1 日平均", float(by_year.loc[2025, "mean"]), 51.02, tol=0.01)
check_close("2026 年の 1 日平均", float(by_year.loc[2026, "mean"]), 141.00, tol=0.01)

by_dow = valid["ordered_at"].dt.dayofweek.value_counts().sort_index()
check("曜日の種類", len(by_dow), 7)
check("曜日別注文数の合計", int(by_dow.sum()), 57869)
check("曜日別注文数の最小", int(by_dow.min()), 8106)
check("曜日別注文数の最大", int(by_dow.max()), 8496)
check("曜日別注文数の最大と最小の差", int(by_dow.max() - by_dow.min()), 390)
check("曜日別注文数の平均（四捨五入）", round(float(by_dow.mean())), 8267)
check("差が平均に占める割合", f"{(by_dow.max() - by_dow.min()) / by_dow.mean():.1%}", "4.7%")

# ------------------------------------------------------------------
# 8. 基準日を固定した経過日数とアクティブ顧客
# ------------------------------------------------------------------
last_order = valid.groupby("customer_id")["ordered_at"].max()
recency = (REFERENCE_DATE - last_order).dt.days
check("有効注文のある顧客数", len(recency), 7629)
check_close("経過日数の平均", float(recency.mean()), 88.0, tol=0.05)
check("経過日数の中央値", int(recency.median()), 39)
check("経過日数の最大", int(recency.max()), 962)
print(f"---  90 日以内（<= 90）: {int((recency <= 90).sum())} 人 / 90 日未満（< 90）: {int((recency < 90).sum())} 人")
active = int((recency <= 90).sum())
check("アクティブ顧客数（90 日以内）", active, 5341)
check("有効注文のある顧客を分母にした比率", f"{active / len(recency):.2%}", "70.01%")
check("全顧客 8,000 人を分母にした比率", f"{active / 8000:.2%}", "66.76%")
check("アクティブ比率（小数第 4 位）", round(active / len(recency), 4), 0.7001)
check("基準日が固定されていること", str(REFERENCE_DATE), "2026-09-01 00:00:00")

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("セッション 7 のすべての検証に成功しました。")
