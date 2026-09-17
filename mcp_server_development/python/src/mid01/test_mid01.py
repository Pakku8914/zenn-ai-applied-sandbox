"""中間プロジェクト1 のテスト（Python 版）

実行： docker compose exec python python -m pytest src/mid01 -q

pytest.ini の pythonpath は src なので、同じディレクトリの docs_domain を
import できるように sys.path を足しています（章ごとにディレクトリを分けているため）。
実務ではパッケージとして構成し、相対 import で解決します（セッション14）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import docs_domain as domain  # noqa: E402  （sys.path を設定した後に import する必要があるため）

DOCS_ROOT = Path("src/mid01/docs").resolve()


@pytest.fixture(scope="module")
def repository() -> domain.DocRepository:
    return domain.create_repository(DOCS_ROOT)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "parent_traversal"),
        ("/etc/passwd", "absolute_path"),
        ("..%2f..%2fetc%2fpasswd", "parent_traversal"),
        ("%2e%2e%2fsecret.md", "parent_traversal"),
        ("guides/../../etc/passwd", "parent_traversal"),
        ("C:\\windows\\win.ini", "drive_letter"),
        ("guides\\vpn-setup.md", "backslash"),
        ("onboarding.md%00.txt", "control_character"),
        ("onboarding.txt", "not_markdown"),
        ("guides", "not_markdown"),
        ("a/b/c/d/e.md", "too_deep"),
    ],
)
def test_rejects_dangerous_paths(raw: str, expected: str) -> None:
    with pytest.raises(domain.DocAccessError) as info:
        domain.normalize_doc_path(raw)
    assert info.value.reason == expected


def test_lists_documents_in_order(repository: domain.DocRepository) -> None:
    paths = [meta.relative_path for meta in repository.list_documents()]
    assert paths == [
        "faq/account-lock.md",
        "faq/printer.md",
        "guides/incident-response.md",
        "guides/vpn-setup.md",
        "onboarding.md",
        "remote-work.md",
        "security-policy.md",
    ]


def test_lists_directories(repository: domain.DocRepository) -> None:
    assert repository.list_directories() == ["faq", "guides"]


def test_search_orders_by_score_then_path(repository: domain.DocRepository) -> None:
    result = domain.search_documents(repository, "VPN")
    assert result["totalMatched"] == 4
    assert [hit["path"] for hit in result["results"]] == [
        "guides/vpn-setup.md",
        "remote-work.md",
        # 以下 2 件は同点（スコア 1）。パス昇順で並ぶことを固定する
        "onboarding.md",
        "security-policy.md",
    ]
    assert [hit["score"] for hit in result["results"]] == [10, 5, 1, 1]


def test_and_search(repository: domain.DocRepository) -> None:
    result = domain.search_documents(repository, "障害 連絡")
    assert [hit["path"] for hit in result["results"]] == [
        "guides/incident-response.md",
        "onboarding.md",
        "remote-work.md",
    ]


def test_directory_filter_and_limit(repository: domain.DocRepository) -> None:
    faq = domain.search_documents(repository, "ロック", directory="faq")
    assert faq["totalMatched"] == 1
    assert faq["results"][0]["path"] == "faq/account-lock.md"

    limited = domain.search_documents(repository, "VPN", limit=2)
    assert limited["returned"] == 2
    assert limited["truncated"] is True


def test_invalid_input_raises(repository: domain.DocRepository) -> None:
    with pytest.raises(ValueError):
        domain.search_documents(repository, "   ")
    with pytest.raises(ValueError):
        domain.search_documents(repository, "VPN", directory="secret")
