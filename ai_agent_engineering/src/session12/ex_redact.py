#!/usr/bin/env python3
"""練習問題の参照解：軌跡を保存する前に機密を伏せる。

機密は送信されなくても漏れる。**軌跡・ログ・トレース・エラーメッセージ**が複製だからだ。
`get_employee` を1回呼んだだけで住所はツール結果として文脈に入り、
`Trajectory.to_jsonl()` はそれをそのままファイルに書く。

`agentkit` は変更しない。保存する直前に**別の軌跡へ写して**から書き出す。

    python src/session12/ex_redact.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.models import Step, ToolCall, ToolResult, Trajectory  # noqa: E402
from attacks import CASES  # noqa: E402
from defenses import first_secret, mask_secrets  # noqa: E402
from layers import NAIVE_CONFIG, reset, run_case  # noqa: E402

REDACTED_DIR = ROOT / "traces" / "session12"


def _mask_args(args: dict) -> dict:
    """引数も伏せる。書き出し系は**引数に本文が入る**ので、結果だけ見ても足りない。"""
    return {k: mask_secrets(v) if isinstance(v, str) else v for k, v in args.items()}


def redact_trajectory(traj: Trajectory) -> Trajectory:
    """機密を伏せた写しを返す。元の軌跡は変更しない（frozen なので変更もできない）。"""
    out = Trajectory(task_id=traj.task_id, task=mask_secrets(traj.task),
                     final=mask_secrets(traj.final) if traj.final else traj.final,
                     stop_reason=traj.stop_reason)
    for s in traj.steps:
        out.steps.append(Step(
            index=s.index,
            thought=mask_secrets(s.thought),
            calls=[ToolCall(c.call_id, c.name, _mask_args(c.args)) for c in s.calls],
            results=[ToolResult(r.call_id, r.ok, mask_secrets(r.content),
                                mask_secrets(r.error) if r.error else r.error)
                     for r in s.results],
            usage=dict(s.usage),
        ))
    return out


def main() -> None:
    row = run_case(NAIVE_CONFIG, CASES[0])
    traj = row["軌跡"]
    leaked = [first_secret(r.content) for s in traj.steps for r in s.results
              if r.ok and first_secret(r.content)]
    print(f"対策前：軌跡のツール結果に含まれる機密 {len(leaked)} 件 → {leaked}")

    REDACTED_DIR.mkdir(parents=True, exist_ok=True)
    path = REDACTED_DIR / "redacted.jsonl"
    redact_trajectory(traj).to_jsonl(path)
    text = path.read_text(encoding="utf-8")
    print(f"対策後：保存した JSONL に残る機密 {0 if first_secret(text) is None else 1} 件")
    print(f"伏せ字の出現 {text.count('＊＊＊（伏せ字）')} 箇所 | 保存先 {path.relative_to(ROOT)}")
    path.unlink()
    reset()


if __name__ == "__main__":
    main()
