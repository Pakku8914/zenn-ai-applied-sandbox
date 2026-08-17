"""ragkit — 本書全体で使う検索の共通ライブラリ。

章をまたいでインターフェースを変えない（requirements.md の「API契約」）。
"""

from .models import Chunk, Doc, Hit, LLMResponse, Query

__all__ = ["Chunk", "Doc", "Hit", "LLMResponse", "Query"]
