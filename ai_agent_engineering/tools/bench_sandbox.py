#!/usr/bin/env python3
"""隔離実行の実測（往復のオーバーヘッド・上限の効き方）。セッション9の実測値の出典。"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentkit.sandbox import run_python  # noqa: E402


def main() -> None:
    print("=== 往復のオーバーヘッド（ファイル経由の依頼）===")
    for label, code in [("空のコード", "pass"),
                        ("print 1行", "print('x')"),
                        ("100万回の加算", "s=0\nfor i in range(1_000_000): s+=i\nprint(s)")]:
        lat = []
        for _ in range(5):
            t0 = time.perf_counter()
            r = run_python(code, timeout=30)
            lat.append((time.perf_counter() - t0) * 1000)
            if not r.ok:
                print(f"{label}: 失敗 — {r.error}")
                break
        else:
            print(f"{label:<16} 中央値 {statistics.median(lat):>7.0f}ms  "
                  f"最小 {min(lat):>7.0f}ms  最大 {max(lat):>7.0f}ms")

    print("\n=== 上限の効き方 ===")
    cases = [
        ("タイムアウト 2秒", "import time\ntime.sleep(30)", dict(timeout=2.0)),
        ("メモリ上限 64MB", "x = bytearray(400*1024*1024)", dict(memory_mb=64)),
        ("メモリ上限内 32MB", "x = bytearray(16*1024*1024)\nprint(len(x))", dict(memory_mb=64)),
        ("外部通信", "import socket\nsocket.setdefaulttimeout(3)\n"
                    "socket.create_connection(('1.1.1.1',53))", {}),
        ("rootfs への書き込み", "open('/etc/x','w')", {}),
        ("作業領域への書き込み", "open('bench.txt','w').write('ok')\nprint('ok')", {}),
    ]
    print(f"{'ケース':<24}{'結果':>8}  詳細")
    for label, code, kwargs in cases:
        t0 = time.perf_counter()
        r = run_python(code, **kwargs)
        dt = (time.perf_counter() - t0) * 1000
        detail = (r.content.strip() or "").splitlines()[:1]
        detail = detail[0] if detail else (r.error or "").splitlines()[:1]
        detail = detail if isinstance(detail, str) else (detail[0] if detail else "")
        print(f"{label:<24}{'成功' if r.ok else '失敗':>8}  {dt:>6.0f}ms  {detail[:60]}")


if __name__ == "__main__":
    main()
