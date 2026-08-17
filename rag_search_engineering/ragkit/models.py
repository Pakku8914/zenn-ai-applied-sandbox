"""章をまたいで共有するデータ構造。

ここで定義した型は「API契約」であり、章の途中で名前や型を変えない。
（requirements.md の「API契約」を参照）
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Doc:
    """コーパスの1文書。"""

    doc_id: str  # DOC-0001 形式
    title: str
    body: str
    category: str  # 勤怠 / 経費 / PC・端末 / アカウント / オフィス / セキュリティ
    updated_at: str  # ISO 日付（YYYY-MM-DD）
    visibility: str  # all / dept / manager
    dept: str
    source_type: str  # faq / procedure / policy / notice
    theme: str  # 生成器が付ける主題キー（判定データの導出に使う）

    @property
    def full_text(self) -> str:
        """検索対象にする本文（タイトルを含める）。"""
        return f"{self.title}\n{self.body}"


@dataclass(frozen=True)
class Chunk:
    """検索の単位。chunk_id は "{doc_id}#{連番3桁}"。"""

    chunk_id: str
    doc_id: str
    text: str
    ordinal: int
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Hit:
    """検索結果の1件。

    score の尺度は検索方式ごとに異なる（BM25 は非有界・コサインは -1〜1）。
    ragkit 側で正規化して隠すことは意図的にしていない（セッション8の題材）。
    """

    chunk_id: str
    doc_id: str
    score: float
    text: str
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Query:
    query_id: str  # Q-001 形式
    text: str
    type: str  # keyword / natural / abbrev / multi_condition / temporal / unanswerable


@dataclass(frozen=True)
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    source: str = "stub"  # stub / fixture / api
