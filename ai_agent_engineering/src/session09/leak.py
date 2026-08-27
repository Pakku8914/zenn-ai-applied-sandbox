#!/usr/bin/env python3
"""隔離が破られるパターン（セッション9）。

隔離コンテナは「外に出る経路」を消した。しかし **app と共有しているもの** は残っている。
共有ボリューム（/work）と依頼キュー（/queue）である。
ここでは3つの穴を実際に開けて見せ、対策を表にする。

    python src/session09/leak.py

境界を試す実験なので run_python を直接呼ぶ（アプリのコードは guard を通す）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentkit.sandbox import run_python  # noqa: E402

LEAK_APP = ROOT / "workspace" / "session09" / "leak"     # app から見たパス
LEAK_RUNNER = "/work/session09/leak"                     # 隔離コンテナから見た同じ場所
QUEUE_APP = Path(os.environ.get("RUNNER_QUEUE", "/workspace/runner_queue"))


def case_shared_read() -> dict:
    """① 作業領域に置いたものは、実行コードから読める。"""
    LEAK_APP.mkdir(parents=True, exist_ok=True)
    note = LEAK_APP / "shared_note.txt"
    # 本物の資格情報は絶対に置かない。これはダミーの文字列である
    note.write_text("CONFIDENTIAL-DUMMY-TOKEN-4242\n", encoding="utf-8")
    target = f"{LEAK_RUNNER}/shared_note.txt"
    code = ("from pathlib import Path\n"
            f"print(Path({target!r}).read_text(encoding='utf-8').strip())\n")
    res = run_python(code)
    note.unlink(missing_ok=True)
    return {"穴": "作業領域に置いたものは実行コードから読める",
            "破れた": "CONFIDENTIAL" in (res.content or ""),
            "観測": (res.content or "").strip() or (res.error or "")[:40]}


def case_tamper() -> dict:
    """② あとで読むファイルを、実行コードが書き換えられる。"""
    LEAK_APP.mkdir(parents=True, exist_ok=True)
    report = LEAK_APP / "report.md"
    report.write_text("# レポート\n合計: 285,400 円\n", encoding="utf-8")
    before = report.read_text(encoding="utf-8")
    target = f"{LEAK_RUNNER}/report.md"
    code = ("from pathlib import Path\n"
            f"Path({target!r}).write_text('# レポート\\n合計: 0 円\\n', encoding='utf-8')\n"
            "print('TAMPERED')\n")
    run_python(code)
    after = report.read_text(encoding="utf-8")
    report.unlink(missing_ok=True)
    return {"穴": "あとで読むファイルを実行コードが書き換えられる",
            "破れた": before != after,
            "観測": after.strip().splitlines()[-1]}


def case_queue() -> dict:
    """③ 依頼キューが実行コードから読み書きできる。"""
    marker = "leak_probe.txt"   # worker は *.req.json だけを見るので処理されない
    path = f"/queue/{marker}"
    code = ("import os\n"
            "from pathlib import Path\n"
            f"Path({path!r}).write_text('probe', encoding='utf-8')\n"
            "print('QUEUE_WRITE_OK',\n"
            "      any(n.endswith('.req.json') for n in os.listdir('/queue')))\n")
    res = run_python(code)
    seen = (QUEUE_APP / marker).exists()
    (QUEUE_APP / marker).unlink(missing_ok=True)
    return {"穴": "依頼キューが実行コードから読み書きできる",
            "破れた": seen,
            "観測": (res.content or "").strip() or (res.error or "")[:40]}


CASES = (case_shared_read, case_tamper, case_queue)

MITIGATIONS = [
    ("ジョブごとに作業領域を分ける",
     "/work 全体ではなく /work/<job> だけを渡す。他のジョブの生成物に触れなくなる"),
    ("秘密を作業領域に置かない",
     "共有ボリュームは隔離の内側ではなく境界そのもの。置いた時点で渡している"),
    ("依頼キューを実行コードから隔てる",
     "実行を非 root にし、キューを読めない所有者にする（セッション9の演習）"),
    ("生成物は宣言したものだけ受け取る",
     "指紋（ハッシュ）を取り、宣言外のファイルと差し替えを検出する"),
]


def run_all() -> list[dict]:
    return [case() for case in CASES]


def render(rows: list[dict]) -> str:
    lines = ["=== 隔離が破られるパターン ===", "破れた | 穴 | 観測"]
    for r in rows:
        lines.append(f"{'はい' if r['破れた'] else 'いいえ'} | {r['穴']} | {r['観測']}")
    lines.append("")
    lines.append("=== 対策 ===")
    lines.append("対策 | 内容")
    for name, detail in MITIGATIONS:
        lines.append(f"{name} | {detail}")
    return "\n".join(lines)


def main() -> None:
    print(render(run_all()))


if __name__ == "__main__":
    main()
