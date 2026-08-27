#!/usr/bin/env python3
"""実行結果の受け渡し（セッション9）。

隔離環境から返ってくるものは2つある。
  ① 標準出力 …… そのままモデルの文脈に入るので、上限を掛ける
  ② 生成ファイル …… 作業領域に置き、**参照（パス）だけ**を渡す
セッション7で決めた「大きいものは外に置いて参照を渡す」をそのまま適用する。

    python src/session09/artifacts.py
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from guard import notice, run_guarded  # noqa: E402

# app から見たパスと、隔離コンテナから見たパス（同じ場所を指す）
OUT_APP = ROOT / "workspace" / "session09" / "out"
OUT_RUNNER = "/work/session09/out"

ALLOWED_SUFFIXES = (".md", ".csv", ".json", ".txt")
MAX_BYTES = 64 * 1024


def reset(job: str) -> Path:
    """ジョブ用のディレクトリを空にして作る。

    失敗したときに前回の生成物が残っていると、古いファイルを成果と誤認する。
    """
    target = OUT_APP / job
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    return target


def prelude(job: str) -> str:
    """依頼コードの先頭に付ける。相対パスの書き込みをジョブ用ディレクトリに落とす。"""
    job_dir = f"{OUT_RUNNER}/{job}"
    return ("import os\n"
            f"os.makedirs({job_dir!r}, exist_ok=True)\n"
            f"os.chdir({job_dir!r})\n")


def scan(job: str) -> list[dict]:
    """生成物を検査してマニフェストにする。受け取るものと捨てるものを分ける。"""
    base = OUT_APP / job
    rows: list[dict] = []
    if not base.exists():
        return rows
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        name = path.relative_to(base).as_posix()
        size = path.stat().st_size
        if path.suffix not in ALLOWED_SUFFIXES:
            rows.append({"name": name, "bytes": size, "accepted": False, "sha256": "—",
                         "reason": f"許可していない拡張子です（{path.suffix}）"})
        elif size > MAX_BYTES:
            rows.append({"name": name, "bytes": size, "accepted": False, "sha256": "—",
                         "reason": f"大きすぎます（上限 {MAX_BYTES} バイト）"})
        else:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
            rows.append({"name": name, "bytes": size, "accepted": True, "sha256": digest,
                         "reason": "—"})
    return rows


def reference(job: str, name: str) -> str:
    """モデルに渡す参照。`read_file` がそのまま読める作業領域の相対パス。"""
    return f"session09/out/{job}/{name}"


def run_with_artifacts(code: str, *, job: str = "demo", timeout: float = 10.0,
                       memory_mb: int = 128) -> dict:
    """隔離環境でコードを実行し、標準出力と生成物のマニフェストを返す。"""
    reset(job)
    result = run_guarded(prelude(job) + code, timeout=timeout, memory_mb=memory_mb,
                         label=f"artifacts:{job}")
    files = scan(job)
    return {"ok": result["ok"], "stdout": result["stdout"], "dropped": result["dropped"],
            "error": result["error"], "files": files,
            "references": [reference(job, f["name"]) for f in files if f["accepted"]]}


DEMO_CODE = (
    "from pathlib import Path\n"
    "Path('summary.csv').write_text('category,amount\\nA,100\\nB,200\\n', encoding='utf-8')\n"
    "Path('notes.bin').write_text('x' * 10, encoding='utf-8')\n"
    "Path('huge.txt').write_text('x' * 100000, encoding='utf-8')\n"
    "print('x' * 3000)\n"
)


def render(result: dict) -> str:
    lines = ["=== 標準出力 ===",
             f"文字数={len(result['stdout'])} 捨てた文字数={result['dropped']}",
             f"断り書き={notice(result['dropped']).strip()}",
             "",
             "=== 生成物のマニフェスト ===",
             "受け取り | 名前 | バイト | 理由"]
    for f in result["files"]:
        lines.append(f"{'受け取る' if f['accepted'] else '捨てる'} | {f['name']} | "
                     f"{f['bytes']} | {f['reason']}")
    lines.append("")
    lines.append(f"モデルに渡す参照: {result['references']}")
    return "\n".join(lines)


def digests(result: dict) -> list[str]:
    """受け取った生成物の指紋。同じコードなら毎回同じ値になる。"""
    return [f["sha256"] for f in result["files"] if f["accepted"]]


def main() -> None:
    first = run_with_artifacts(DEMO_CODE, job="demo")
    print(render(first))
    second = run_with_artifacts(DEMO_CODE, job="demo")
    print(f"同じコードを2回実行して指紋が一致: {digests(first) == digests(second)}")


if __name__ == "__main__":
    main()
