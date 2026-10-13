"""個人情報の棚卸し（付帯情報の検査）と、保持期限つきの台帳（セッション13）。

- image_findings / pdf_findings … ファイルの付帯情報（EXIF・PDF のメタデータ）に個人情報の手がかりがあるかを調べる。
  画素や本文の中身（レシートに印字された店名など）は見ない＝見つけられない
- PersonalStore … アップロード・文書・レシート・音声を、持ち主と期限つきで1か所に記録する。
  期限の判定は注入した時計で行う。期限を過ぎたものは get() で「無い」と扱い、実際の削除は sweep() がまとめて行う
"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

from kondate.clock import Clock

# ---- 本章で決めた保持期限（章をまたいで変えない） ----
RETENTION = {
    "upload": timedelta(hours=24),    # 受け取ったファイルそのもの（写真の位置情報（GPS）が残っている）
    "document": timedelta(days=30),   # 登録した PDF（質問に使い続ける）
    "receipt": timedelta(days=30),    # 読み取ったレシート（店名・購入日時・購入品）
    "voice": timedelta(days=7),       # 同意したときだけ保存する発話の音声
}
# 種別 → DELETE /api/me/data の応答のキー（usage は UsageLog の側で数える）
KEYS = {"upload": "uploads", "document": "documents", "receipt": "receipts", "voice": "voice"}

MAKE, MODEL, DATETIME = 0x010F, 0x0110, 0x0132
EXIF_IFD, GPS_IFD, DATETIME_ORIGINAL = 0x8769, 0x8825, 0x9003


# ---------------------------------------------------------------- 棚卸し（付帯情報の検査）

def image_findings(raw: bytes) -> dict[str, bool]:
    """画像の EXIF に、位置・機種・撮影日時が入っているか。"""
    with Image.open(io.BytesIO(raw)) as img:
        exif = img.getexif()
        return {
            "exif": len(exif) > 0,
            "gps": len(exif.get_ifd(GPS_IFD)) > 0,                  # 位置は IFD0 ではなく GPS IFD に入っている
            "device": MAKE in exif or MODEL in exif,
            "taken_at": DATETIME in exif or DATETIME_ORIGINAL in exif.get_ifd(EXIF_IFD),
        }


def pdf_findings(raw: bytes) -> dict[str, bool]:
    """PDF の文書情報（メタデータ）に、タイトル・作成者・作成ソフトが入っているか。"""
    meta = PdfReader(io.BytesIO(raw)).metadata or {}
    return {
        "title": bool(meta.get("/Title")),
        "author": bool(meta.get("/Author")),
        "creator": bool(meta.get("/Creator")),
    }


# ---------------------------------------------------------------- 保持期限つきの台帳

@dataclass
class Held:
    kind: str                       # upload / document / receipt / voice
    item_id: str                    # up_… / doc_… / rcp_… / vc_…
    user_id: str
    expires_at: datetime
    path: Path | None = None        # ファイルに保存したもの（upload・voice）
    data: object = field(default=None, repr=False)  # メモリに持つもの。repr に出さない（print やログに中身が出ない）


class PersonalStore:
    """利用者の個人データの台帳（本章の簡易版。メモリに持つので、プロセスを再起動すると台帳は消える）。"""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self._items: dict[str, Held] = {}

    def add(self, kind: str, item_id: str, user_id: str, *, path: Path | None = None, data: object = None) -> Held:
        held = Held(kind, item_id, user_id, self.clock.now() + RETENTION[kind], path, data)
        self._items[item_id] = held
        return held

    def get(self, user_id: str, item_id: str) -> Held | None:
        """持ち主が一致し、期限内のものだけを返す。掃除がまだでも、期限を過ぎたものは「無い」と扱う。"""
        held = self._items.get(item_id)
        if held is None or held.user_id != user_id or self.clock.now() >= held.expires_at:
            return None
        return held

    def of_user(self, user_id: str) -> list[Held]:
        return [h for h in self._items.values() if h.user_id == user_id]

    def count(self, user_id: str) -> dict[str, int]:
        counts = dict.fromkeys(KEYS.values(), 0)
        for held in self.of_user(user_id):
            counts[KEYS[held.kind]] += 1
        return counts

    def paths(self) -> set[Path]:
        """台帳が知っているファイルの一覧（練習問題7の孤児ファイルの掃除で使う）。"""
        return {h.path for h in self._items.values() if h.path is not None}

    def sweep(self) -> dict[str, int]:
        """期限を過ぎたものを消し、種別ごとの件数を返す。"""
        now = self.clock.now()
        return self._remove(lambda held: now >= held.expires_at)

    def delete_user(self, user_id: str) -> dict[str, int]:
        """その利用者のものをすべて消し、種別ごとの件数を返す。2回目は 0 件になる。"""
        return self._remove(lambda held: held.user_id == user_id)

    def _remove(self, match: Callable[[Held], bool]) -> dict[str, int]:
        removed = dict.fromkeys(KEYS.values(), 0)
        for held in [h for h in self._items.values() if match(h)]:
            if held.path is not None:
                held.path.unlink(missing_ok=True)  # ファイルを先に消す。失敗したら台帳に残り、次の掃除でやり直せる
            del self._items[held.item_id]
            removed[KEYS[held.kind]] += 1
        return removed
