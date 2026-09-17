"""ルールベース（決定的）な自動評価。

LLM に採点させる前に、機械で判定できることは機械で判定する。速く、安く、
毎回同じ答えが出る検査から先に通すのが評価パイプラインの基本形。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from evalkit.dataset import EvalCase

# 検出用の最小パターン（本番では専用のライブラリ／サービスを使うこと）
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_JP_PHONE_RE = re.compile(r"0\d{1,4}-\d{1,4}-\d{3,4}")
_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")


@dataclass(frozen=True)
class CheckResult:
    """1 つの検査の結果。落ちた理由が分かる detail を必ず残す。"""

    name: str
    passed: bool
    detail: str = ""


def check_must_include(text: str, phrases: list[str]) -> CheckResult:
    """必ず含まれるべき語句がすべて含まれているか。"""
    missing = [p for p in phrases if p not in text]
    return CheckResult(
        name="must_include",
        passed=not missing,
        detail="" if not missing else f"欠落: {missing}",
    )


def check_must_not_include(text: str, phrases: list[str]) -> CheckResult:
    """含まれてはいけない語句が含まれていないか。"""
    found = [p for p in phrases if p in text]
    return CheckResult(
        name="must_not_include",
        passed=not found,
        detail="" if not found else f"混入: {found}",
    )


def check_max_chars(text: str, limit: int) -> CheckResult:
    """出力が長すぎないか（UI の表示崩れとコストの両方に効く）。"""
    return CheckResult(
        name="max_chars",
        passed=len(text) <= limit,
        detail="" if len(text) <= limit else f"{len(text)} 文字 > 上限 {limit} 文字",
    )


def check_json_keys(text: str, required_keys: list[str]) -> CheckResult:
    """JSON としてパースでき、必須キーがそろっているか。"""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return CheckResult(name="json_keys", passed=False, detail=f"JSON パース失敗: {exc}")
    if not isinstance(parsed, dict):
        return CheckResult(name="json_keys", passed=False, detail="トップレベルがオブジェクトでない")
    missing = [k for k in required_keys if k not in parsed]
    return CheckResult(
        name="json_keys",
        passed=not missing,
        detail="" if not missing else f"欠落キー: {missing}",
    )


def check_no_pii(text: str) -> CheckResult:
    """個人情報らしい文字列が出力に混ざっていないか。"""
    hits: list[str] = []
    if _EMAIL_RE.search(text):
        hits.append("email")
    if _JP_PHONE_RE.search(text):
        hits.append("phone")
    if _CARD_RE.search(text):
        hits.append("card_number")
    return CheckResult(
        name="no_pii",
        passed=not hits,
        detail="" if not hits else f"検出: {hits}",
    )


def run_rule_checks(case: EvalCase, text: str) -> list[CheckResult]:
    """ケースの `checks` 設定に従って検査を実行する。

    設定されていない検査は実行しない（= ケースごとに合格条件を変えられる）。
    """
    results: list[CheckResult] = []
    checks = case.checks

    if "must_include" in checks:
        results.append(check_must_include(text, list(checks["must_include"])))
    if "must_not_include" in checks:
        results.append(check_must_not_include(text, list(checks["must_not_include"])))
    if "max_chars" in checks:
        results.append(check_max_chars(text, int(checks["max_chars"])))
    if "json_keys" in checks:
        results.append(check_json_keys(text, list(checks["json_keys"])))
    if checks.get("no_pii"):
        results.append(check_no_pii(text))

    if not results:
        results.append(CheckResult(name="no_rules", passed=True, detail="ルール未設定"))
    return results


def all_passed(results: list[CheckResult]) -> bool:
    """すべての検査に通ったか。"""
    return all(r.passed for r in results)
