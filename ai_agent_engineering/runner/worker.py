#!/usr/bin/env python3
"""隔離実行ワーカー（tool-runner コンテナの中で動く）。

/queue にファイルとして届いた依頼を実行し、結果をファイルで返す。
ネットワークを持たないコンテナなので、通信手段はファイルだけである。

依存ライブラリを一切使わない（標準ライブラリのみ）。攻撃に使える道具を置かないため。
"""

from __future__ import annotations

import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

QUEUE = Path("/queue")
WORK = Path("/work")
POLL_INTERVAL = 0.05


def limit_child(memory_mb: int) -> None:
    """子プロセス側で資源上限を掛ける。

    コンテナ全体の mem_limit だけに頼るとワーカー自身が OOM で殺され、
    以降の依頼を受けられなくなる。子プロセスだけを殺せるようにする。
    """
    limit = memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))


def handle(req_path: Path) -> None:
    job_id = req_path.name.removesuffix(".req.json")
    res_path = QUEUE / f"{job_id}.res.json"
    try:
        payload = json.loads(req_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        res_path.write_text(json.dumps({"ok": False, "error": f"依頼を読めません: {exc}"},
                                       ensure_ascii=False), encoding="utf-8")
        req_path.unlink(missing_ok=True)
        return

    code = payload.get("code", "")
    timeout = float(payload.get("timeout", 10.0))
    memory_mb = int(payload.get("memory_mb", 128))

    script = WORK / f".job_{job_id}.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(code, encoding="utf-8")

    started = time.perf_counter()
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=timeout, cwd=str(WORK),
            preexec_fn=lambda: limit_child(memory_mb),  # noqa: PLW1509
            # 秘密情報を子プロセスへ渡さない（環境変数を絞る）
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(WORK),
                 "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        result = {"ok": False, "stdout": out,
                  "error": f"タイムアウト（{timeout} 秒）で打ち切りました"}
    else:
        elapsed = time.perf_counter() - started
        if proc.returncode == 0:
            result = {"ok": True, "stdout": proc.stdout, "elapsed": round(elapsed, 3)}
        else:
            # 資源上限に当たった場合はここに来る（MemoryError / 負の returncode）
            result = {"ok": False, "stdout": proc.stdout,
                      "error": (proc.stderr or "").strip()[-500:]
                      or f"終了コード {proc.returncode}",
                      "elapsed": round(elapsed, 3)}
    finally:
        script.unlink(missing_ok=True)

    tmp = QUEUE / f"{job_id}.res.tmp"
    tmp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    tmp.rename(res_path)
    req_path.unlink(missing_ok=True)


def main() -> None:
    QUEUE.mkdir(parents=True, exist_ok=True)
    print(f"[worker] 起動しました（queue={QUEUE}, work={WORK}, uid={os.getuid()}）", flush=True)
    while True:
        for req in sorted(QUEUE.glob("*.req.json")):
            handle(req)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
