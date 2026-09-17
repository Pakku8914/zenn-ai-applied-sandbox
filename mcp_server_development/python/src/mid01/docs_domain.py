"""社内ドキュメント検索 ― ドメイン層（Python 版）

TypeScript 版（node/src/mid01/domain/）と同じ判定・同じスコア・同じ順序になるように
書いています。パス検証・走査・検索を 1 モジュールにまとめているのは、Python 版が
search_documents 1 本だけの移植で、分割の利得が小さいためです。

このモジュールは mcp を import しません（テストから直接検証できるようにするため）。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

MAX_PATH_LENGTH = 200
MAX_DEPTH = 3
MAX_DOCUMENTS = 500
SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
DRIVE_LETTER_PATTERN = re.compile(r"^[A-Za-z]:")

SCORE_TITLE = 5
SCORE_HEADING = 3
SCORE_BODY = 1
DEFAULT_LIMIT = 5
MAX_LIMIT = 20
MAX_QUERY_LENGTH = 100
MAX_TERMS = 5
SNIPPET_LENGTH = 60

URI_SCHEME = "docs"

#: 拒否理由ごとの固定文面。入力値と内部パスを含めない
REJECT_MESSAGES: dict[str, str] = {
    "empty": "path が空です。",
    "too_long": f"path が長すぎます（{MAX_PATH_LENGTH} 文字以内で指定してください）。",
    "control_character": "path に使用できない制御文字が含まれています。",
    "drive_letter": "path にドライブレターは使用できません。",
    "backslash": "path の区切りには / を使用してください。",
    "absolute_path": "path は公開ディレクトリからの相対パスで指定してください。",
    "parent_traversal": "path に .. や . を含めることはできません。",
    "too_deep": f"path の階層は {MAX_DEPTH} 段までです。",
    "invalid_segment": (
        "path に使用できるのは半角英数字とピリオド・ハイフン・アンダースコアのみです。"
    ),
    "not_markdown": "参照できるのは拡張子 .md のファイルだけです。",
    "outside_root": "指定されたファイルは公開対象のディレクトリの外にあります。",
    "symlink": (
        "指定されたファイルはシンボリックリンクで公開対象の外を指しているため参照できません。"
    ),
    "not_found": "指定されたファイルは見つかりません。",
    "not_file": "指定されたパスはファイルではありません。",
}


class DocAccessError(Exception):
    """ドメイン層のエラー。reason で機械的に判別できる"""

    def __init__(self, reason: str) -> None:
        super().__init__(REJECT_MESSAGES[reason])
        self.reason = reason


def normalize_doc_path(raw: str) -> str:
    """構文検査だけを行う（ファイルシステムに触らない）。

    TypeScript 版との差分: unquote() は不正なパーセントエンコード（"%zz"）で
    例外を投げず、そのまま残します。したがって "%zz" は invalid_encoding ではなく
    invalid_segment として落ちます（"%" が許可リストに無いため）。
    """
    decoded = unquote(raw.strip())
    if decoded == "":
        raise DocAccessError("empty")
    if len(decoded) > MAX_PATH_LENGTH:
        raise DocAccessError("too_long")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in decoded):
        raise DocAccessError("control_character")
    # ドライブレターはバックスラッシュより先に見る（"C:\\x" は両方に該当する）
    if DRIVE_LETTER_PATTERN.match(decoded):
        raise DocAccessError("drive_letter")
    if "\\" in decoded:
        raise DocAccessError("backslash")
    if decoded.startswith("/"):
        raise DocAccessError("absolute_path")

    segments = decoded.split("/")
    # .. の検査は区間数より先（"../../etc/passwd" は 4 区間ある）
    if any(segment in (".", "..") for segment in segments):
        raise DocAccessError("parent_traversal")
    if len(segments) > MAX_DEPTH:
        raise DocAccessError("too_deep")
    if any(SEGMENT_PATTERN.match(segment) is None for segment in segments):
        raise DocAccessError("invalid_segment")
    if not segments[-1].lower().endswith(".md"):
        raise DocAccessError("not_markdown")
    return "/".join(segments)


def resolve_safe_doc_path(root: Path, raw: str) -> Path:
    """構文検査 → 実パス確認まで行う"""
    relative = normalize_doc_path(raw)
    try:
        # 基準ディレクトリ側にも resolve を掛ける（/tmp がリンクの環境で誤判定を防ぐ）
        real_root = root.resolve(strict=True)
    except OSError as exc:
        raise DocAccessError("not_found") from exc

    # シンボリックリンクを解決せずに正規化する（1 段目の壁）
    candidate = Path(os.path.normpath(real_root / relative))
    if candidate == real_root or not candidate.is_relative_to(real_root):
        raise DocAccessError("outside_root")

    try:
        # resolve はシンボリックリンクを解決する（2 段目の壁）
        real = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise DocAccessError("not_found") from exc
    if real == real_root or not real.is_relative_to(real_root):
        raise DocAccessError("symlink")
    if not real.is_file():
        raise DocAccessError("not_file")
    return real


@dataclass(frozen=True, slots=True)
class DocumentMeta:
    relative_path: str
    uri: str
    title: str
    byte_size: int
    line_count: int


@dataclass(frozen=True, slots=True)
class DocumentContent:
    meta: DocumentMeta
    text: str


class DocRepository:
    """文書の走査と読み取り。走査順を名前順に固定して決定的にする"""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def to_uri(self, relative_path: str) -> str:
        return f"{URI_SCHEME}://{relative_path}"

    def list_documents(self) -> list[DocumentMeta]:
        relatives: list[str] = []
        self._walk("", relatives)
        # Python の sorted はコードポイント順（TypeScript 版の compareStrings と同じ）
        relatives.sort()
        return [self._meta(relative) for relative in relatives]

    def list_directories(self) -> list[str]:
        found: set[str] = set()
        for meta in self.list_documents():
            parents = meta.relative_path.split("/")[:-1]
            if parents:
                found.add("/".join(parents))
        return sorted(found)

    def read_document(self, raw_path: str) -> DocumentContent:
        absolute = resolve_safe_doc_path(self.root, raw_path)
        relative = normalize_doc_path(raw_path)
        text = absolute.read_text(encoding="utf-8")
        return DocumentContent(meta=self._build_meta(relative, text), text=text)

    def _walk(self, current: str, out: list[str]) -> None:
        depth = 0 if current == "" else len(current.split("/"))
        if depth >= MAX_DEPTH:
            return
        directory = self.root / current if current else self.root
        try:
            entries = sorted(directory.iterdir(), key=lambda entry: entry.name)
        except OSError:
            return
        for entry in entries:
            # シンボリックリンクは辿らない（公開対象の外を索引に載せない）
            if entry.is_symlink() or entry.name.startswith("."):
                continue
            relative = f"{current}/{entry.name}" if current else entry.name
            if entry.is_dir():
                self._walk(relative, out)
            elif entry.is_file() and entry.name.lower().endswith(".md"):
                out.append(relative)
                if len(out) >= MAX_DOCUMENTS:
                    return

    def _meta(self, relative: str) -> DocumentMeta:
        text = (self.root / relative).read_text(encoding="utf-8")
        return self._build_meta(relative, text)

    def _build_meta(self, relative: str, text: str) -> DocumentMeta:
        return DocumentMeta(
            relative_path=relative,
            uri=self.to_uri(relative),
            title=extract_title(text, relative),
            byte_size=len(text.encode("utf-8")),
            line_count=len(text.rstrip("\n").split("\n")),
        )


def create_repository(root: Path) -> DocRepository:
    return DocRepository(root)


def extract_title(text: str, fallback: str) -> str:
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def split_document(text: str) -> tuple[str, str, str]:
    """タイトル・見出し・本文の 3 つに分ける（重み付けの単位）"""
    title_lines: list[str] = []
    heading_lines: list[str] = []
    body_lines: list[str] = []
    title_found = False
    for line in text.split("\n"):
        stripped = line.strip()
        if not title_found and stripped.startswith("# "):
            title_lines.append(stripped[2:])
            title_found = True
        elif stripped.startswith("#"):
            heading_lines.append(re.sub(r"^#+\s*", "", stripped))
        else:
            body_lines.append(line)
    return "\n".join(title_lines), "\n".join(heading_lines), "\n".join(body_lines)


def count_occurrences(haystack: str, needle: str) -> int:
    """重なりを数えない出現回数"""
    if needle == "":
        return 0
    count = 0
    index = haystack.find(needle)
    while index != -1:
        count += 1
        index = haystack.find(needle, index + len(needle))
    return count


def score_document(text: str, terms: list[str]) -> tuple[int, int]:
    """AND 検索。1 語でも含まない文書はスコア 0"""
    title, headings, body = (part.lower() for part in split_document(text))
    score = 0
    match_count = 0
    for term in terms:
        needle = term.lower()
        in_title = count_occurrences(title, needle)
        in_heading = count_occurrences(headings, needle)
        in_body = count_occurrences(body, needle)
        hits = in_title + in_heading + in_body
        if hits == 0:
            return 0, 0
        score += in_title * SCORE_TITLE + in_heading * SCORE_HEADING + in_body * SCORE_BODY
        match_count += hits
    return score, match_count


def build_snippet(text: str, term: str) -> str:
    """タイトル行を除いて最初に一致した行から抜粋を作る"""
    needle = term.lower()
    title_seen = False
    fallback = ""
    for line in text.split("\n"):
        stripped = line.strip()
        is_title = not title_seen and stripped.startswith("# ")
        if is_title:
            title_seen = True
        plain = re.sub(r"^[-*]\s+", "", re.sub(r"^#+\s*", "", stripped)).strip()
        if plain == "" or needle not in plain.lower():
            continue
        if is_title:
            if fallback == "":
                fallback = plain
            continue
        return _truncate(plain)
    return _truncate(fallback)


def _truncate(text: str) -> str:
    # Python の文字列はコードポイント単位なのでそのまま切ってよい
    return text if len(text) <= SNIPPET_LENGTH else text[:SNIPPET_LENGTH] + "…"


def parse_query(raw: str) -> list[str]:
    """Python の \\s も全角空白（U+3000）を含む"""
    normalized = re.sub(r"\s+", " ", raw.strip())
    if normalized == "":
        raise ValueError("検索語を 1 文字以上で指定してください。")
    if len(normalized) > MAX_QUERY_LENGTH:
        raise ValueError(f"検索語は {MAX_QUERY_LENGTH} 文字以内で指定してください。")
    return normalized.split(" ")[:MAX_TERMS]


def search_documents(
    repository: DocRepository,
    query: str,
    limit: int | None = None,
    directory: str | None = None,
) -> dict:
    """検索結果を dict で返す。プロトコルに出るキー名は camelCase に揃える。

    業務エラーは ValueError で表します（SDK が isError のツール結果へ変換します）。
    TypeScript 版が { ok: false } を返す設計なのに対し、Python 版が例外なのは
    高水準 API の作法に合わせたためです。
    """
    terms = parse_query(query)
    bounded = DEFAULT_LIMIT if limit is None else min(MAX_LIMIT, max(1, int(limit)))

    scope = (directory or "").strip()
    if scope:
        known = repository.list_directories()
        if scope not in known:
            raise ValueError(
                "directory に指定できるのは "
                + " / ".join(known)
                + " のいずれかです（省略すると公開ディレクトリ全体を検索します）。"
            )

    hits: list[dict] = []
    for meta in repository.list_documents():
        if scope and not meta.relative_path.startswith(f"{scope}/"):
            continue
        try:
            content = repository.read_document(meta.relative_path)
        except DocAccessError:
            continue
        score, match_count = score_document(content.text, terms)
        if score == 0:
            continue
        hits.append(
            {
                "path": meta.relative_path,
                "uri": meta.uri,
                "title": meta.title,
                "score": score,
                "matchCount": match_count,
                "snippet": build_snippet(content.text, terms[0]),
            }
        )

    # スコア降順 → パス昇順（タプルのキーで 2 段ソートを表現する）
    hits.sort(key=lambda hit: (-hit["score"], hit["path"]))
    limited = hits[:bounded]

    result: dict = {
        "query": " ".join(terms),
        "totalMatched": len(hits),
        "returned": len(limited),
        "truncated": len(hits) > len(limited),
        "results": limited,
    }
    if scope:
        result["directory"] = scope
    return result
