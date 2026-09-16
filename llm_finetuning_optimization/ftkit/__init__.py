"""ftkit — 本書全体で使う学習・評価・量子化の共通ライブラリ。

章をまたいでインターフェースを変えない（requirements.md の「API契約」）。
"""

from .data import CATEGORIES, Example

__all__ = ["CATEGORIES", "Example"]
