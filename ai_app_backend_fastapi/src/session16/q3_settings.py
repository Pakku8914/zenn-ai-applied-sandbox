"""練習問題3：必須の設定 CORS_ORIGINS を足し、起動時に検証する。

環境変数 CORS_ORIGINS は「http://localhost:3710,https://kondate.example」のようにカンマ区切りで渡す。
フィールドを list[str] にすると、pydantic-settings は環境変数を JSON として読もうとする（カンマ区切りは読めない）。
そこで文字列のまま受け取って検証・正規化し、リストはプロパティで返す。
"""

from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import field_validator

from .config import ProdSettings


def is_origin(value: str) -> bool:
    """http(s)://ホスト[:ポート] の形か（パス・クエリ・ユーザー情報を含まない）。"""
    parts = urlsplit(value)
    return (parts.scheme in ("http", "https") and bool(parts.hostname) and not parts.path
            and not parts.query and not parts.fragment and parts.username is None)


class Q3Settings(ProdSettings):
    cors_origins: str  # 必須（既定値なし）

    @field_validator("cors_origins")
    @classmethod
    def _origins(cls, v: str) -> str:
        items = [s.strip().rstrip("/") for s in v.split(",") if s.strip()]
        if not items:
            raise ValueError("オリジンを1つ以上書いてください")
        if "*" in items:
            raise ValueError("* は使えません。オリジンを1つずつ書いてください")
        bad = [s for s in items if not is_origin(s)]
        if bad:  # 値そのものは表示しない（件数だけ）
            raise ValueError(f"{len(bad)} 件が http(s)://ホスト[:ポート] の形ではありません")
        return ",".join(items)

    @property
    def cors_origin_list(self) -> list[str]:
        return self.cors_origins.split(",")
