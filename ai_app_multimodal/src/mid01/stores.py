"""取り込んだものの置き場所（プロセス内メモリ。再起動すると消える）。

- DocumentStore：セッション5と同じ。本プロジェクトは ask を持たないので、抜き出した文字と索引は持たない
- ReceiptStore：セッション7と同じ
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ulid import ULID

from src.mid01.pdftext import ReceiptText
from src.mid01.receipt import ReceiptRead


@dataclass
class StoredDocument:
    document_id: str
    user_id: str
    sha256: str
    pages: int
    data: bytes = field(repr=False)

    def view(self) -> dict:
        return {"document_id": self.document_id, "pages": self.pages, "sha256": self.sha256}


class DocumentStore:
    def __init__(self) -> None:
        self._by_id: dict[str, StoredDocument] = {}
        self._by_hash: dict[tuple[str, str], str] = {}  # (利用者, SHA256) → document_id

    def find(self, user_id: str, sha256: str) -> StoredDocument | None:
        doc_id = self._by_hash.get((user_id, sha256))
        return self._by_id[doc_id] if doc_id else None

    def add(self, user_id: str, sha256: str, pages: int, data: bytes) -> tuple[StoredDocument, bool]:
        if (existing := self.find(user_id, sha256)) is not None:
            return existing, False
        doc = StoredDocument(f"doc_{ULID()}", user_id, sha256, pages, data)
        self._by_id[doc.document_id] = doc
        self._by_hash[(user_id, sha256)] = doc.document_id
        return doc, True

    def get(self, user_id: str, document_id: str) -> StoredDocument | None:
        doc = self._by_id.get(document_id)
        return doc if doc is not None and doc.user_id == user_id else None


@dataclass
class StoredReceipt:
    receipt_id: str
    user_id: str
    sha256: str
    source: str
    read: ReceiptRead
    issues: list[dict]
    text: ReceiptText | None = field(default=None, repr=False)

    def view(self) -> dict:
        return {
            "receipt_id": self.receipt_id,
            "source": self.source,
            **self.read.model_dump(),
            "needs_review": bool(self.issues),
            "issues": self.issues,
            "text_checked": self.text is not None,
        }


class ReceiptStore:
    def __init__(self) -> None:
        self._by_id: dict[str, StoredReceipt] = {}
        self._by_hash: dict[tuple[str, str], str] = {}

    def find(self, user_id: str, sha256: str) -> StoredReceipt | None:
        receipt_id = self._by_hash.get((user_id, sha256))
        return self._by_id[receipt_id] if receipt_id else None

    def add(self, receipt: StoredReceipt) -> bool:
        key = (receipt.user_id, receipt.sha256)
        if key in self._by_hash:
            return False
        self._by_id[receipt.receipt_id] = receipt
        self._by_hash[key] = receipt.receipt_id
        return True

    def of_user(self, user_id: str) -> list[StoredReceipt]:
        return [r for r in self._by_id.values() if r.user_id == user_id]  # 取り込んだ順
