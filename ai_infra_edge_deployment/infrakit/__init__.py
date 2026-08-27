"""infrakit — 本書全体で使う推論基盤・エッジの共通ライブラリ。

章をまたいでインターフェースを変えない（requirements.md の「API契約」）。
"""

from .client import GenResult, LlamaClient

__all__ = ["GenResult", "LlamaClient"]
