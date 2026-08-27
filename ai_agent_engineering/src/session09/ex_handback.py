#!/usr/bin/env python3
"""問題5の参照解答：生成物の受け取りを宣言駆動にする（セッション9）。

拡張子の許可リストは「捨て忘れ」に強いが、**宣言していないファイル**を拾ってしまう。
依頼するときに「作るファイル」を宣言させ、それ以外は捨てる。
宣言したのに作られなかった場合は失敗として扱う（黙って空の成果を返さない）。

    python src/session09/ex_handback.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from artifacts import reference, run_with_artifacts  # noqa: E402


def run_declared(code: str, *, declares: list[str], job: str = "declared",
                 timeout: float = 10.0, memory_mb: int = 128) -> dict:
    """宣言したファイルだけを受け取る。"""
    result = run_with_artifacts(code, job=job, timeout=timeout, memory_mb=memory_mb)
    produced = {f["name"] for f in result["files"]}
    rows: list[dict] = []
    for f in result["files"]:
        if f["name"] not in declares:
            rows.append({**f, "accepted": False, "reason": "宣言されていません"})
        else:
            rows.append(f)
    missing = [name for name in declares if name not in produced]
    accepted = [r["name"] for r in rows if r["accepted"]]
    return {"ok": result["ok"] and not missing,
            "files": rows, "missing": missing, "accepted": accepted,
            "stdout": result["stdout"], "dropped": result["dropped"],
            "references": [reference(job, name) for name in accepted]}


CODE_EXTRA = (
    "from pathlib import Path\n"
    "Path('summary.csv').write_text('category,amount\\nA,100\\n', encoding='utf-8')\n"
    "Path('scratch.txt').write_text('memo', encoding='utf-8')\n"
    "print('DONE')\n"
)

CODE_MISSING = (
    "from pathlib import Path\n"
    "Path('summary.csv').write_text('category,amount\\nA,100\\n', encoding='utf-8')\n"
    "print('DONE')\n"
)


def cases() -> list[tuple[str, dict]]:
    return [
        ("宣言外のファイルを作った",
         run_declared(CODE_EXTRA, declares=["summary.csv"], job="declared_extra")),
        ("宣言したファイルを作らなかった",
         run_declared(CODE_MISSING, declares=["summary.csv", "chart.md"],
                      job="declared_missing")),
    ]


def render(rows: list[tuple[str, dict]]) -> str:
    lines = ["=== 宣言駆動の受け取り ===", "場合 | 成否 | 受け取った | 足りない"]
    for label, r in rows:
        lines.append(f"{label} | {'成功' if r['ok'] else '失敗'} | "
                     f"{r['accepted']} | {r['missing']}")
    lines.append("")
    lines.append("=== マニフェストの明細 ===")
    lines.append("場合 | 受け取り | 名前 | 理由")
    for label, r in rows:
        for f in r["files"]:
            lines.append(f"{label} | {'受け取る' if f['accepted'] else '捨てる'} | "
                         f"{f['name']} | {f['reason']}")
    return "\n".join(lines)


def main() -> None:
    print(render(cases()))


if __name__ == "__main__":
    main()
