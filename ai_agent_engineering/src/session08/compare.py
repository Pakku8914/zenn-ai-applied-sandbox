#!/usr/bin/env python3
"""セッション8：単体構成と複数体構成を同じ題材で比べる。

    python src/session08/compare.py

数えるのは、環境に依存しない整数だけにする。

  手数   … LLM を呼んだ回数（セッション6の規約と同じ数え方）
  段数   … 直列に並ぶ呼び出しの段数（レイテンシの代理指標。並列分は最大値）
  定義   … 送ったツール定義の総数（1回の呼び出しに載る「使える道具」の重さ）
  再送   … 履歴に載ったツール結果の総数（同じ結果を何回送り直したか）
  項目   … 引き継ぎで渡した項目の総数（受け渡しの重さ）
  採点   … 成果物の採点（4項目。`report.score` が機械的に判定する）
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from runners import (run_handoff, run_orchestrator,  # noqa: E402
                     run_orchestrator_parallel, run_solo)
from sideeffects import reset_data  # noqa: E402

COLUMNS = ("方式", "体数", "手数", "段数", "定義", "再送", "項目", "採点")


def run_all() -> list[dict]:
    """7通りの構成を順に走らせる。各実行の前にデータと成果物を初期化する。"""
    return [
        run_solo(),
        run_orchestrator("structured"),
        run_orchestrator("free"),
        run_handoff("own"),
        run_handoff("carry"),
        run_handoff("needs"),
        run_orchestrator_parallel(),
    ]


def row_of(result: dict) -> list[str]:
    led, s = result["ledger"], result["score"]
    return [result["方式"], str(len(result["trajectories"])), str(led.total_calls),
            str(result["stages"]), str(led.total_specs), str(led.total_results),
            str(led.total_hop_fields), f"{s['passed']}/{s['total']}"]


def render_table(results: list[dict]) -> str:
    """比較表。桁揃えはしない（全角文字が混ざると表示幅が環境で変わるため）。"""
    return "\n".join([" | ".join(COLUMNS)] + [" | ".join(row_of(r)) for r in results])


def render_hops(result: dict) -> str:
    """引き継ぎの明細。どの区間で何を渡したかを1行ずつ出す。"""
    lines = ["区間 | 項目数 | 渡した鍵"]
    for hop in result["ledger"].hops:
        lines.append(f"{hop['from']}→{hop['to']} | {hop['fields']} | {', '.join(hop['keys'])}")
    return "\n".join(lines)


def render_missing(results: list[dict]) -> str:
    lines = ["方式 | 採点 | 欠けた項目"]
    for r in results:
        s = r["score"]
        lines.append(f"{r['方式']} | {s['passed']}/{s['total']} | "
                     f"{'（なし）' if not s['missing'] else '／'.join(s['missing'])}")
    return "\n".join(lines)


def render_tokens(results: list[dict]) -> str:
    """近似入力トークン（比較用＝メッセージの文字数÷3。ツール定義は含まない）。

    実 API の計測値ではない。ここで読み取るのは絶対値ではなく**推移と大小関係**である。
    """
    lines = ["方式 | 合計 | 1回の最大 | 呼び出しごと（役割別）"]
    for r in results:
        led = r["ledger"]
        per = " ".join(f"{role}={led.approx_in[role]}" for role in sorted(led.approx_in))
        lines.append(f"{r['方式']} | {led.total_in} | {led.max_in} | {per}")
    return "\n".join(lines)


def main() -> None:
    results = run_all()
    print("=== 方式の比較 ===")
    print(render_table(results))
    print()
    print("=== 成果物の採点で欠けた項目 ===")
    print(render_missing(results))
    print()
    print("=== 引き継ぎの明細：ハンドオフ（自分の成果だけ） ===")
    print(render_hops(results[3]))
    print()
    print("=== 引き継ぎの明細：オーケストレータ（構造化） ===")
    print(render_hops(results[1]))
    print()
    print("=== 近似入力トークン（比較用・文字数÷3。ツール定義は含まない） ===")
    print(render_tokens(results))
    reset_data()


if __name__ == "__main__":
    main()
