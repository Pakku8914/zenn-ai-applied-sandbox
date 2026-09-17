"""セッション 3 の検証スクリプト。

本文・練習問題・解答に載せた「型」と「数値」を、その場で再計算して照合します。
期待値と一致しない場合は非 0 で終了します（許容誤差 0.005）。

使い方:
    docker compose exec lab python src/session03/verify_03.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from q6_load_all import expected_dtypes, load_all

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
TOLERANCE = 0.005

failures: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    ok = actual == expected
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual}")
    if not ok:
        print(f"     期待値: {expected}")
        failures.append(label)


def check_close(label: str, actual: float, expected: float) -> None:
    ok = abs(actual - expected) <= TOLERANCE
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual:.4f}")
    if not ok:
        print(f"     期待値: {expected:.4f} ± {TOLERANCE}")
        failures.append(label)


def raised(func) -> str:
    """func を呼び、発生した例外の名前（発生しなければ '例外なし'）を返す。"""
    try:
        func()
    except Exception as error:  # noqa: BLE001 - 何が起きたかを文字列で比べたい
        return type(error).__name__
    return "例外なし"


def raises_value_error(func) -> bool:
    """func が ValueError（その派生クラスを含む）を出すかどうかを返す。"""
    try:
        func()
    except ValueError:
        return True
    except Exception:  # noqa: BLE001 - 想定と違う例外なら False として失敗させる
        return False
    return False


check("pandas のバージョン", pd.__version__, "3.0.5")

missing = [name for name in ("books", "customers", "orders", "reviews") if not (DATA_DIR / f"{name}.csv").exists()]
if missing:
    print(f"NG   データが未生成です: {missing}")
    print("     先に `python tools/make_datasets.py` を実行してください。")
    raise SystemExit(1)

# ---------------------------------------------------------------- 1. 行数と形
books = pd.read_csv(DATA_DIR / "books.csv")
customers = pd.read_csv(
    DATA_DIR / "customers.csv",
    dtype={"customer_id": "str", "birth_year": "int64", "region": "str", "channel": "str"},
    parse_dates=["signup_date"],
)
orders_raw = pd.read_csv(DATA_DIR / "orders.csv")
orders = pd.read_csv(DATA_DIR / "orders.csv", parse_dates=["ordered_at"])
reviews = pd.read_csv(DATA_DIR / "reviews.csv", parse_dates=["reviewed_at"])

check("books.csv の行数", len(books), 600)
check("books.csv の列数", books.shape[1], 5)
check("customers.csv の行数", len(customers), 8000)
check("orders.csv の行数", len(orders), 60061)
check("reviews.csv の行数", len(reviews), 14467)
check("books の列名", list(books.columns), ["book_id", "category", "price", "pages", "published_year"])

# ---------------------------------------------- 2. pandas 3.0 の既定の型（2.x との違い）
check("books.book_id の dtype", str(books["book_id"].dtype), "str")
check("books.category の dtype", str(books["category"].dtype), "str")
check("books.price の dtype", str(books["price"].dtype), "int64")
check("books.pages の dtype", str(books["pages"].dtype), "int64")
check("books.published_year の dtype", str(books["published_year"].dtype), "int64")
check("customers.signup_date の dtype", str(customers["signup_date"].dtype), "datetime64[us]")
check("customers.birth_year の dtype", str(customers["birth_year"].dtype), "int64")
check("customers.region の dtype", str(customers["region"].dtype), "str")
check("customers.channel の dtype", str(customers["channel"].dtype), "str")
check("parse_dates なしの ordered_at の dtype", str(orders_raw["ordered_at"].dtype), "str")
check("parse_dates ありの ordered_at の dtype", str(orders["ordered_at"].dtype), "datetime64[us]")
check("ordered_at が 2024〜2026 年に収まる", bool(orders["ordered_at"].dt.year.between(2024, 2026).all()), True)

# ------------------------------------------------- 3. Series・DataFrame・インデックス
price_series = pd.Series([1410, 3200, 880], index=["B0001", "B0002", "B0003"], name="price")
mini = pd.DataFrame({"price": [1410, 3200, 880], "pages": [240, 520, 180]}, index=["B0001", "B0002", "B0003"])
check("Series をラベルで引く", int(price_series["B0002"]), 3200)
check("Series を位置で引く", int(price_series.iloc[1]), 3200)
check("Series の name", price_series.name, "price")
check("1 列だけ取り出した型", type(mini["price"]).__name__, "Series")
check("二重の角かっこで取り出した型", type(mini[["price"]]).__name__, "DataFrame")
check("読み込み直後のインデックスの型", type(books.index).__name__, "RangeIndex")
check("先頭 3 つのインデックスラベル", books.index[:3].tolist(), [0, 1, 2])

indexed = books.set_index("book_id")
check("set_index 後のインデックス名", indexed.index.name, "book_id")
check("set_index 後の列数", indexed.shape[1], 4)
check("reset_index 後の列数", indexed.reset_index().shape[1], 5)
check("B0001 の price", int(indexed.loc["B0001", "price"]), 1410)
check("set_index は元の books を変えない", "book_id" in books.columns, True)

# ------------------------------------------------------- 4. info・describe で全体像
described = books["price"].describe()
check("books.price の count", int(described["count"]), 600)
check_close("books.price の mean", float(described["mean"]), 1872.40)
check_close("books.price の std", float(described["std"]), 949.01)
check_close("books.price の min", float(described["min"]), 540.0)
check_close("books.price の 25%", float(described["25%"]), 1110.0)
check_close("books.price の 50%", float(described["50%"]), 1600.0)
check_close("books.price の 75%", float(described["75%"]), 2472.5)
check_close("books.price の max", float(described["max"]), 4820.0)
check("books に欠損のある列", [c for c in books.columns if bool(books[c].isna().any())], [])
check("books の str 列", [c for c in books.columns if str(books[c].dtype) == "str"], ["book_id", "category"])
check(
    "books の int64 列",
    [c for c in books.columns if str(books[c].dtype) == "int64"],
    ["price", "pages", "published_year"],
)

check("customers.region の欠損数", int(customers["region"].isna().sum()), 392)
check("customers.region の非欠損数", int(customers["region"].notna().sum()), 7608)
check(
    "customers の日時列",
    [c for c in customers.columns if str(customers[c].dtype).startswith("datetime64")],
    ["signup_date"],
)

rating = reviews["rating"].describe()
check("reviews.rating の dtype", str(reviews["rating"].dtype), "float64")
check("reviews.rating の describe の count", int(rating["count"]), 14169)
check_close("reviews.rating の mean", float(rating["mean"]), 3.9725)
check_close("reviews.rating の std", float(rating["std"]), 0.5914)
check_close("reviews.rating の min", float(rating["min"]), 1.0)
check_close("reviews.rating の 25%", float(rating["25%"]), 4.0)
check_close("reviews.rating の 50%", float(rating["50%"]), 4.0)
check_close("reviews.rating の 75%", float(rating["75%"]), 4.0)
check_close("reviews.rating の max", float(rating["max"]), 5.0)
check("行数 - count = 欠損数", len(reviews) - int(rating["count"]), 298)
check("reviews.rating の isna().sum()", int(reviews["rating"].isna().sum()), 298)
check_close("reviews.rating の mean()", float(reviews["rating"].mean()), 3.9725)
check_close("reviews.rating の dropna().mean()", float(reviews["rating"].dropna().mean()), 3.9725)
check(
    "欠損を含む rating を int64 にすると ValueError",
    raises_value_error(lambda: reviews["rating"].astype("int64")),
    True,
)
nullable_rating = reviews["rating"].astype("Int64")
check("rating を Int64 にした dtype", str(nullable_rating.dtype), "Int64")
check("Int64 にしても欠損数は変わらない", int(nullable_rating.isna().sum()), 298)

# ------------------------------------------------------------- 5. メモリ使用量
check_close("orders のメモリ使用量（MB）", orders.memory_usage(deep=True).sum() / 1024**2, 11.74)

# --------------------------------------------------- 6. 型が違うときに起きる不具合
bad = pd.read_csv(DATA_DIR / "books.csv", dtype={"price": "str"})
check("文字列として読んだ price の dtype", str(bad["price"].dtype), "str")
check("文字列として読んだ 1 行目の price", bad["price"].iloc[0], "1410")
check("文字列の price を 2 倍すると", (bad["price"] * 2).iloc[0], "14101410")
check("文字列の price に mean() を呼ぶと", raised(lambda: bad["price"].mean()), "TypeError")
check("astype('int64') 後の dtype", str(bad["price"].astype("int64").dtype), "int64")
check("astype('int64') 後に 2 倍すると", int((bad["price"].astype("int64") * 2).iloc[0]), 2820)
check("to_numeric 後の dtype", str(pd.to_numeric(bad["price"]).dtype), "int64")

sample = pd.Series(["990", "1000", "540"], dtype="str")
check("文字列のまま並べ替えると", sample.sort_values().tolist(), ["1000", "540", "990"])
check("数値に直して並べ替えると", pd.to_numeric(sample).sort_values().tolist(), [540, 990, 1000])

messy = pd.Series(["1410", "3,200", "", "880"], dtype="str")
coerced = pd.to_numeric(messy, errors="coerce")
check("coerce で欠損になる位置", coerced.isna().tolist(), [False, True, True, False])
check("coerce で残った値", coerced.dropna().tolist(), [1410.0, 880.0])
check("errors 指定なしの to_numeric", raises_value_error(lambda: pd.to_numeric(messy)), True)

check("文字列の日時に .dt を使うと", raised(lambda: orders_raw["ordered_at"].dt.year), "AttributeError")
repaired = pd.to_datetime(orders_raw["ordered_at"])
check("to_datetime 後は .dt が使える", bool(repaired.dt.year.between(2024, 2026).all()), True)

# ------------------------------------------- 7. 問題6 の解答（型の仕様書に沿った読み込み）
frames = load_all()
check("load_all が返すキー", sorted(frames), ["books", "customers", "orders", "reviews"])
dtype_errors: list[str] = []
checked_columns = 0
for name, df in frames.items():
    for column, expected in expected_dtypes(name).items():
        checked_columns += 1
        if str(df[column].dtype) != expected:
            dtype_errors.append(f"{name}.{column}={df[column].dtype}")
check("仕様書で検査した列数", checked_columns, 25)
check("仕様と一致しない列", dtype_errors, [])
check(
    "load_all の行数",
    {name: len(df) for name, df in frames.items()},
    {"books": 600, "customers": 8000, "orders": 60061, "reviews": 14467},
)
check_close(
    "load_all で読んだ orders のメモリ使用量（MB）",
    frames["orders"].memory_usage(deep=True).sum() / 1024**2,
    11.74,
)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("すべての検証に成功しました。")
