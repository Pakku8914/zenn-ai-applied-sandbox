"""保持期限つきの台帳（セッション13の privacy.py から PersonalStore の部分を写したもの）。

最終プロジェクトで足したのは live() だけ。同じ利用者の「期限内のもの」を種別で絞って並べる
（文書・レシートの二重登録の確認と、声の相談に添える食材名の取り出しに使う）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from kondate.clock import Clock

RETENTION = {
    "upload": timedelta(hours=24),    # 受け取ったファイル・冷蔵庫の写真から読み取った食材名
    "document": timedelta(days=30),
    "receipt": timedelta(days=30),
    "voice": timedelta(days=7),
}
KEYS = {"upload": "uploads", "document": "documents", "receipt": "receipts", "voice": "voice"}


@dataclass
class Held:
    kind: str
    item_id: str
    user_id: str
    expires_at: datetime
    path: Path | None = None
    data: object = field(default=None, repr=False)


class PersonalStore:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self._items: dict[str, Held] = {}

    def add(self, kind: str, item_id: str, user_id: str, *, path: Path | None = None, data: object = None) -> Held:
        held = Held(kind, item_id, user_id, self.clock.now() + RETENTION[kind], path, data)
        self._items[item_id] = held
        return held

    def get(self, user_id: str, item_id: str) -> Held | None:
        held = self._items.get(item_id)
        if held is None or held.user_id != user_id or self.clock.now() >= held.expires_at:
            return None
        return held

    def live(self, user_id: str, kind: str | None = None) -> list[Held]:
        """最終：その利用者の期限内のもの（追加した順）。kind を渡すとその種別だけ。"""
        now = self.clock.now()
        return [h for h in self._items.values()
                if h.user_id == user_id and now < h.expires_at and (kind is None or h.kind == kind)]

    def of_user(self, user_id: str) -> list[Held]:
        return [h for h in self._items.values() if h.user_id == user_id]

    def count(self, user_id: str) -> dict[str, int]:
        counts = dict.fromkeys(KEYS.values(), 0)
        for held in self.of_user(user_id):
            counts[KEYS[held.kind]] += 1
        return counts

    def sweep(self) -> dict[str, int]:
        now = self.clock.now()
        return self._remove(lambda held: now >= held.expires_at)

    def delete_user(self, user_id: str) -> dict[str, int]:
        return self._remove(lambda held: held.user_id == user_id)

    def _remove(self, match: Callable[[Held], bool]) -> dict[str, int]:
        removed = dict.fromkeys(KEYS.values(), 0)
        for held in [h for h in self._items.values() if match(h)]:
            if held.path is not None:
                held.path.unlink(missing_ok=True)
            del self._items[held.item_id]
            removed[KEYS[held.kind]] += 1
        return removed
