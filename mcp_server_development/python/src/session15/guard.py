"""外部データの無害化（サニタイズ）と信頼境界の明示（Python 版）

TypeScript 版 node/src/session15/sanitize.ts と同じ判定になるように書いています。
このモジュールも MCP を知りません（mcp を import しません）。
"""

from __future__ import annotations

import re
import secrets as secrets_module
from dataclasses import dataclass

DIRECTIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "override_instructions",
        re.compile(
            r"(?:これまで|今まで|以前|上記|先ほど)の(?:指示|命令|ルール|プロンプト)"
            r"[^。\n]{0,24}?(?:無視|忘れ|破棄|上書き)"
        ),
    ),
    (
        "override_instructions_en",
        re.compile(
            r"ignore\s+(?:all\s+)?(?:previous|prior|above|earlier)\s+"
            r"(?:instructions?|prompts?|rules?)",
            re.IGNORECASE,
        ),
    ),
    (
        "system_prompt_probe",
        re.compile(
            r"(?:システムプロンプト|初期プロンプト|system\s*prompt)"
            r"[^。\n]{0,24}?(?:出力|表示|教え|返し|reveal|print|repeat)",
            re.IGNORECASE,
        ),
    ),
    (
        "credential_exfiltration",
        re.compile(
            r"(?:トークン|APIキー|API\s*キー|認証情報|パスワード|credentials?|secrets?)"
            r"[^。\n]{0,24}?(?:送信|送って|貼り付け|投稿|アップロード|send|post)",
            re.IGNORECASE,
        ),
    ),
    (
        "tool_invocation",
        re.compile(
            r"(?:ツール|tool)[^。\n]{0,24}?"
            r"(?:必ず呼び出|かならず呼び出|呼び出してください|実行してください|call\s+this)",
            re.IGNORECASE,
        ),
    ),
]

DIRECTIVE_PLACEHOLDER = "[指示文を除去]"
DEFAULT_MAX_LENGTH = 400

#: 見えない文字（ゼロ幅・双方向制御・BOM）のコードポイント。
#: 正規表現に直接書くと、ソースコードに見えない文字が紛れてレビューできなくなる
INVISIBLE_CODE_POINTS = frozenset(
    [0x00AD, 0xFEFF]
    + list(range(0x200B, 0x2010))
    + list(range(0x202A, 0x202F))
    + list(range(0x2060, 0x2065))
    + list(range(0x2066, 0x206A))
)
MARKER_PATTERN = re.compile(r"[<>]{2,}|`{3,}")
IMPERATIVE_PATTERN = re.compile(r"ください|下さい|しなさい")


def strip_invisible(text: str) -> tuple[str, int]:
    """見えない文字と制御文字を落とす（タブ・改行・復帰は残す）"""
    out: list[str] = []
    removed = 0
    for character in text:
        code_point = ord(character)
        is_control = code_point not in (0x09, 0x0A, 0x0D) and (
            code_point <= 0x1F or code_point == 0x7F
        )
        if is_control or code_point in INVISIBLE_CODE_POINTS:
            removed += 1
            continue
        out.append(character)
    return "".join(out), removed


@dataclass(frozen=True)
class SanitizeReport:
    text: str
    findings: tuple[str, ...]
    removed_invisible: int
    neutralized_markers: int
    truncated: bool


def detect_directives(text: str) -> tuple[str, ...]:
    """検出した指示文パターンの識別子を、出現位置の昇順で返す"""
    found: list[tuple[int, str]] = []
    for name, pattern in DIRECTIVE_PATTERNS:
        for match in pattern.finditer(text):
            found.append((match.start(), name))
    found.sort()
    return tuple(name for _, name in found)


def sanitize_external_text(
    raw: str,
    *,
    max_length: int = DEFAULT_MAX_LENGTH,
    keep_newlines: bool = False,
) -> SanitizeReport:
    text, removed = strip_invisible(raw)
    text = re.sub(r"\r\n?", "\n", text) if keep_newlines else re.sub(r"[\r\n\t]+", " ", text)

    markers = len(MARKER_PATTERN.findall(text))
    text = MARKER_PATTERN.sub("", text)

    text = re.sub(r"[^\S\n]{2,}", " ", text) if keep_newlines else re.sub(r"\s{2,}", " ", text)
    text = text.strip()

    findings = detect_directives(text)
    for _, pattern in DIRECTIVE_PATTERNS:
        text = pattern.sub(DIRECTIVE_PLACEHOLDER, text)

    truncated = len(text) > max_length
    if truncated:
        text = text[:max_length] + "…"
    return SanitizeReport(text, findings, removed, markers, truncated)


def count_imperatives(text: str) -> int:
    """サニタイズでは消えない命令形の数。境界の内側で数えるために使う"""
    return len(IMPERATIVE_PATTERN.findall(text))


def new_nonce() -> str:
    return secrets_module.token_hex(8)


def untrusted_boundary(nonce: str) -> tuple[str, str]:
    return (f"<<<UNTRUSTED-DATA {nonce} BEGIN>>>", f"<<<UNTRUSTED-DATA {nonce} END>>>")


def wrap_untrusted(nonce: str, source: str, note: str, body: str) -> str:
    begin, end = untrusted_boundary(nonce)
    return "\n".join([begin, f"出所: {source}", f"信頼レベル: 低（{note}）", body, end])
