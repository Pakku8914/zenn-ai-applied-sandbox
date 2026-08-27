#!/usr/bin/env python3
"""問題4の参照解答：隔離の穴を1本のプローブで示す（セッション9）。

示す穴は「**失敗したのに生成物が残る**」。
ツール結果は ok=False なのに、作業領域には途中まで書かれたファイルが残る。
エージェントは次のステップでそのファイルを読み、途中までのデータを正しい集計として扱う。

    python src/session09/ex_probe.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentkit.sandbox import run_python  # noqa: E402

PROBE_APP = ROOT / "workspace" / "session09" / "probe"
PROBE_RUNNER = "/work/session09/probe"

# 途中まで書いてから落ちるコード（例外は「途中で落ちる処理」の代表として使う）
CODE_PARTIAL = (
    "import os\n"
    f"os.makedirs({PROBE_RUNNER!r}, exist_ok=True)\n"
    f"os.chdir({PROBE_RUNNER!r})\n"
    "from pathlib import Path\n"
    "Path('half.csv').write_text('category,amount\\nA,100\\n', encoding='utf-8')\n"
    "print('HALF_WRITTEN')\n"
    "1 / 0\n"
)


def probe() -> dict:
    """穴が実在することを観測する。"""
    shutil.rmtree(PROBE_APP, ignore_errors=True)
    res = run_python(CODE_PARTIAL)
    leftover = PROBE_APP / "half.csv"
    exists = leftover.exists()
    size = leftover.stat().st_size if exists else 0
    shutil.rmtree(PROBE_APP, ignore_errors=True)
    return {"境界": "失敗したときの後片付け",
            "指定": "（compose では守れない。アプリ側の責任）",
            "期待": "実行は失敗し、途中まで書かれたファイルが残る",
            "実行結果": "成功" if res.ok else "失敗",
            "標準出力": (res.content or "").strip(),
            "残ったファイル": "half.csv" if exists else "（なし）",
            "残ったバイト数": size,
            "ok": (not res.ok) and exists and size > 0}


MITIGATIONS = [
    "ジョブ用ディレクトリを1回の実行ごとに作り、**実行の前に**丸ごと消す（artifacts.reset）",
    "実行が失敗したら生成物を受け取らない（ok=False のときはマニフェストを空にする）",
    "生成物の指紋を取り、前回の残骸と同じものを成果として渡さない",
]


def render(row: dict) -> str:
    lines = ["=== 追加プローブ：失敗したのに生成物が残る ===",
             f"境界: {row['境界']}",
             f"守っている指定: {row['指定']}",
             f"期待: {row['期待']}",
             f"実行結果: {row['実行結果']} / 標準出力: {row['標準出力']}",
             f"残ったファイル: {row['残ったファイル']}（{row['残ったバイト数']} バイト）",
             f"判定: {'OK（穴を再現できた）' if row['ok'] else 'NG（再現できていない）'}",
             "",
             "=== 対策 ==="]
    lines += [f"- {m}" for m in MITIGATIONS]
    return "\n".join(lines)


def main() -> None:
    row = probe()
    print(render(row))
    if not row["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
