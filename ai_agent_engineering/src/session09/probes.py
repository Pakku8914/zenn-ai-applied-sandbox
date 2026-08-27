#!/usr/bin/env python3
"""隔離の境界を1本ずつプローブで確かめる（セッション9）。

「隔離しました」と書くだけでは何も保証されない。境界ごとに
  ① compose のどの指定で守っているか
  ② 破れていないことをどう観測するか
を1行に並べ、期待と観測が一致するかで判定する。

    python src/session09/probes.py     # 全行 OK なら終了コード 0

境界そのものを試す実験なので、ここでは例外的に run_python を直接呼ぶ
（アプリのコードは必ず guard.run_guarded を通す）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentkit.models import ToolResult  # noqa: E402
from agentkit.sandbox import run_python  # noqa: E402


# --- 観測の読み方 -----------------------------------------------------------
def stdout_of(res: ToolResult) -> str:
    """標準出力をそのまま観測にする。"""
    return (res.content or "").strip()


def failure_of(res: ToolResult) -> str:
    """失敗の種類を短い語に正規化する。

    生の標準エラーにはジョブIDを含むパスが混ざるので、表にそのまま出さない。
    """
    if res.ok:
        return "成功してしまった"
    err = res.error or ""
    for word in ("タイムアウト", "MemoryError", "PermissionError", "OSError"):
        if word in err:
            return f"失敗（{word}）"
    return "失敗（その他）"


# --- プローブ（隔離環境の中で走らせるコード）--------------------------------
CODE_OK = "print(sum(range(10)))"

CODE_TCP = (
    "import socket\n"
    "socket.setdefaulttimeout(3)\n"
    "try:\n"
    "    socket.create_connection(('1.1.1.1', 53))\n"
    "    print('CONNECTED')\n"
    "except OSError as e:\n"
    "    print('BLOCKED', type(e).__name__)\n"
)

CODE_DNS = (
    "import socket\n"
    "try:\n"
    "    print('RESOLVED', socket.gethostbyname('example.com'))\n"
    "except OSError as e:\n"
    "    print('BLOCKED', type(e).__name__)\n"
)

CODE_DATA = (
    "import os\n"
    "print(os.path.exists('/workspace/data/employees.jsonl'))\n"
)

CODE_ROOTFS = (
    "try:\n"
    "    open('/etc/passwd', 'a').write('x')\n"
    "    print('WROTE')\n"
    "except OSError:\n"
    "    print('DENIED')\n"
)

CODE_WORK = (
    "from pathlib import Path\n"
    "Path('probe_work.txt').write_text('ok', encoding='utf-8')\n"
    "print('WROTE', Path('probe_work.txt').read_text(encoding='utf-8'))\n"
)

CODE_TMP = (
    "from pathlib import Path\n"
    "Path('/tmp/probe.txt').write_text('ok', encoding='utf-8')\n"
    "print('WROTE')\n"
)

CODE_MEM_OVER = "x = bytearray(400 * 1024 * 1024)\nprint(len(x))"
CODE_MEM_IN = "x = bytearray(16 * 1024 * 1024)\nprint(len(x))"
CODE_SLEEP = "import time\ntime.sleep(30)\nprint('起きた')"

CODE_RLIMIT_AS = "import resource\nprint(resource.getrlimit(resource.RLIMIT_AS)[0])"
CODE_RLIMIT_NPROC = "import resource\nprint(resource.getrlimit(resource.RLIMIT_NPROC)[0])"
CODE_RLIMIT_FSIZE = "import resource\nprint(resource.getrlimit(resource.RLIMIT_FSIZE)[0])"

CODE_SECRET = (
    "import os\n"
    "words = ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')\n"
    "risky = [k for k in os.environ if any(w in k.upper() for w in words)]\n"
    "print('NO_SECRET' if not risky else 'LEAKED ' + ','.join(sorted(risky)))\n"
)

CODE_UID = "import os\nprint(os.getuid())"

# (境界, 守っている指定, コード, run_python の引数, 観測の読み方, 期待)
PROBES = [
    ("実行できる（正常系）", "—", CODE_OK, {}, stdout_of, "45"),
    ("外部への TCP 接続", "network_mode: none", CODE_TCP, {}, stdout_of, "BLOCKED OSError"),
    ("名前解決", "network_mode: none", CODE_DNS, {}, stdout_of, "BLOCKED gaierror"),
    ("業務データが見えない", "volumes（workspace だけを渡す）", CODE_DATA, {}, stdout_of, "False"),
    ("rootfs への書き込み", "read_only: true", CODE_ROOTFS, {}, stdout_of, "DENIED"),
    ("作業領域への書き込み", "volumes: ./workspace:/work", CODE_WORK, {}, stdout_of, "WROTE ok"),
    ("一時領域への書き込み", "tmpfs: /tmp", CODE_TMP, {}, stdout_of, "WROTE"),
    ("メモリ上限を超える確保", "mem_limit + RLIMIT_AS", CODE_MEM_OVER, {"memory_mb": 64},
     failure_of, "失敗（MemoryError）"),
    ("メモリ上限内の確保", "mem_limit + RLIMIT_AS", CODE_MEM_IN, {"memory_mb": 64},
     stdout_of, "16777216"),
    ("実行時間の上限", "run_python(timeout=...)", CODE_SLEEP, {"timeout": 2.0},
     failure_of, "失敗（タイムアウト）"),
    ("子プロセスのメモリ上限", "worker の RLIMIT_AS", CODE_RLIMIT_AS, {"memory_mb": 64},
     stdout_of, "67108864"),
    ("子プロセスのプロセス数上限", "pids_limit + RLIMIT_NPROC", CODE_RLIMIT_NPROC, {},
     stdout_of, "32"),
    ("生成物のサイズ上限", "worker の RLIMIT_FSIZE", CODE_RLIMIT_FSIZE, {},
     stdout_of, "16777216"),
    ("秘密情報の遮断", "worker が env を絞る", CODE_SECRET, {}, stdout_of, "NO_SECRET"),
    ("実行ユーザー（いまは root）", "user: 未設定", CODE_UID, {}, stdout_of, "0"),
]


def probe_all() -> list[dict]:
    """全プローブを順に走らせ、判定つきの行を返す。"""
    rows: list[dict] = []
    for boundary, directive, code, kwargs, reader, expect in PROBES:
        res = run_python(code, **kwargs)
        observed = reader(res)
        rows.append({"境界": boundary, "指定": directive, "期待": expect,
                     "観測": observed, "ok": observed == expect})
    # 後片付け（プローブが作ったファイルを残さない）
    (ROOT / "workspace" / "probe_work.txt").unlink(missing_ok=True)
    return rows


def render(rows: list[dict]) -> str:
    ok = sum(1 for r in rows if r["ok"])
    lines = [f"=== 隔離の境界（{len(rows)} 本のプローブ）===",
             "判定 | 境界 | 守っている指定 | 観測"]
    for r in rows:
        lines.append(f"{'OK' if r['ok'] else 'NG'} | {r['境界']} | {r['指定']} | {r['観測']}")
        if not r["ok"]:
            lines.append(f"     期待: {r['期待']}")
    lines.append(f"{ok} / {len(rows)} OK")
    return "\n".join(lines)


def main() -> None:
    rows = probe_all()
    print(render(rows))
    if any(not r["ok"] for r in rows):
        sys.exit(1)


if __name__ == "__main__":
    main()
