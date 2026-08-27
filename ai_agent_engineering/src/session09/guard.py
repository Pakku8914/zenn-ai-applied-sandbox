#!/usr/bin/env python3
"""隔離環境へ入る扉を1つに絞る（セッション9）。

`run_python` を呼ぶ場所を増やすと、上限・監査・後片付けが場所ごとにばらける。
この章では「アプリのコードは必ず run_guarded を通る」という規約を置く。

    python src/session09/guard.py
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentkit.clock import FixedClock  # noqa: E402
from agentkit.sandbox import run_python  # noqa: E402

MAX_TIMEOUT = 10.0        # 1回の実行に許す最長時間（秒）
MAX_MEMORY_MB = 128       # 1回の実行に許すメモリ（MB）
MAX_OUTPUT_CHARS = 2000   # モデルに戻す標準出力の上限（文字）
AUDIT_PATH = ROOT / "traces" / "session09_exec.jsonl"


# --- 上限の検査（問題6でここを自分で書く）----------------------------------
def check_limits(timeout: float, memory_mb: int) -> None:
    """上限を超える依頼を、実行する前に断る。

    黙って上限まで切り下げないのは、呼び出し側の思い違いを隠さないため。
    """
    if not 0 < timeout <= MAX_TIMEOUT:
        raise ValueError(
            f"timeout は 0 より大きく {MAX_TIMEOUT} 秒以下にしてください（指定: {timeout}）")
    if not 0 < memory_mb <= MAX_MEMORY_MB:
        raise ValueError(
            f"memory_mb は 0 より大きく {MAX_MEMORY_MB} MB 以下にしてください（指定: {memory_mb}）")


@dataclass
class ExecBudget:
    """1タスクで許すコード実行の総量。上限に達したら実行せずに断る。"""

    max_calls: int = 5
    max_seconds: float = 20.0
    calls: int = 0
    seconds: float = 0.0

    def check(self, timeout: float) -> str | None:
        """断る理由を返す（実行してよければ None）。"""
        if self.calls >= self.max_calls:
            return f"実行回数の上限に達しました（{self.calls} / {self.max_calls} 回）"
        if self.seconds + timeout > self.max_seconds:
            return (f"実行時間の予算を超えます（消費 {self.seconds:.1f} 秒 ＋ 最悪 "
                    f"{timeout:.1f} 秒 > 上限 {self.max_seconds:.1f} 秒）")
        return None

    def record(self, elapsed: float) -> None:
        self.calls += 1
        self.seconds += elapsed


# --- 出力の受け取り ---------------------------------------------------------
def clip_stdout(text: str, limit: int = MAX_OUTPUT_CHARS) -> tuple[str, int]:
    """標準出力を上限で切り、捨てた文字数を返す。"""
    if len(text) <= limit:
        return text, 0
    return text[:limit], len(text) - limit


def notice(dropped: int) -> str:
    """モデルに見せる省略の断り書き。捨てたことを隠さない。"""
    if dropped <= 0:
        return ""
    return (f"\n…（残り {dropped} 文字は省略しました。"
            "全量が必要なら作業領域にファイルとして保存してください）")


# --- 監査 -------------------------------------------------------------------
def audit_record(*, code: str, timeout: float, memory_mb: int, ok: bool,
                 label: str, elapsed_ms: int) -> dict:
    """監査に残す1件。コード本文は残さず、指紋（ハッシュ）と長さだけを残す。

    コードには利用者が貼った値がそのまま入りうる。監査ログは長く残るので、
    「あとで消せない場所に秘密を書かない」を既定にする。
    """
    return {"label": label,
            "code_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest()[:16],
            "code_chars": len(code),
            "timeout": timeout, "memory_mb": memory_mb, "ok": ok,
            "elapsed_ms": elapsed_ms,
            "at": FixedClock().now().isoformat()}


def append_audit(record: dict) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# --- 唯一の入口 -------------------------------------------------------------
def run_guarded(code: str, *, timeout: float = 10.0, memory_mb: int = 128,
                budget: ExecBudget | None = None, label: str = "") -> dict:
    """隔離環境でコードを実行する唯一の入口。

    ここでコードの中身は検査しない（文字列検査は破られる。looks_dangerous 参照）。
    守るのは「時間・メモリ・回数・出力量」という外側から測れる量だけである。
    """
    check_limits(timeout, memory_mb)
    if budget is not None:
        refused = budget.check(timeout)
        if refused:
            return {"ok": False, "stdout": "", "dropped": 0, "error": refused,
                    "refused": refused, "audit": None}

    started = time.perf_counter()
    res = run_python(code, timeout=timeout, memory_mb=memory_mb)
    elapsed = time.perf_counter() - started
    if budget is not None:
        budget.record(elapsed)

    stdout, dropped = clip_stdout(res.content or "")
    record = audit_record(code=code, timeout=timeout, memory_mb=memory_mb, ok=res.ok,
                          label=label, elapsed_ms=int(elapsed * 1000))
    append_audit(record)
    return {"ok": res.ok, "stdout": stdout, "dropped": dropped, "error": res.error,
            "refused": None, "audit": record}


# --- Bad：コードの文字列を見て危険を判定しようとする ------------------------
DANGEROUS = ("import socket", "import os", "open(", "subprocess", "__import__")


def looks_dangerous(code: str) -> str | None:
    """危険そうな文字列を探す。**この方式は破られる**ことを示すために置いてある。"""
    for pattern in DANGEROUS:
        if pattern in code:
            return pattern
    return None


# 文字列検査は通り抜けるが、境界は通り抜けられないコード
BYPASS_NETWORK = (
    "src = 'imp' + 'ort socket'\n"
    "exec(src)\n"
    "socket.setdefaulttimeout(3)\n"
    "try:\n"
    "    socket.create_connection(('1.1.1.1', 53))\n"
    "    print('CONNECTED')\n"
    "except OSError as e:\n"
    "    print('BLOCKED', type(e).__name__)\n"
)

# 文字列検査も境界も通り抜けるコード（読み取りは元々禁止していない）
BYPASS_READ = (
    "from pathlib import Path\n"
    "print(len(Path('/etc/passwd').read_text(encoding='utf-8')) > 0)\n"
)


BYPASS_CASES = [
    ("import socket をそのまま書く", "import socket\nprint('ok')\n"),
    ("exec で組み立てる（BYPASS_NETWORK）", BYPASS_NETWORK),
    ("ファイルを読む（BYPASS_READ）", BYPASS_READ),
]


def render_bypass() -> str:
    lines = ["=== 文字列検査（Bad）と境界（Good）の比較 ===",
             "コード | 文字列検査 | 隔離環境での結果"]
    for name, code in BYPASS_CASES:
        hit = looks_dangerous(code)
        judged = f"止めた（{hit}）" if hit else "通した"
        result = run_guarded(code, timeout=6.0, label="bypass")
        observed = (result["stdout"] or "").strip().splitlines()
        observed = observed[-1] if observed else (result["error"] or "")[:30]
        lines.append(f"{name} | {judged} | {observed}")
    return "\n".join(lines)


def main() -> None:
    ok = run_guarded("print(sum(range(10)))", label="demo")
    audit_text = json.dumps(ok["audit"], ensure_ascii=False)
    print("=== 入口を通した実行 ===")
    print(f"ok={ok['ok']} stdout={ok['stdout'].strip()!r} "
          f"監査にコード本文が入っている={'print' in audit_text} "
          f"指紋の桁数={len(ok['audit']['code_sha256'])}")

    print("\n=== 上限の検査 ===")
    for timeout, memory_mb in ((0, 128), (30.0, 128), (10.0, 512)):
        try:
            check_limits(timeout, memory_mb)
            print(f"timeout={timeout} memory_mb={memory_mb} → 通した")
        except ValueError as exc:
            print(f"timeout={timeout} memory_mb={memory_mb} → 断った: {exc}")

    print("\n=== 予算 ===")
    budget = ExecBudget(max_calls=2, max_seconds=20.0)
    for i in range(3):
        res = run_guarded("print('computed')", timeout=5.0, budget=budget, label=f"budget-{i}")
        print(f"{i + 1} 回目: ok={res['ok']} refused={res['refused']}")

    print()
    print(render_bypass())


if __name__ == "__main__":
    main()
