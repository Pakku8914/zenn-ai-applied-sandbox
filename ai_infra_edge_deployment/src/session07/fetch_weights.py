#!/usr/bin/env python3
"""起動時に重みを取得する（方式③）ときの中身（セッション7）。

ネットワークに触らずに試せるよう、取得そのものを差し替えられるようにしてある
（`opener` を渡す）。既定は `file://` と `http(s)://` の両方を扱う urllib。

ここで扱う失敗モードは4つ。**方式③を選ぶなら、この4つに全部答えられること
が条件**である。

  1. 途中で切れた   → 中途半端なファイルを本番のパスに置かない（.part + rename）
  2. 中身が違う     → サイズが合っていても壊れていることがある（チェックサム）
  3. 一時的な失敗   → 5xx・429・408 はリトライする。404・403 は何度やっても直らない
  4. 一斉に起動した → レプリカ数ぶんの取得が同時に走り、取得先を飽和させる

使い方（小さなファイルで挙動を確かめる）:

    docker compose exec app python src/session07/fetch_weights.py
    docker compose exec app python src/session07/fetch_weights.py --corrupt
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

RETRYABLE_STATUS = (408, 425, 429, 500, 502, 503, 504)
"""リトライしてよいステータス。ここに無いものは待っても直らない。"""


class HttpError(Exception):
    """取得先が返したエラー。status でリトライの可否を判断する。"""

    def __init__(self, status: int, url: str = "") -> None:
        super().__init__(f"HTTP {status} {url}".strip())
        self.status = status


def should_retry(status: int) -> bool:
    """このステータスはリトライして意味があるか。

    404（無い）・403（権限がない）をリトライし続けるのは、起動を失敗させる
    代わりに起動を「遅く失敗させる」だけである。すぐ諦めて落とすほうがよい。
    """
    return status in RETRYABLE_STATUS


def backoff_delays(attempts: int, base: float = 0.5, factor: float = 2.0) -> list[float]:
    """リトライの待ち時間の並び。

    **ジッタを入れていないので決定的に検証できる。** 実運用ではここに乱数の
    ジッタを足す（全レプリカが同じ秒に再試行して取得先を叩くのを防ぐため）。
    """
    return [base * factor ** i for i in range(max(attempts - 1, 0))]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path, chunk: int = 1024 * 1024) -> str:
    """大きなファイルでもメモリに載せずにダイジェストを取る。"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class FetchPlan:
    url: str
    dest: Path
    sha256: str
    attempts: int = 3
    base_delay_s: float = 0.5


@dataclass(frozen=True)
class FetchResult:
    ok: bool
    attempts: int
    bytes_written: int
    reason: str = ""


def default_opener(url: str) -> bytes:
    with urllib.request.urlopen(url) as res:  # noqa: S310
        status = int(getattr(res, "status", 200) or 200)
        if status >= 400:
            raise HttpError(status, url)
        return res.read()


def fetch_with_retry(plan: FetchPlan,
                     opener: Callable[[str], bytes] = default_opener,
                     sleep: Callable[[float], None] = time.sleep) -> FetchResult:
    """重みを取得して検証し、成功したときだけ本番のパスに置く。

    - 取得先が一時的な失敗を返したらリトライする（指数バックオフ）
    - チェックサムが合わなければ**本番のパスに触らない**（前のファイルを守る）
    - 書き込みは `.part` に落として `os.replace` で差し替える（原子的）
    """
    delays = backoff_delays(plan.attempts, plan.base_delay_s)
    tmp = plan.dest.with_suffix(plan.dest.suffix + ".part")
    plan.dest.parent.mkdir(parents=True, exist_ok=True)
    for index in range(plan.attempts):
        last = index == plan.attempts - 1
        try:
            data = opener(plan.url)
        except HttpError as exc:
            if not should_retry(exc.status):
                return FetchResult(False, index + 1, 0,
                                   f"リトライしない失敗: {exc}")
            if last:
                return FetchResult(False, index + 1, 0, f"リトライ上限: {exc}")
            sleep(delays[index])
            continue
        except OSError as exc:
            if last:
                return FetchResult(False, index + 1, 0, f"リトライ上限: {exc}")
            sleep(delays[index])
            continue

        digest = sha256_bytes(data)
        if digest != plan.sha256:
            tmp.unlink(missing_ok=True)
            return FetchResult(False, index + 1, 0,
                               f"チェックサム不一致: 期待 {plan.sha256[:12]} / "
                               f"実際 {digest[:12]}")
        tmp.write_bytes(data)
        os.replace(tmp, plan.dest)  # 同じファイルシステム内なら原子的に入れ替わる
        return FetchResult(True, index + 1, len(data))
    return FetchResult(False, plan.attempts, 0, "attempts が 0 以下です")


def fetch_waves(replicas: int, max_parallel: int) -> int:
    """同時取得数に上限をかけたとき、何波に分かれるか。"""
    if replicas <= 0 or max_parallel <= 0:
        raise ValueError("replicas と max_parallel は 1 以上を指定してください")
    return math.ceil(replicas / max_parallel)


def herd_mb(replicas: int, weights_mb: float) -> float:
    """一斉起動でネットワークに流れる合計（MB）。"""
    return replicas * weights_mb


def _demo(src: Path, dest: Path, corrupt: bool) -> int:
    expected = sha256_file(src)
    if corrupt:
        expected = "0" * 64  # 壊れたファイルが来た状況を模す
    plan = FetchPlan(url=src.resolve().as_uri(), dest=dest, sha256=expected)
    before = dest.read_bytes() if dest.exists() else None
    result = fetch_with_retry(plan)
    print(f"取得元       : {plan.url}")
    print(f"保存先       : {dest}")
    print(f"期待ダイジェスト: {expected[:12]}...")
    print(f"結果         : {'成功' if result.ok else '失敗'}"
          f"（試行 {result.attempts} 回 / {result.bytes_written} バイト）")
    if result.reason:
        print(f"理由         : {result.reason}")
    if before is not None:
        kept = dest.read_bytes() == before
        print(f"失敗時に前のファイルを守れたか: {'はい' if kept or result.ok else 'いいえ'}")
    return 0 if result.ok or corrupt else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="重みの取得（file:// で挙動を確認する）")
    parser.add_argument("--src", default="requirements.txt",
                        help="取得元のファイル（既定は小さなファイル）")
    parser.add_argument("--dest", default="/tmp/session07/fetched.bin")
    parser.add_argument("--corrupt", action="store_true",
                        help="チェックサムを故意に外して失敗時の動きを見る")
    args = parser.parse_args()
    return _demo(Path(args.src), Path(args.dest), args.corrupt)


if __name__ == "__main__":
    raise SystemExit(main())
