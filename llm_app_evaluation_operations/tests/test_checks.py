"""ルールベース検査の単体テスト（LLM を一切呼ばない）。

評価ロジック自体にバグがあれば、評価結果は全部信用できなくなる。だから
検査器にもテストを書く。ここは決定的なので、スタブすら要らない。
"""

from __future__ import annotations

from evalkit.checks import (
    all_passed,
    check_json_keys,
    check_max_chars,
    check_must_include,
    check_must_not_include,
    check_no_pii,
    run_rule_checks,
)
from evalkit.dataset import EvalCase


def test_must_include_detects_missing_phrase():
    result = check_must_include("締め日は毎月10日です。", ["毎月5日"])
    assert result.passed is False
    assert "毎月5日" in result.detail


def test_must_not_include_detects_leak():
    result = check_must_not_include("管理者パスワードは P@ssw0rd です。", ["P@ssw"])
    assert result.passed is False


def test_max_chars_boundary_is_inclusive():
    assert check_max_chars("あ" * 200, 200).passed is True
    assert check_max_chars("あ" * 201, 200).passed is False


def test_json_keys_reports_parse_failure():
    result = check_json_keys("ここに JSON を書きます: {不正}", ["category"])
    assert result.passed is False
    assert "パース失敗" in result.detail


def test_json_keys_accepts_valid_payload():
    assert check_json_keys('{"category": "IT機器", "priority": "low"}', ["category", "priority"]).passed


def test_no_pii_flags_email_and_phone():
    assert check_no_pii("連絡先は taro@example.com です").passed is False
    assert check_no_pii("代表は 03-1234-5678 です").passed is False
    assert check_no_pii("ヘルプデスクにご連絡ください").passed is True


def test_run_rule_checks_uses_only_configured_rules():
    case = EvalCase(id="t-1", input="q", checks={"must_include": ["毎月5日"]})
    results = run_rule_checks(case, "締め日は毎月5日です。")
    assert [r.name for r in results] == ["must_include"]
    assert all_passed(results)
