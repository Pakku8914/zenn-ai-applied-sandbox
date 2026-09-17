"""問題6 の解答: 4 ファイルを「型の仕様書」に従って読み込み、読み込み結果を自己検査する。

使い方:
    docker compose exec lab python src/session03/q6_load_all.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# 型の仕様書：どのファイルのどの列をどう読むかを 1 か所に集める
SPECS: dict[str, dict[str, object]] = {
    "books": {
        "dtype": {
            "book_id": "str", "category": "str",
            "price": "int64", "pages": "int64", "published_year": "int64",
        },
        "parse_dates": [],
        "rows": 600,
    },
    "customers": {
        "dtype": {"customer_id": "str", "birth_year": "int64", "region": "str", "channel": "str"},
        "parse_dates": ["signup_date"],
        "rows": 8000,
    },
    "orders": {
        "dtype": {
            "order_id": "str", "customer_id": "str", "book_id": "str",
            "quantity": "int64", "unit_price": "int64",
            "discount_rate": "float64", "is_canceled": "int64",
        },
        "parse_dates": ["ordered_at"],
        "rows": 60061,
    },
    "reviews": {
        "dtype": {
            "review_id": "str", "order_id": "str", "customer_id": "str", "book_id": "str",
            "rating": "float64",  # 欠損があるので整数にはできない
            "body_length": "int64",
        },
        "parse_dates": ["reviewed_at"],
        "rows": 14467,
    },
}


def load_all(data_dir: Path = DATA_DIR) -> dict[str, pd.DataFrame]:
    """仕様書に従って 4 ファイルを読み込み、名前をキーにした辞書で返す。"""
    frames: dict[str, pd.DataFrame] = {}
    for name, spec in SPECS.items():
        frames[name] = pd.read_csv(
            data_dir / f"{name}.csv",
            dtype=spec["dtype"],
            parse_dates=spec["parse_dates"],
        )
    return frames


def expected_dtypes(name: str) -> dict[str, str]:
    """仕様書から「列名 -> 期待する dtype」の対応を組み立てる。"""
    spec = SPECS[name]
    expected = dict(spec["dtype"])
    for column in spec["parse_dates"]:
        expected[column] = "datetime64[us]"
    return expected


def main() -> None:
    frames = load_all()

    print("■ 読み込み結果")
    for name, df in frames.items():
        print(f"{name:<10} : {len(df):>6} 行 × {df.shape[1]} 列")

    print("\n■ 行数の検査")
    row_errors = [name for name, df in frames.items() if len(df) != SPECS[name]["rows"]]
    print(f"行数が仕様と違うファイル : {row_errors if row_errors else 'なし'}")

    print("\n■ 型の検査（仕様と一致しない列だけ表示）")
    checked = 0
    dtype_errors: list[str] = []
    for name, df in frames.items():
        for column, expected in expected_dtypes(name).items():
            checked += 1
            actual = str(df[column].dtype)
            if actual != expected:
                dtype_errors.append(f"{name}.{column}: {actual}（期待は {expected}）")
    for message in dtype_errors:
        print(f"NG   {message}")
    if not dtype_errors:
        print("（不一致はありません）")
    print(f"検査した列 : {checked} 列")

    mb = frames["orders"].memory_usage(deep=True).sum() / 1024**2
    print(f"\norders のメモリ使用量（deep=True）: {mb:.2f} MB")

    if row_errors or dtype_errors:
        raise SystemExit(1)
    print("\nすべての検査に成功しました。")


if __name__ == "__main__":
    main()
