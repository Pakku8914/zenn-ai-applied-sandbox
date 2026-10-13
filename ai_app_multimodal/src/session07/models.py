"""レシートから読み取る形（セッション7）。画像でも PDF でも、出力はこの1つのモデルにそろえる。

Pydantic に置くのは「これが崩れていたら後ろの処理が動かない」形だけ（型・必須・空でない）。
金額の範囲や合計の一致・日付の中身は、整合性検査（checks.py）で確かめて人に回す。
"""

from __future__ import annotations

from typing import Annotated

from anthropic import transform_schema
from pydantic import BaseModel, Field, StringConstraints

Text40 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class ReceiptItem(BaseModel):
    name: Text40 = Field(description="品名（レシートの表記のまま）")
    quantity: int = Field(description="個数（書かれていなければ1）")
    price: int = Field(description="その行の金額（円の整数。個数を掛けたあとの額）")


class ReceiptRead(BaseModel):
    store: Text40 = Field(description="店名")
    purchased_at: str = Field(description="購入日（YYYY-MM-DD）")
    items: list[ReceiptItem] = Field(min_length=1, description="購入品（レシートの上から順に）")
    total: int = Field(description="合計金額（円の整数）")


# API が受け付ける形に変換したスキーマ。画像でも PDF でも同じものを ChatRequest.output_schema に渡す
RECEIPT_SCHEMA = transform_schema(ReceiptRead)
