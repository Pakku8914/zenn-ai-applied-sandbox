#!/usr/bin/env python3
"""問題8の解答例：起動時取得の失敗モードを固定するテスト（セッション7）。

  docker compose exec app python -m pytest src/session07/test_fetch_weights.py -q

ネットワークには出ない。`opener`（取得）と `sleep`（待ち）を差し替えて、
時間にも回線にも依存しない形で検証する。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.session07.fetch_weights import (  # noqa: E402
    FetchPlan, HttpError, fetch_waves, fetch_with_retry, herd_mb, sha256_bytes,
)

PAYLOAD = b"weights-v1"
DIGEST = sha256_bytes(PAYLOAD)
Q4_K_M_MB = 379.4  # 2026-08-15 実測


def test_retries_with_exponential_backoff(tmp_path: Path) -> None:
    """2回失敗して3回目で成功する。待ち時間は 0.5 → 1.0 と倍になる。"""
    calls = {"n": 0}
    slept: list[float] = []

    def flaky(url: str) -> bytes:
        calls["n"] += 1
        if calls["n"] < 3:
            raise HttpError(503, url)
        return PAYLOAD

    dest = tmp_path / "weights" / "model.gguf"
    result = fetch_with_retry(FetchPlan("http://store/model.gguf", dest, DIGEST),
                              opener=flaky, sleep=slept.append)

    assert result.ok and result.attempts == 3
    assert slept == [0.5, 1.0]
    assert dest.read_bytes() == PAYLOAD
    # 一時ファイルを残さない（次の起動で中途半端なファイルを読ませない）
    assert not (dest.parent / "model.gguf.part").exists()


def test_checksum_mismatch_keeps_previous_file(tmp_path: Path) -> None:
    """壊れたものが来たら、いま動いているファイルに触らない。"""
    dest = tmp_path / "model.gguf"
    dest.write_bytes(PAYLOAD)

    result = fetch_with_retry(FetchPlan("http://store/model.gguf", dest, "f" * 64),
                              opener=lambda url: b"broken", sleep=lambda _: None)

    assert not result.ok and "チェックサム" in result.reason
    assert dest.read_bytes() == PAYLOAD


def test_permanent_failure_gives_up_immediately(tmp_path: Path) -> None:
    """404 はリトライしない。待っても直らない失敗で起動を引き延ばさない。"""
    slept: list[float] = []

    def gone(url: str) -> bytes:
        raise HttpError(404, url)

    result = fetch_with_retry(
        FetchPlan("http://store/none.gguf", tmp_path / "none.gguf", DIGEST),
        opener=gone, sleep=slept.append)

    assert not result.ok and result.attempts == 1
    assert slept == []
    assert not (tmp_path / "none.gguf").exists()


def test_herd_is_split_into_waves() -> None:
    """レプリカ20本・同時5本なら4波。合計転送量はレプリカ数に比例する。"""
    assert fetch_waves(20, 5) == 4
    # 浮動小数点の比較は丸めてから行う（== で書くと環境によって落ちる）
    assert round(herd_mb(20, Q4_K_M_MB), 1) == 7588.0
