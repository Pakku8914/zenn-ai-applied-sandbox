#!/usr/bin/env python3
"""セッション15：段階リリース（カナリア）とロールバック。

    python src/session15/rollout.py

新しい構成を全トラフィックにいきなり当てない、というのは誰でも言える。
難しいのは「**何％から始めるか**」ではなく「**何を見て次へ進むか**」と
「**その5％に、壊れる型のタスクが入っているか**」である。

振り分けは乱数で決めない。同じ task_id は必ず同じ群に入るようにする
（Python の組み込み `hash()` はプロセスごとに変わるので使わない）。
そうしないと、同じタスクが再試行のたびに旧構成と新構成を行き来する。
"""

from __future__ import annotations

import hashlib
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.eval import ExpectedTrajectory, task_success  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.loop import ReActAgent  # noqa: E402
from agentkit.models import Trajectory  # noqa: E402
from jobspec import (KINDS, SEND_NEW_TURNS, build_job_tools, clear_workspace,  # noqa: E402
                     jsonl_count, reset_data)
from opsconfig import OpsConfig  # noqa: E402

KIND_ORDER = ("policy", "list", "report", "send")
POPULATION = [f"TASK-{200 + i}" for i in range(100)]

# 期待する軌跡（セッション13の宣言をそのまま運用に持ち込む）
EXPECTED = {
    "policy": ["get_policy"],
    "list": ["get_policy", "list_expenses"],
    "report": ["get_policy", "list_expenses", "write_file"],
    "send": ["get_policy", "write_file"],
}


def kind_of(task_id: str) -> str:
    """タスクの型。送信を伴う型は全体の4%しか来ない（＝カナリアに入りにくい）。"""
    i = int(task_id.rsplit("-", 1)[1]) % 100
    return "send" if i % 25 == 7 else ("policy", "list", "report")[i % 3]


def bucket(task_id: str, method: str = "serial") -> int:
    """0〜99 の群。**同じ task_id は常に同じ群**に入る（乱数を使わない）。

    serial … ID の連番をそのまま使う（本章の既定。手で追える）
    hash   … 安定ハッシュ（本番向け。ID の並びに意味がある場合はこちら）
    """
    tail = task_id.rsplit("-", 1)[1]
    if method == "serial":
        return int(tail) % 100
    return int(hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:8], 16) % 100


def canary_ids(percent: int, strategy: str = "head",
               method: str = "serial") -> list[str]:
    """新構成に回すタスクを選ぶ。"""
    if strategy == "head":
        return [tid for tid in POPULATION if bucket(tid, method) < percent]
    if strategy != "stratified":
        raise ValueError(f"strategy は head か stratified です: {strategy!r}")
    # 型ごとに最低1件を確保してから、足りない分を先頭から埋める（層化）
    quota = max(1, round(len(POPULATION) * percent / 100))
    picked: list[str] = []
    for kind in KIND_ORDER:
        first = next((tid for tid in POPULATION if kind_of(tid) == kind), None)
        if first is not None and first not in picked:
            picked.append(first)
    for tid in POPULATION:
        if len(picked) >= quota:
            break
        if tid not in picked:
            picked.append(tid)
    return sorted(picked, key=lambda tid: bucket(tid, method))


# ---------------------------------------------------------------------------
def run_one(task_id: str, variant: str) -> Trajectory:
    """1件を指定の構成で走らせる。構成の違いは応答列（＝モデルの振る舞い）だけ。"""
    kind = kind_of(task_id)
    task, turns, _steps = KINDS[kind]
    if kind == "send" and variant == "new":
        turns = SEND_NEW_TURNS          # 新構成は下書きせず送ってしまう
    agent = ReActAgent(ScriptedClient(turns), build_job_tools(f"rollout-{variant}"),
                       max_steps=8)
    return agent.run(task, task_id=task_id)


@dataclass
class ArmMetrics:
    """片方の群（旧構成 or 新構成）の成績。"""

    variant: str
    n: int = 0
    success: int = 0
    forbidden: int = 0
    steps: int = 0
    kinds: Counter = field(default_factory=Counter)

    @property
    def success_rate(self) -> float:
        return self.success / self.n if self.n else 0.0

    def kind_breakdown(self) -> str:
        return " / ".join(f"{k} {self.kinds[k]}" for k in KIND_ORDER if self.kinds[k])


def measure(task_ids: list[str], variant: str) -> ArmMetrics:
    m = ArmMetrics(variant=variant)
    for tid in task_ids:
        kind = kind_of(tid)
        traj = run_one(tid, variant)
        expected = ExpectedTrajectory(task_id=tid, tools=EXPECTED[kind],
                                      forbidden_tools=["send_message"], max_steps=6)
        m.n += 1
        m.success += int(task_success(traj, expected))
        m.forbidden += sum(1 for name in traj.tool_names if name == "send_message")
        m.steps += len(traj.steps)
        m.kinds[kind] += 1
    return m


def decide(new: ArmMetrics, base: ArmMetrics, cfg: OpsConfig) -> tuple[str, str]:
    """次の段階へ進むかを、3つの基準で機械的に決める。

    「様子を見て問題なさそうなら進む」は判断基準ではない。誰が見ても同じ答えに
    なる形（数値と閾値）にしておかないと、深夜に判断できない。
    """
    if new.forbidden > 0:
        return "止める", f"禁止ツールの呼び出しが {new.forbidden} 件"
    if new.success_rate < cfg.min_success_rate:
        return "止める", (f"成功率 {new.success_rate:.3f} が基準 "
                          f"{cfg.min_success_rate:.3f} を下回った")
    if base.steps and new.steps > base.steps * cfg.max_step_ratio:
        return "止める", f"手数 {new.steps} が基準 {base.steps} の {cfg.max_step_ratio} 倍を超えた"
    return "進む", "3つの基準（禁止ツール・成功率・手数）をすべて満たした"


def run_rollout(cfg: OpsConfig, strategy: str | None = None) -> list[dict]:
    """段階を順に上げる。**止める判定が出たらそこで打ち切る**（次へ進めない）。"""
    strategy = strategy or cfg.canary_strategy
    rows = []
    for percent in cfg.canary_percents:
        ids = canary_ids(percent, strategy)
        new, base = measure(ids, "new"), measure(ids, "old")
        verdict, why = decide(new, base, cfg)
        rows.append({"strategy": strategy, "percent": percent, "n": new.n,
                     "kinds": new.kind_breakdown(), "new": new, "base": base,
                     "verdict": verdict, "why": why})
        if verdict == "止める":
            break
    return rows


# ---------------------------------------------------------------------------
def render_runbook(percent: int = 25, forbidden: int = 1) -> str:
    """ロールバックの runbook。深夜に読んで手が動く粒度で書く。"""
    return "\n".join([
        "# runbook: 新構成のロールバック",
        "",
        "## 検知",
        f"- 段階 {percent}% で禁止ツールの呼び出しを {forbidden} 件検出した",
        "- 見た指標: 禁止ツールの呼び出し数 / タスク成功率 / 手数の合計",
        "- 一次情報: 軌跡（traces/）と data/messages.jsonl の増加行数",
        "",
        "## 一次判断",
        "- 禁止ツールの呼び出しは1件でも「止める」。様子を見ない",
        "- 成功率だけの低下なら、型ごとに割って原因の型を特定してから決める",
        "",
        "## ロールバック手順",
        "1. ops.json の canary_percents を [0] にして新構成への振り分けを止める",
        "2. 新規受付を止めず、キューに積まれたジョブは旧構成で処理する",
        "3. 5分後に禁止ツールの呼び出し数が 0 に戻ったことを確認する",
        "4. 戻らない場合はワーカーを1台ずつ入れ替える（全台同時に止めない）",
        "",
        "## 進行中のジョブの扱い",
        "- 副作用を出していないジョブ: キャンセルして旧構成で入れ直す",
        "- 副作用を出したジョブ: 走り切らせる。途中で止めると中途半端な状態が残る",
        "- 判定に迷うジョブ: 引き継ぎ書を出して人に渡す",
        "",
        "## 後始末",
        "- 送信済みメッセージの一覧を作り、宛先へ訂正の連絡を出す（補償）",
        "- 影響を受けた task_id を記録する（あとで再実行の対象になる）",
        "",
        "## 再発防止",
        "- カナリアを層化する（型ごとに最低1件を新構成へ回す）",
        "- 送信系ツールに承認ゲートを付ける（呼べてしまうこと自体が欠陥）",
        "- 差し替えの受け入れ基準に「禁止ツール0件」を明文化する",
    ])


REQUIRED_SECTIONS = ("## 検知", "## 一次判断", "## ロールバック手順",
                     "## 進行中のジョブの扱い", "## 後始末", "## 再発防止")


def check_runbook(text: str) -> tuple[bool, list[str]]:
    """runbook に必要な節がそろっているか。足りない節を返す。"""
    missing = [s for s in REQUIRED_SECTIONS if s not in text]
    if "1. " not in text:
        missing.append("番号付きの手順")
    return (not missing), missing


# ---------------------------------------------------------------------------
def main() -> None:
    reset_data()
    clear_workspace()
    cfg = OpsConfig.load()

    print("=== 母集団（100件）===")
    kinds = Counter(kind_of(tid) for tid in POPULATION)
    print("型 | 件数 | 1件あたりの手数")
    for kind in KIND_ORDER:
        print(f"{kind} | {kinds[kind]} | {KINDS[kind][2]}")
    print("※ 壊れるのは send 型だけ。母集団の 4% しかない。")

    before = jsonl_count("messages")
    print("\n=== 段階リリース（振り分けは task_id から決める。乱数を使わない）===")
    print("選び方 | 段階 | 新構成 | 型の内訳 | 新:成功 | 新:禁止 | 旧:成功 | 旧:禁止 | 判定 | 理由")
    rows = run_rollout(cfg, "head") + run_rollout(cfg.with_(canary_percents=(5,)),
                                                  "stratified")
    for row in rows:
        label = "先頭から" if row["strategy"] == "head" else "型ごとに"
        print(" | ".join([
            label, f"{row['percent']}%", str(row["n"]), row["kinds"],
            str(row["new"].success), str(row["new"].forbidden),
            str(row["base"].success), str(row["base"].forbidden),
            row["verdict"], row["why"],
        ]))
    print(f"\nmessages.jsonl の増加: {jsonl_count('messages') - before} 行"
          "（新構成が実際に社外へ送っている）")

    print("\n=== ロールバック後の確認（全件を旧構成で流す）===")
    after = measure(POPULATION, "old")
    print(f"件数 {after.n} / 成功 {after.success} / 禁止ツール {after.forbidden} / "
          f"手数の合計 {after.steps}")

    print("\n=== 読み取れること ===")
    print("- 先頭から 5% では欠陥が1件も当たらない。「安全だった」のではなく「当てていない」。")
    print("- 型ごとに1件ずつ選べば、同じ 5% で同じ欠陥を検出できる。")
    print("- カナリアの設計は割合ではなく**型の網羅**である。")

    print("\n=== runbook（抜粋）===")
    runbook = render_runbook()
    print("\n".join(runbook.splitlines()[:14]))
    ok, missing = check_runbook(runbook)
    print(f"…\nrunbook の節がそろっているか: {ok}（不足: {missing or 'なし'}）")

    reset_data()
    clear_workspace()


if __name__ == "__main__":
    main()
