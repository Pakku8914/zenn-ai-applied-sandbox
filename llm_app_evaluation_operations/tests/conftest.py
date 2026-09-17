"""pytest 共通設定。

APIキーが無い環境でもテストスイート全体が緑になることを最優先にしている。
実 API を叩くテストは `@pytest.mark.live` を付け、キーが無ければ自動でスキップする。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from evalkit.client import RecordedClient
from evalkit.dataset import load_dataset

BASE_DIR = Path(__file__).resolve().parent.parent
DATASET_PATH = BASE_DIR / "datasets" / "faq_v1.jsonl"
CASSETTE_PATH = BASE_DIR / "recordings" / "faq_v1.json"


def pytest_collection_modifyitems(config, items):
    """APIキーが無い場合は live マーカー付きのテストをスキップする。"""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    skip_live = pytest.mark.skip(reason="ANTHROPIC_API_KEY が未設定のためスキップ")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture(scope="session")
def dataset():
    """評価データセット（全ケース）。"""
    return load_dataset(DATASET_PATH)


@pytest.fixture
def replay_client():
    """カセットを再生するクライアント（APIキー不要・課金なし）。"""
    return RecordedClient(CASSETTE_PATH)
