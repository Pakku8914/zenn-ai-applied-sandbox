#!/usr/bin/env python3
"""復習03：レビュー対象の構成仕様（1枚のデータとして扱う）。

安全性のレビューは、動いているものを眺めて感想を言う作業ではない。
**構成を1枚のデータにし、規則で監査する**作業である。ここではその1枚を用意する。

    python src/review03/spec.py

隔離（S09）の欄は `docker-compose.yml` の写しである。隔離コンテナを起動しなくても
「指定が足りているか」はここでレビューできる。

`agentkit` は1行も変更しない。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from _paths import setup

ROOT = setup()

from boundary import SOURCE_NOTE  # noqa: E402  (S12 の信頼境界の表)

# 依頼文。S02 で「これはエージェントでよい」と判断済みという前提で始める
TASK = ("2026年8月の経費を締めて、規程違反の疑いがある申請を注記したレポートを作り、"
        "経理部に共有してください")

# このタスクに必要なツール。手順書（DOC-0003）は人が読んで実装したので search_docs は要らない
TASK_NEEDS = ("get_policy", "list_expenses", "write_file", "send_message")

# 信頼できない本文を返すツール（S12 の表から取る。手で書き写さない）
UNTRUSTED_SOURCES = tuple(name for name, level, _ in SOURCE_NOTE if level == "信頼できない")

POLICY_THRESHOLD = 50_000        # 規程「経費精算」: 1件5万円以上は事前承認が必要
MAX_EXEC_TIMEOUT = 10.0          # S09 の guard.py が持つ上限（秒）
MAX_EXEC_MEMORY_MB = 128         # 同（MB）
SOUND_INSPECTORS = ("宛先＋内容",)  # 宛先だけでは足りない。根拠は問題3の実測

GRANULARITY_LABEL = {"tool": "ツール単位", "operation": "操作単位"}
JUDGE_LABEL = {"none": "しない", "kind_and_idempotency": "種類と冪等性で決める"}
COMPLETION_LABEL = {"model_claim": "モデルの申告", "effect_check": "副作用の照合"}


@dataclass(frozen=True)
class Spec:
    """レビュー対象の構成。辞書1つにまとめず型にしておくと、欠けた欄に気づける。"""

    name: str
    runner: dict          # 隔離コンテナの compose 指定（S09）
    exec_limits: dict     # 1回のコード実行に許す量（S09）
    tools: tuple[str, ...]        # エージェントに渡すツール（S12 の権限）
    untrusted: tuple[str, ...]    # 信頼できない出所として宣言したツール（S12）
    approval: dict        # 承認と監査の設定（S10）
    retry: dict           # 再試行と打ち切りの設定（S11）
    inspector: str        # 出力検査の実装（S12）
    completion: str       # 完了の判定（S11）


AS_IS = Spec(
    name="経費の月次締め代行エージェント v0（レビュー前）",
    runner={"network_mode": "none", "read_only": False, "tmpfs": True,
            "mem_limit": "256m", "pids_limit": None, "cap_drop": True},
    exec_limits={"timeout": 60.0, "memory_mb": 128, "max_calls": None,
                 "stdout_chars": None},
    tools=("search_docs", "get_policy", "list_expenses", "get_employee", "read_file",
           "write_file", "submit_expense", "send_message", "run_python"),
    untrusted=("search_docs",),
    approval={"granularity": "tool", "threshold_yen": 100_000, "audit_count": False},
    retry={"max_retries": 2, "judge": "none", "loop_window": 0},
    inspector="前方一致",
    completion="model_claim",
)


def apply_fixes(spec: Spec) -> Spec:
    """レビューの結論を仕様に書き戻す（問題9）。

    ここで足すのは**測れる層**だけである。「プロンプトに書く」は1つも入っていない。
    """
    return replace(
        spec,
        name="経費の月次締め代行エージェント v1（レビュー後）",
        runner={**spec.runner, "read_only": True, "pids_limit": 64},
        exec_limits={**spec.exec_limits, "timeout": MAX_EXEC_TIMEOUT,
                     "max_calls": 5, "stdout_chars": 2000},
        tools=TASK_NEEDS,
        untrusted=UNTRUSTED_SOURCES,
        approval={**spec.approval, "granularity": "operation",
                  "threshold_yen": POLICY_THRESHOLD, "audit_count": True},
        retry={**spec.retry, "max_retries": 1, "judge": "kind_and_idempotency",
               "loop_window": 3},
        inspector="宛先＋内容",
        completion="effect_check",
    )


TO_BE = apply_fixes(AS_IS)


# ---------------------------------------------------------------------------
# 表示（レビュー会に配る1枚）
# ---------------------------------------------------------------------------
def _mark(value) -> str:
    if value is None or value is False:
        return "なし"
    if value is True:
        return "あり"
    return str(value)


def _count(value, unit: str) -> str:
    return "なし" if value is None else f"{value} {unit}"


def _window(value: int) -> str:
    return "なし" if not value else f"{value} 手連続"


def render_spec(spec: Spec) -> str:
    r, e, a, t = spec.runner, spec.exec_limits, spec.approval, spec.retry
    return "\n".join([
        f"=== {spec.name} ===",
        "項目 | 設定",
        f"隔離の指定 | network_mode={r['network_mode']} / read_only={_mark(r['read_only'])}"
        f" / tmpfs={_mark(r['tmpfs'])} / mem_limit={_mark(r['mem_limit'])}"
        f" / pids_limit={_mark(r['pids_limit'])} / cap_drop={_mark(r['cap_drop'])}",
        f"コード実行の上限 | timeout={e['timeout']} 秒 / memory={e['memory_mb']} MB"
        f" / 実行回数={_count(e['max_calls'], '回')}"
        f" / 標準出力={_count(e['stdout_chars'], '文字')}",
        f"渡すツール（{len(spec.tools)} 本） | {', '.join(spec.tools)}",
        f"信頼できない出所（宣言） | {', '.join(spec.untrusted)}",
        f"承認 | 判定={GRANULARITY_LABEL[a['granularity']]} / 基準={a['threshold_yen']:,} 円"
        f" / 監査={'ハッシュ鎖＋件数' if a['audit_count'] else 'ハッシュ鎖のみ'}",
        f"再試行 | 上限={t['max_retries']} 回 / 判断={JUDGE_LABEL[t['judge']]}"
        f" / 循環検出={_window(t['loop_window'])}",
        f"出力検査 | {spec.inspector}",
        f"完了の判定 | {COMPLETION_LABEL[spec.completion]}",
    ])


def main() -> None:
    print(render_spec(AS_IS))
    print()
    print(render_spec(TO_BE))
    print()
    print(f"依頼文: {TASK}")
    print(f"このタスクに必要なツール（{len(TASK_NEEDS)} 本）: {', '.join(TASK_NEEDS)}")
    print(f"信頼できない出所（S12 の表から）: {', '.join(UNTRUSTED_SOURCES)}")


if __name__ == "__main__":
    main()
