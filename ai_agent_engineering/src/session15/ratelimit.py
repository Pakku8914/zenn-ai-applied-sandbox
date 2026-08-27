#!/usr/bin/env python3
"""セッション15：レート制限と、上限に当たったときの2つの作法。

    python src/session15/ratelimit.py

「1秒あたり N 回まで」を固定ウィンドウで表す。窓が変わったら使用数を0に戻す。
上限に当たったときの作法は2つある。

  ① 当たってから謝る … とりあえず呼ぶ。拒否されたら指数バックオフで待つ
  ② 手前で順番待ち   … 呼ぶ前に順番を取る。取れなければ次の窓まで待つ

①は拒否されたぶんが丸ごと無駄になる。②は無駄が出ない代わりに、
**行列を到着順にしないと後ろのワーカーが永久に通らない**（飢餓）。

待機は実時間では待たない。セッション11の `RecordingSleeper` に記録するだけである。
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
S11 = ROOT / "src" / "session11"
for _p in (str(ROOT), str(S11), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backoff import backoff_delay, delay_table  # noqa: E402  （セッション11）


def backoff_ticks(attempt: int) -> int:
    """セッション11の指数バックオフを1秒刻みに切り上げる。attempt は0始まり。

    0.5 → 1 / 1.0 → 1 / 2.0 → 2 / 4.0 → 4 / 8.0 → 8 と伸びる。
    """
    return max(1, math.ceil(backoff_delay(attempt)))


@dataclass
class RateLimit:
    """固定ウィンドウのレート制限。順番待ちの行列も持つ。

    limit … 1つの窓に通す回数
    fair  … True なら行列は到着順。False なら番号の若いワーカーを優先する
    """

    limit: int = 2
    window: int = 1
    fair: bool = True
    used: int = 0
    window_index: int = -1
    line: list[int] = field(default_factory=list)   # 順番待ちの行列（ワーカー番号）
    granted_total: int = 0
    rejected_total: int = 0

    # -- 共通 ---------------------------------------------------------------
    def _roll(self, t: int) -> None:
        """窓が変わったら使用数を0に戻す。"""
        index = t // self.window
        if index != self.window_index:
            self.window_index = index
            self.used = 0

    def wait_to_next_window(self, t: int) -> int:
        return (t // self.window + 1) * self.window - t

    # -- ①当たってから謝る --------------------------------------------------
    def take(self, t: int) -> bool:
        """並ばずに直接呼ぶ。False なら上限に当たった（＝この呼び出しは無駄になる）。"""
        self._roll(t)
        if self.used < self.limit:
            self.used += 1
            self.granted_total += 1
            return True
        self.rejected_total += 1
        return False

    # -- ②手前で順番待ち ----------------------------------------------------
    def join(self, t: int, worker: int) -> None:
        """順番待ちの行列に並ぶ。すでに並んでいれば何もしない（割り込ませない）。"""
        if worker not in self.line:
            self.line.append(worker)

    def leave(self, worker: int) -> None:
        """ジョブが消えた（キャンセル・クラッシュ）ワーカーを行列から外す。"""
        if worker in self.line:
            self.line.remove(worker)

    def serve(self, t: int) -> list[int]:
        """行列の先頭から limit 件に許可を出す。返り値は許可したワーカー番号。"""
        self._roll(t)
        order = list(self.line) if self.fair else sorted(self.line)
        granted: list[int] = []
        for worker in order:
            if self.used >= self.limit:
                break
            self.used += 1
            granted.append(worker)
        for worker in granted:
            self.line.remove(worker)
        self.granted_total += len(granted)
        return granted


def serve_demo(fair: bool, workers: int = 4, ticks: int = 6, limit: int = 2) -> list[int]:
    """全員が毎秒並び続けたとき、誰が何回通れたかを数える。"""
    rate = RateLimit(limit=limit, fair=fair)
    served = [0] * workers
    for t in range(ticks):
        for worker in range(workers):
            rate.join(t, worker)
        for worker in rate.serve(t):
            served[worker] += 1
    return served


def main() -> None:
    print("=== 指数バックオフをティック（1秒刻み）に切り上げる ===")
    print(delay_table(6))
    print("切り上げ（ティック）: " + " ".join(str(backoff_ticks(i)) for i in range(6)))

    print("\n=== 順番待ちの行列を到着順にするかどうか ===")
    print("4人が毎秒並ぶ / 上限 2回/秒 / 6秒間")
    print("方式 | w0 | w1 | w2 | w3")
    for label, fair in (("到着順に並べる（公平）", True), ("番号の若い順に通す（不公平）", False)):
        print(f"{label} | " + " | ".join(str(n) for n in serve_demo(fair)))
    print("※ 不公平な行列では w2 と w3 が1回も通らない。"
          "上限は守れているのに、後ろのジョブは永久に始まらない。")


if __name__ == "__main__":
    main()
