"""roots からの検索スコープ解決（Python 版・mcp を import しない）

TypeScript 版の doc-scope.ts と同じ判定をします。
中間プロジェクト1 の docs_domain.py は 1 行も書き換えず、外から包みます。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from mid01_domain import domain


@dataclass(frozen=True, slots=True)
class DocScope:
    #: "server-config" または "roots"
    source: str
    #: 許可された相対ディレクトリ。("",) は公開ディレクトリ全体
    directories: tuple[str, ...]
    ignored_roots: tuple[str, ...] = ()


WHOLE_SCOPE = DocScope(source="server-config", directories=("",))


def to_local_path(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
        return None
    return Path(unquote(parsed.path))


def resolve_scope_from_roots(docs_root: Path, root_uris: list[str]) -> DocScope | None:
    """公開ディレクトリの中を指す root だけを採用する（境界を広げない）

    1 つも採用できなければ None を返す。呼び出し側でツールを失敗させます。
    """
    base = docs_root.resolve()
    directories: set[str] = set()
    ignored: list[str] = []

    for uri in root_uris:
        local = to_local_path(uri)
        if local is None:
            ignored.append(uri)
            continue
        resolved = local.resolve()
        if resolved == base:
            directories.add("")
            continue
        if not resolved.is_relative_to(base):
            ignored.append(uri)
            continue
        directories.add(resolved.relative_to(base).as_posix())

    if not directories:
        return None
    listed = ("",) if "" in directories else tuple(sorted(directories))
    return DocScope(source="roots", directories=listed, ignored_roots=tuple(ignored))


def describe_scope(scope: DocScope) -> str:
    return "(公開ディレクトリ全体)" if "" in scope.directories else ", ".join(scope.directories)


def is_path_in_scope(scope: DocScope, relative_path: str) -> bool:
    return any(
        directory == "" or relative_path == directory or relative_path.startswith(f"{directory}/")
        for directory in scope.directories
    )


class ScopedRepository:
    """リポジトリをスコープで包む。検索も読み取りも同じ境界を通る"""

    def __init__(self, base: domain.DocRepository, scope: DocScope) -> None:
        self._base = base
        self._scope = scope

    @property
    def root(self) -> Path:
        return self._base.root

    def to_uri(self, relative_path: str) -> str:
        return self._base.to_uri(relative_path)

    def list_documents(self) -> list[domain.DocumentMeta]:
        return [
            meta
            for meta in self._base.list_documents()
            if is_path_in_scope(self._scope, meta.relative_path)
        ]

    def list_directories(self) -> list[str]:
        return [
            directory
            for directory in self._base.list_directories()
            if is_path_in_scope(self._scope, f"{directory}/")
        ]

    def read_document(self, raw_path: str) -> domain.DocumentContent:
        relative = domain.normalize_doc_path(raw_path)
        if not is_path_in_scope(self._scope, relative):
            raise domain.DocAccessError("outside_root")
        return self._base.read_document(raw_path)
