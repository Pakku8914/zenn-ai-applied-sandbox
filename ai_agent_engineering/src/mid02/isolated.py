#!/usr/bin/env python3
"""隔離環境での集計（S09 の再利用）。

    python src/mid02/isolated.py     # 集計を1回流して結果を表示する

S09 では3択（許さない／限定的に許す／隔離して許す）を判断した。この章の答えは
**「限定的に許す」＋「それでも隔離して動かす」**である。

  - 任意コードはモデルに書かせない（`run_python` をツールとして持たせない）
  - 流すのは、状態が持っている**1つの固定されたコード**（`SUMMARY_CODE`）だけ
  - それでも隔離コンテナで動かす（ネットワークなし・読み取り専用・資源上限）

理由は副作用の重さである。この章のエージェントは金額の申請と社外に届く送信を扱う。
「集計のために任意コードを書ける」道具を同じ走行の中に置くと、注入された指示が
コード経由で出口を作れてしまう（S12 の「知っている出口しか塞げない」）。

もう1つの要点は、隔離環境に**業務データを持ち込まない**ことである。`tool-runner` には
`data/` をマウントしていない。渡すのは「渡してよい列だけ」に絞った CSV である。
氏名も社員IDも渡さない。渡していないものは漏れない。
"""

from __future__ import annotations

import shutil

from _paths import setup

ROOT = setup()

from agentkit.biztools import WORKSPACE  # noqa: E402
from agentkit.sandbox import run_python  # noqa: E402
from guard import run_guarded  # noqa: E402  (S09：隔離環境へ入る唯一の入口)

from ledger import expenses  # noqa: E402

INPUT_APP = WORKSPACE / "mid02" / "input" / "expenses.csv"
INPUT_RUNNER = "/work/mid02/input/expenses.csv"
OUT_APP = WORKSPACE / "mid02" / "out"
OUT_RUNNER = "/work/mid02/out"

TIMEOUT = 6.0
MEMORY_MB = 64

# 隔離環境で流す唯一のコード。モデルは1文字も書けない
SUMMARY_CODE = (
    "import csv\n"
    "from pathlib import Path\n"
    f"rows = list(csv.DictReader(open({INPUT_RUNNER!r}, encoding='utf-8')))\n"
    "total = sum(int(r['amount']) for r in rows)\n"
    "over = sum(1 for r in rows if int(r['amount']) >= 50000)\n"
    "by = {}\n"
    "for r in rows:\n"
    "    by[r['category']] = by.get(r['category'], 0) + int(r['amount'])\n"
    "lines = ['category,amount'] + [f\"{k},{by[k]}\" for k in sorted(by)]\n"
    "Path('summary.csv').write_text('\\n'.join(lines) + '\\n', encoding='utf-8')\n"
    "print(f'件数={len(rows)} 合計={total} 5万円以上={over}')\n"
    "for k in sorted(by):\n"
    "    print(f'{k}={by[k]}')\n"
)

_available: bool | None = None


def available(force: bool = False) -> bool:
    """隔離実行が使えるかを1回だけ確かめる。

    `SKIP_RUNNER=1` のときは確かめずに「使えない」とする（S09 の verify と同じ約束）。
    使えない場合でも走行は続けられるようにしてある。集計だけが付かない。
    """
    global _available
    import os  # noqa: PLC0415

    if os.environ.get("SKIP_RUNNER") == "1":
        return False
    if _available is None or force:
        probe = run_python("print('probe')", timeout=2.0)
        _available = bool(probe.ok and "probe" in probe.content)
    return _available


def write_input() -> int:
    """隔離環境へ渡す CSV を書く。**区分と金額だけ**にする（氏名・社員IDは渡さない）。"""
    rows = expenses()
    INPUT_APP.parent.mkdir(parents=True, exist_ok=True)
    lines = ["category,amount"]
    lines += [f"{r['category']},{int(r['amount'])}" for r in rows]
    INPUT_APP.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(rows)


def prelude(job: str) -> str:
    """相対パスの書き込みをジョブ用ディレクトリに落とす（S09 と同じ作法）。"""
    job_dir = f"{OUT_RUNNER}/{job}"
    return ("import os\n"
            f"os.makedirs({job_dir!r}, exist_ok=True)\n"
            f"os.chdir({job_dir!r})\n")


def reset(job: str) -> None:
    """前回の生成物を消す（古いファイルを成果と誤認しないため）。"""
    shutil.rmtree(OUT_APP / job, ignore_errors=True)


def compute_summary(job: str = "demo") -> dict:
    """区分別の集計を隔離環境で計算する。

    戻り値の `reference` は `read_file` がそのまま読める作業領域の相対パスである。
    生成物の本文をモデルの文脈に流し込まない（S07・S09 の「参照だけを渡す」）。
    """
    if not available():
        return {"ok": False, "stdout": "", "reference": "", "rows": 0,
                "error": "隔離実行が使えません（tool-runner が起動していないか SKIP_RUNNER=1）"}
    count = write_input()
    reset(job)
    result = run_guarded(prelude(job) + SUMMARY_CODE, timeout=TIMEOUT,
                         memory_mb=MEMORY_MB, label=f"mid02:summary:{job}")
    produced = OUT_APP / job / "summary.csv"
    return {"ok": bool(result["ok"] and produced.exists()),
            "stdout": (result["stdout"] or "").strip(),
            "reference": f"mid02/out/{job}/summary.csv" if produced.exists() else "",
            "rows": count,
            "error": result["error"]}


def main() -> None:
    print(f"隔離実行が使えるか: {available()}")
    out = compute_summary("demo")
    print(f"ok={out['ok']} 参照={out['reference']} error={out['error']}")
    print("--- 標準出力 ---")
    print(out["stdout"] or "（なし）")
    print("--- 渡した CSV の先頭2行（氏名も社員IDも入っていない） ---")
    if INPUT_APP.exists():
        print("\n".join(INPUT_APP.read_text(encoding="utf-8").splitlines()[:2]))


if __name__ == "__main__":
    main()
