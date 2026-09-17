"""問題3 の解答: 1 件推論の関数に入力の検証を入れる。

使い方:
    docker compose exec lab python src/session28/q3_validate_input.py
"""

from __future__ import annotations

from common import (
    FEATURES,
    MODEL_PATH,
    build_meta,
    load_model,
    predict_one,
    record_digest,
    repeat_bundle,
    sample_record,
    save_model,
    validate_record,
)


def broken_cases(record: dict) -> list[tuple[str, object]]:
    """検証で落ちてほしい入力を 6 通り作る（落ちる順番に並べる）。"""
    short = {name: value for name, value in record.items() if name not in ("recency", "age")}
    return [
        ("dict ではない（list を渡した）", list(record.values())),
        ("必須の列が足りない（recency と age を消した）", short),
        ("欠損を許さない列が欠損（total_amount = NaN）", {**record, "total_amount": float("nan")}),
        ("数値のはずが文字列（n_orders = '7'）", {**record, "n_orders": "7"}),
        ("範囲から外れている（age = 200）", {**record, "age": 200}),
        ("学習時になかったカテゴリ（region = '沖縄'）", {**record, "region": "沖縄"}),
    ]


def try_predict(model, record: object) -> tuple[float | None, str]:
    """推論を試し、落ちたら例外の型名と文面を返す。"""
    try:
        return predict_one(model, record), ""
    except ValueError as exc:
        return None, f"{type(exc).__name__}: {exc}"


def analyze() -> dict:
    """正常系 1 件と異常系 6 件、欠損を許す列の扱いをまとめる。"""
    bundle = repeat_bundle()
    save_model(bundle["model"], build_meta(bundle), MODEL_PATH)
    model, _, _ = load_model(MODEL_PATH)

    record = sample_record()
    clean = validate_record(record)
    proba = predict_one(model, record)

    messages = []
    for label, broken in broken_cases(record):
        _, message = try_predict(model, broken)
        messages.append({"label": label, "message": message})

    region_missing, _ = try_predict(model, {**record, "region": None})
    _, channel_message = try_predict(model, {**record, "channel": None})
    return {
        "record": record,
        "proba": proba,
        "n_clean": len(clean),
        "same_order": list(clean) == FEATURES,
        "messages": messages,
        "n_failed": sum(1 for row in messages if row["message"]),
        "region_missing_ok": region_missing is not None,
        "channel_message": channel_message,
    }


def main() -> None:
    result = analyze()

    print("■ 1. 正常な 1 件")
    print(f"入力の要点: {record_digest(result['record'])}")
    print(f"再購入確率: {result['proba']:.4f}")
    print(f"検証後の列数: {result['n_clean']}（学習時と同じ順番: {result['same_order']}）")
    print()

    print(f"■ 2. 落ちてほしい入力（{len(result['messages'])} 通り）")
    for index, row in enumerate(result["messages"], start=1):
        print(f"[{index}] {row['label']}")
        print(f"    {row['message']}")
    print(f"落ちた件数: {result['n_failed']} / {len(result['messages'])} 件")
    print()

    print("■ 3. 欠損を許す列と、許さない列")
    print(f"region = None → 推論できた: {result['region_missing_ok']}")
    print(f"channel = None → {result['channel_message']}")
    print()

    print("■ 4. なぜ predict の前に落とすのか（3 文）")
    print("列が足りなければ scikit-learn も例外を出しますが、文面はモデルの都合で書かれています。")
    print("範囲外の値や未知のカテゴリは例外にならず、もっともらしい確率が返ってきます。")
    print("自分で検証しておけば、どこがおかしいかを入力の言葉で説明できます。")


if __name__ == "__main__":
    main()
