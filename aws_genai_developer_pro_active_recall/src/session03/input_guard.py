#!/usr/bin/env python3
"""セッション3: FM に渡す前の検証（validation）と正規化（normalization）。

設計は2段です。

1. **修復（repair）** — 表記のゆれは機械的に直せるので直す（NFKC 正規化・連続空白の圧縮・前後空白の除去）
2. **遮断（block）** — 直せない／直してはいけないものは通さない
   （空・長すぎ・機密混入・文字化け・重複）

「直せるものは直し、直せないものは隔離する」を1つの関数にしたのが `check()` です。
実務ではこの判定を AWS Glue Data Quality のルールセットに寄せますが、
ルールの中身（何を見て何を落とすか）はここで書く内容とまったく同じです。

    docker compose exec app python src/session03/input_guard.py
"""

from __future__ import annotations

import hashlib
import re
import sys
import unicodedata
from dataclasses import dataclass

sys.path.insert(0, "/workspace")

from bedrock_mock import generation  # noqa: E402

# 1文書あたりの入力トークン上限。
# 「モデルのコンテキスト窓」ではなく「1リクエストに載せてよい予算」から決めます。
# 窓が 300,000 トークンあっても、全部使えばコストとレイテンシがそのまま跳ね上がります。
MAX_INPUT_TOKENS = 2_000

# 遮断する欠陥と、修復する欠陥を先に宣言しておく（後から増えても表が壊れないため）
BLOCK_RULES = ("mojibake", "empty", "too_long", "pii", "duplicate")
REPAIR_RULES = ("nfkc", "whitespace")

# 機密混入の検出。ここでは「検出して弾く」までを担当し、
# 匿名化のポリシー設計は「セッション13：データセキュリティとプライバシー」で扱います
PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "phone": re.compile(r"(?<!\d)0\d{1,4}-\d{1,4}-\d{4}(?!\d)"),
    "long_digits": re.compile(r"(?<!\d)\d{12,}(?!\d)"),
}

# U+FFFD（置換文字）と、タブ・改行を除く制御文字。どちらも「取り込み経路が壊れた痕跡」。
# `�` は re モジュールが解釈するため、生文字列のまま書けます
MOJIBAKE_PATTERN = re.compile(r"[�\x00-\x08\x0b\x0c\x0e-\x1f]")

# 連続する半角空白・タブ。全角空白は NFKC が半角空白に変換するのでここには書かない
SPACE_RUN_PATTERN = re.compile(r"[ \t]{2,}")


@dataclass(frozen=True)
class Finding:
    """検証で見つかった欠陥1件。`rule` は BLOCK_RULES のいずれか。"""

    rule: str
    detail: str = ""


@dataclass(frozen=True)
class CheckResult:
    doc_id: str
    source_uri: str
    status: str  # "accepted" | "quarantined"
    text: str  # 正規化後のテキスト（隔離時は使わない）
    tokens: int
    repairs: tuple[str, ...] = ()
    findings: tuple[Finding, ...] = ()
    fingerprint: str = ""

    @property
    def rules(self) -> tuple[str, ...]:
        """検出した規則名を重複なく、宣言順で返す。"""
        found = {f.rule for f in self.findings}
        return tuple(r for r in BLOCK_RULES if r in found)

    @property
    def details(self) -> tuple[str, ...]:
        return tuple(f"{f.rule}:{f.detail}" if f.detail else f.rule for f in self.findings)


def normalize(text: str) -> tuple[str, tuple[str, ...]]:
    """修復を適用し、(正規化後のテキスト, 適用した修復名) を返す。

    NFKC を最初に置くのが要点です。全角英数・半角カタカナ・互換文字は
    「同じ意味なのに別の文字」なので、正規化前に重複判定やキーワード一致をやると必ず外します。
    """
    applied: list[str] = []
    nfkc = unicodedata.normalize("NFKC", text)
    if nfkc != text:
        applied.append("nfkc")
    squeezed = SPACE_RUN_PATTERN.sub(" ", nfkc).strip()
    if squeezed != nfkc:
        applied.append("whitespace")
    return squeezed, tuple(applied)


def fingerprint(text: str) -> str:
    """重複判定用の指紋。**正規化後のテキスト**から作るのが肝心。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check(record: dict, *, seen: set[str]) -> CheckResult:
    """1件を検証する。`seen` には既に受理した文書の指紋を入れておく。"""
    doc_id = record.get("id", "(no-id)")
    source_uri = record.get("uri", "")
    raw = record.get("text") or ""
    findings: list[Finding] = []

    # 1) 文字化けは「修復せずに」遮断する。
    #    見た目を整えてしまうと、壊れた取り込み経路が直らないまま索引に入る
    if MOJIBAKE_PATTERN.search(raw):
        findings.append(Finding("mojibake", "置換文字または制御文字を含む"))

    # 2) 修復（この時点で表記は1通りに揃う）
    text, repairs = normalize(raw)
    tokens = generation.count_tokens(text)

    # 3) 空はここで打ち切る（空に対する長さ・機密・重複の判定は意味がない）
    if not text:
        findings.append(Finding("empty", "正規化後に本文が空"))
        return CheckResult(
            doc_id=doc_id,
            source_uri=source_uri,
            status="quarantined",
            text=text,
            tokens=tokens,
            repairs=repairs,
            findings=tuple(findings),
        )

    # 4) 長さ（本章では弾くところまで。分割戦略は検索機構のセッションで扱う）
    if tokens > MAX_INPUT_TOKENS:
        findings.append(Finding("too_long", f"{tokens} tok > {MAX_INPUT_TOKENS} tok"))

    # 5) 機密混入
    for name, pattern in PII_PATTERNS.items():
        if pattern.search(text):
            findings.append(Finding("pii", name))

    # 6) 重複（正規化後に一致するものは「同じ文書」として扱う）
    digest = fingerprint(text)
    if digest in seen:
        findings.append(Finding("duplicate", digest[:12]))

    status = "quarantined" if findings else "accepted"
    return CheckResult(
        doc_id=doc_id,
        source_uri=source_uri,
        status=status,
        text=text,
        tokens=tokens,
        repairs=repairs,
        findings=tuple(findings),
        fingerprint=digest,
    )


def check_all(records: list[dict]) -> list[CheckResult]:
    """バッチ全体を検証する。受理したものだけを重複判定の母集団に加える。"""
    seen: set[str] = set()
    results: list[CheckResult] = []
    for record in records:
        result = check(record, seen=seen)
        if result.status == "accepted":
            seen.add(result.fingerprint)
        results.append(result)
    return results


def main() -> None:
    """手で確かめる用の最小デモ。壊れ方ごとに1件ずつ通す。"""
    samples: list[dict] = [
        {"id": "ok", "text": "在宅勤務は週3日を上限として認められます。"},
        {"id": "empty", "text": "　　 "},
        {"id": "fullwidth", "text": "ＶＰＮクライアントはＷｉｎｄｏｗｓ１１で動きますか。"},
        {"id": "pii", "text": "田中様（tanaka@example.com、090-1234-5678）の対応履歴です。"},
        {"id": "mojibake", "text": "貸与PCの交換申��は資産管理番号が必要です。"},
        {"id": "long", "text": "あ" * 20_000},
    ]
    print(f"入力トークン上限: {MAX_INPUT_TOKENS} tok")
    print(f"{'id':<10} {'status':<12} repairs / findings")
    for result in check_all(samples):
        marks = list(result.repairs) + list(result.details)
        print(f"{result.doc_id:<10} {result.status:<12} {', '.join(marks) or '-'}")


if __name__ == "__main__":
    main()
