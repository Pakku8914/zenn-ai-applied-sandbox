"""共通データ（data/recipes.json・data/users.json）の読み込み。3冊で同じファイルを使う。"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from kondate.settings import get_settings

# 共通データの SHA256 先頭12桁（シード 20261002 で決定的に生成。series-contract §2）
EXPECTED_SHA12 = {"recipes.json": "aa67705b432a", "users.json": "23afe5fd389f"}


def data_path(name: str) -> Path:
    return Path(get_settings().data_dir) / name


def sha12(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


@lru_cache
def load_recipes() -> tuple[dict, ...]:
    return tuple(json.loads(data_path("recipes.json").read_text(encoding="utf-8")))


@lru_cache
def load_users() -> tuple[dict, ...]:
    return tuple(json.loads(data_path("users.json").read_text(encoding="utf-8")))
