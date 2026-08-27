#!/usr/bin/env python3
"""セッション9の自己検証：隔離が実際に効いていること。

「隔離した」と書くだけでは意味がない。外に出られないこと・上限で殺されることを
テストで示す。tool-runner が起動していない場合は SKIP_RUNNER=1 で飛ばせる。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

if os.environ.get("SKIP_RUNNER") == "1":
    print("SKIP_RUNNER=1 のため隔離実行の検証を飛ばします。")
    sys.exit(0)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agentkit.sandbox import run_python  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


# --- 正常系 ---------------------------------------------------------------
r = run_python("print(sum(range(10)))")
check("コードが実行できる", r.ok and r.content.strip() == "45", r.content.strip() or (r.error or ""))

# --- ネットワーク遮断 -----------------------------------------------------
net = run_python(
    "import socket\n"
    "socket.setdefaulttimeout(3)\n"
    "try:\n"
    "    socket.create_connection(('1.1.1.1', 53))\n"
    "    print('CONNECTED')\n"
    "except OSError as e:\n"
    "    print('BLOCKED', type(e).__name__)\n"
)
check("外部への TCP 接続が失敗する",
      net.ok and "BLOCKED" in net.content, net.content.strip() or (net.error or ""))

dns = run_python(
    "import socket\n"
    "try:\n"
    "    print('RESOLVED', socket.gethostbyname('example.com'))\n"
    "except OSError as e:\n"
    "    print('BLOCKED', type(e).__name__)\n"
)
check("名前解決も失敗する", dns.ok and "BLOCKED" in dns.content,
      dns.content.strip() or (dns.error or ""))

# --- タイムアウト ---------------------------------------------------------
slow = run_python("import time\ntime.sleep(30)\nprint('done')", timeout=2.0)
check("タイムアウトで打ち切られる",
      (not slow.ok) and "タイムアウト" in (slow.error or ""), slow.error or "")

# --- メモリ上限 -----------------------------------------------------------
mem = run_python("x = bytearray(400 * 1024 * 1024)\nprint(len(x))", memory_mb=64)
check("メモリ上限で失敗する", not mem.ok, (mem.error or "")[:80])

# --- 書き込み境界 ---------------------------------------------------------
inside = run_python("open('ok.txt', 'w').write('hello')\nprint('WROTE')")
check("作業領域には書ける", inside.ok and "WROTE" in inside.content,
      inside.content.strip() or (inside.error or ""))

outside = run_python(
    "try:\n"
    "    open('/etc/passwd', 'a').write('x')\n"
    "    print('WROTE')\n"
    "except OSError as e:\n"
    "    print('DENIED', type(e).__name__)\n"
)
check("読み取り専用領域には書けない",
      outside.ok and "DENIED" in outside.content, outside.content.strip() or (outside.error or ""))

# --- 秘密情報が渡っていない -----------------------------------------------
env = run_python("import os\nprint(sorted(os.environ))")
check("ANTHROPIC_API_KEY が子プロセスに渡っていない",
      env.ok and "ANTHROPIC_API_KEY" not in env.content, env.content.strip()[:120])

# --- ワーカーが死んでいない（連続実行できる）------------------------------
again = run_python("print('alive')")
check("上限に当たった後もワーカーが生きている", again.ok and "alive" in again.content,
      again.content.strip() or (again.error or ""))

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション9の検証はすべて成功しました。")
