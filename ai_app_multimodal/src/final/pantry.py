"""声の相談に添える「手元にある食材」（最終プロジェクトで足した部品）。

写真・レシートから読み取った名前のうち、食材辞書（data/recipes.json の食材名）の語だけを使う。
読み取った文字列をそのまま LLM の system に入れると、写真やレシートに書かれた文が「指示」として読まれる
おそれがある（プロンプトインジェクション）。辞書の語に置き換えておけば、入るのは決まった語だけになる。

置き場所は台帳（PersonalStore）。新しい種別は作らない。
- 冷蔵庫の写真：種別 upload（24時間）に FridgeNote を載せる（写真そのものは保存しない）
- レシート：取り込んだレシート（種別 receipt・30日）の pantry に持たせる
どちらも DELETE /api/me/data で消え、期限が来れば見えなくなる。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.final.models import ReceiptRead
from src.final.privacy import PersonalStore
from src.final.review import ingredient_dictionary

PANTRY_MAX = 20


@dataclass(frozen=True)
class FridgeNote:
    names: tuple[str, ...]


def names_from_scan(value: dict) -> tuple[str, ...]:
    """冷蔵庫の読み取り結果（応答の本体）から、要確認の印が付いていない食材の名前だけを取る。
    unknown_name の印が付いていない＝辞書にある名前なので、そのまま使える。"""
    flagged = {issue["index"] for issue in value["issues"]}
    return tuple(dict.fromkeys(ing["name"] for i, ing in enumerate(value["ingredients"]) if i not in flagged))


def dictionary_name(text: str) -> str | None:
    """text に含まれる辞書の食材名のうち、いちばん長いもの（「卵（10個入り）」→「卵」）。無ければ None。"""
    found = [name for name in ingredient_dictionary() if name in text]
    return max(found, key=lambda name: (len(name), name)) if found else None


def names_from_receipt(read: ReceiptRead) -> tuple[str, ...]:
    return tuple(dict.fromkeys(n for item in read.items if (n := dictionary_name(item.name)) is not None))


def pantry_names(store: PersonalStore, user_id: str) -> list[str]:
    """期限内の写真・レシートから集めた食材名（古い順・重複なし・最大 PANTRY_MAX 件）。"""
    names: list[str] = []
    for held in store.live(user_id):
        if held.kind == "upload" and isinstance(held.data, FridgeNote):
            names += held.data.names
        elif held.kind == "receipt":
            names += held.data.pantry
    return list(dict.fromkeys(names))[:PANTRY_MAX]


def system_with_pantry(base: str, names: list[str]) -> str:
    if not names:
        return base
    return base + f"利用者の手元にある食材：{'、'.join(names)}。献立を提案するときは、なるべくこれらを使ってください。"
