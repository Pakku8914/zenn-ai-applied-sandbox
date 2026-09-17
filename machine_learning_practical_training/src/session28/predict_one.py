"""1 件だけの推論と、入力の検証（本文 4 節）。

学習のときは何万行もまとめて渡しますが、運用では 1 件だけ来ます。
そして 1 件だけ来るときは、**列が足りない・型が違う・ありえない値**が普通に混ざります。

使い方:
    docker compose exec lab python src/session28/predict_one.py
"""

from __future__ import annotations

from common import (
    MODEL_PATH,
    ensure_model,
    predict_one,
    record_digest,
    sample_record,
    unknown_keys,
    validate_record,
)


def broken_records(record: dict) -> list[tuple[str, dict]]:
    """わざと壊した入力を 5 通り作る（検証の順番どおりに並べる）。"""
    missing = {name: value for name, value in record.items() if name != "recency"}
    return [
        ("列が足りない（recency を消した）", missing),
        ("欠損を許さない列が欠損（n_orders = None）", {**record, "n_orders": None}),
        ("数値のはずが文字列（n_orders = '7'）", {**record, "n_orders": "7"}),
        ("範囲から外れている（mean_discount = 1.5）", {**record, "mean_discount": 1.5}),
        ("学習時になかったカテゴリ（channel = 'テレビCM'）", {**record, "channel": "テレビCM"}),
    ]


def try_predict(model, record: dict) -> tuple[float | None, str]:
    """推論を試し、落ちたら例外の型名と文面を返す（落ちること自体を確かめるため）。"""
    try:
        return predict_one(model, record), ""
    except ValueError as exc:
        return None, f"{type(exc).__name__}: {exc}"


def main() -> None:
    model, meta, differences = ensure_model(MODEL_PATH)
    print("■ 1. 保存したモデルを読み込む")
    print(f"読み込み: outputs/{MODEL_PATH.name}（バージョンの食い違い {len(differences)} 件）")
    print(f"受け取る列: 数値 {len(meta['numeric'])} 列 + カテゴリ {len(meta['categorical'])} 列")
    print()

    record = sample_record()
    proba = predict_one(model, record)
    print("■ 2. 1 件だけ推論する")
    print(f"入力の要点: {record_digest(record)}")
    print(f"（このほかに {len(record) - 3} 列が同じ dict に入っています）")
    print(f"再購入確率: {proba:.4f}")
    print()

    print("■ 3. おかしな入力は、predict の前に落とす")
    for index, (label, broken) in enumerate(broken_records(record), start=1):
        _, message = try_predict(model, broken)
        print(f"[{index}] {label}")
        print(f"    {message}")
    print()

    print("■ 4. 欠損を許す列は、欠損のまま受け取る")
    nullable, _ = try_predict(model, {**record, "region": None})
    print(f"region を None にしても推論できたか: {nullable is not None}")
    print("（学習時に最頻値で埋める前処理が Pipeline に入っているため）")
    _, message = try_predict(model, {**record, "channel": None})
    print(f"channel を None にすると落ちる: {message}")
    print()

    print("■ 5. モデルが使わないキーは捨てる")
    with_extra = {**record, "customer_id": "C00001"}
    print(f"余分なキー: {unknown_keys(with_extra)}")
    print(f"検証後に残る列の数: {len(validate_record(with_extra))}")
    print()
    print("判断: 検証を通したあとは、モデルには必ず 11 列そろった 1 行だけが渡ります。")
    print("      『落ちてほしいところで落ちる』のが、いちばん安い事故対策です。")


if __name__ == "__main__":
    main()
