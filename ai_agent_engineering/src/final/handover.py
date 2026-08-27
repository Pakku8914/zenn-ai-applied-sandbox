#!/usr/bin/env python3
"""最終プロジェクト・成果物①：引き継ぎ用の設計書。

    python src/final/handover.py     # 設計書（Markdown）を標準出力に出す

中間プロジェクト02の設計書との違いは、**読む人が「作る人」から「引き継ぐ人」に
変わる**という一点である。

  中間プロジェクト02 … 1本の走行の中で、どこで止めて何を検査するか
  この章             … 1件のジョブの一生の中で、いつ・誰が・何を見て動くか

だから同じ題材でも列が増える。ツール仕様表には「出口」と「打ち消し方」、状態遷移には
「担当」と「待たせてよい時間」、検査5カ所には「引き継ぎ後の担当」。
**担当の書かれていない検査は、引き継いだ瞬間に誰のものでもなくなる。**

表と図はすべて宣言から生成する。手で書いた図は必ず実装とずれる。
"""

from __future__ import annotations

from final_paths import setup

ROOT = setup()

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.state import Machine  # noqa: E402
from opsconfig import OpsConfig  # noqa: E402  (S15)

SYSTEM_NAME = "みなと商事オペレーション代行エージェント"

# 検査の目印（引き継ぎパッケージの採点でも同じ文字列を探す）
SPEC_TABLE_HEAD = "| ツール | 出口 | 冪等 | 段階 | 打ち消し |"
OWNER_TABLE_HEAD = "| 状態 | 担当 | 待たせてよい時間 | 最初に見るもの |"
EXIT_REACH_NOTE = "すべての状態から、人へ渡す出口に到達できる"

# ---------------------------------------------------------------------------
# 1. 道具（ツール仕様）
#
# 出口＝この道具を使うと「どこに」「何が」出るか。打ち消し方が無い道具は、
# 段階を上げる以外に守りようがない。
# ---------------------------------------------------------------------------
EXITS: dict[str, str] = {
    "book_room": "予約システム（他人の予定表に出る）",
    "submit_expense": "経費システム（承認者の手間が発生する）",
    "send_message": "社内チャット（受信者が読んだら戻せない）",
    "write_file": "作業領域（他のジョブと共有される）",
}

UNDO: dict[str, str] = {
    "book_room": "予約を取り消す",
    "submit_expense": "申請を取り下げる",
    "write_file": "上書きする",
    "send_message": "打ち消せない",
}

MODES = ("auto", "notify", "approve", "dual")
MODE_LABEL = {"auto": "自動実行", "notify": "事後通知",
              "approve": "事前承認", "dual": "二重承認"}

# 段階の宣言（S10 の4段階）。読み取りは宣言しない（＝自動実行）
APPROVAL: dict[str, str] = {
    "book_room": "notify",
    "write_file": "notify",
    "submit_expense": "approve",
    "send_message": "approve",
}

# 引き継ぎ後に足す条件付きの規則（宛先で段階が上がる）
CONDITIONAL_RULES: tuple[tuple[str, str, str], ...] = (
    ("send_message", "宛先が社内の完全一致でない", "二重承認（S12 の `is_internal` で判定）"),
    ("submit_expense", "金額が 50,000 円以上", "事前承認（S10 の判定表どおり）"),
    ("write_file", "書き込み先が他のジョブの作業領域", "実行しない（ツール側で弾く）"),
)

# 比較用：打ち消せない操作を事後通知に落とした宣言（実行前の検査で落ちる）
LOOSE_APPROVAL: dict[str, str] = {**APPROVAL, "send_message": "notify"}


def spec_rows(registry=None, approval: dict[str, str] | None = None) -> list[dict]:
    """ツール仕様表の行。**レジストリから生成する**ので実装とずれない。"""
    registry = registry if registry is not None else build_registry()
    approval = approval if approval is not None else APPROVAL
    rows: list[dict] = []
    for name in registry.names():
        tool = registry.get(name)
        write = "write" in tool.tags
        rows.append({
            "name": name,
            "write": write,
            "exit": EXITS.get(name, "—（読み取り）"),
            "idempotent": tool.idempotent,
            "mode": approval.get(name, "auto"),
            "undo": UNDO.get(name, "—"),
            "requires_approval": tool.requires_approval,
        })
    return rows


def spec_violations(registry=None, approval: dict[str, str] | None = None) -> list[str]:
    """宣言とレジストリが食い違っていないかを、走らせる前に検査する。

    検査するのは「この宣言で運用できるか」だけである。うまくいくかは検査できない。
    """
    registry = registry if registry is not None else build_registry()
    approval = approval if approval is not None else APPROVAL
    out: list[str] = []
    for row in spec_rows(registry, approval):
        name, mode = row["name"], row["mode"]
        if row["write"]:
            if name not in approval:
                out.append(f"{name}: 副作用のある道具に段階が宣言されていません。")
            if name not in EXITS:
                out.append(f"{name}: 出口（どこに何が出るか）が宣言されていません。")
            if name not in UNDO:
                out.append(f"{name}: 打ち消し方が宣言されていません。")
        elif name in approval:
            out.append(f"{name}: 読み取りの道具に段階を宣言しています（段階は副作用にだけ付けます）。")
        if row["requires_approval"] and mode not in ("approve", "dual"):
            out.append(
                f"{name}: レジストリは承認が必要と宣言していますが、段階が "
                f"{MODE_LABEL[mode]} です。事前承認以上にしてください。")
        if row["undo"] == "打ち消せない" and mode not in ("approve", "dual"):
            out.append(
                f"{name}: 打ち消せない操作なのに段階が {MODE_LABEL[mode]} です。"
                "事前承認以上にしてください。")
    return out


# ---------------------------------------------------------------------------
# 2. ジョブの状態遷移
#
# 中間プロジェクト02の承認フロー（10状態26遷移）は「1本の走行の中」の図である。
# こちらは**1件のジョブの一生**の図で、キューに入ってから人に引き渡すまでを表す。
# 混ぜてはいけない。運用の当番が見るのはこちらで、実装者が見るのはあちらである。
# ---------------------------------------------------------------------------
JOB_TRANSITIONS: dict[str, dict[str, str]] = {
    "queued": {"assigned": "running", "cancelled": "cancelled"},
    "running": {"step": "running", "needs_approval": "waiting",
                "rate_limited": "queued", "crashed": "queued",
                "limit_reached": "limited", "cancelled": "cancelled",
                "failed": "failed", "finished": "reviewing"},
    "waiting": {"approved": "running", "rejected": "compensating",
                "expired": "handoff"},
    "compensating": {"compensated": "handoff"},
    "reviewing": {"accepted": "done", "defect_found": "handoff"},
    "limited": {"escalated": "handoff"},
    "failed": {"escalated": "handoff"},
    "handoff": {"delivered": "closed"},
}

JOB_TERMINAL = ("done", "cancelled", "closed")
JOB_TRANSITION_COUNT = sum(len(events) for events in JOB_TRANSITIONS.values())

# 状態ごとの担当・待たせてよい時間・最初に見るもの。
# **「最初に見るもの」を書いておくと、深夜の当番が調べ物から始めずに済む。**
OWNERS: dict[str, tuple[str, str, str]] = {
    "queued": ("当番（オンコール）", "15分", "キューの滞留件数"),
    "running": ("当番（オンコール）", "1ジョブ 8 ステップ", "軌跡の最後のステップ"),
    "waiting": ("承認者（所属長）", "24時間で期限切れ", "承認依頼の本文と差分"),
    "compensating": ("当番（オンコール）", "10分", "打ち消しの結果"),
    "reviewing": ("当番（オンコール）", "30分", "成果物の中身"),
    "limited": ("当番（オンコール）", "30分", "止まった理由と残った副作用"),
    "failed": ("当番（オンコール）", "30分", "エラー文と軌跡"),
    "handoff": ("当番 → エスカレーション先", "当日中", "引き継ぎ書"),
    "cancelled": ("当番（オンコール）", "当日中", "止めた時点の引き継ぎ書"),
    "done": ("—（完了）", "—", "—"),
    "closed": ("—（引き渡し済み）", "—", "—"),
}

ESCALATION: tuple[tuple[str, str, str], ...] = (
    ("一次", "当番（オンコール）", "runbook に載っている症状。30分で解決しなければ二次へ"),
    ("二次", "このエージェントの開発担当", "runbook に無い症状・軌跡から原因が特定できない"),
    ("三次", "情報システム部", "越境の疑い・機密の流出・外部システムの障害"),
)


def build_job_machine(initial: str = "queued") -> Machine:
    if initial not in JOB_TRANSITIONS and initial not in JOB_TERMINAL:
        raise ValueError(f"未定義の状態です: {initial!r}")
    return Machine(initial, JOB_TRANSITIONS)


def job_states() -> list[str]:
    return sorted(set(JOB_TRANSITIONS) | set(JOB_TERMINAL))


def job_mermaid() -> str:
    """ジョブの状態遷移図。状態機械から生成するので実装とずれない。"""
    return build_job_machine().to_mermaid()


def reachable_from(start: str) -> set[str]:
    """start から到達できる状態の集合（幅優先）。"""
    seen = {start}
    queue = [start]
    while queue:
        state = queue.pop(0)
        for nxt in JOB_TRANSITIONS.get(state, {}).values():
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def dead_ends() -> list[str]:
    """終端に到達できない状態。**1つでもあれば、そのジョブは誰にも渡らない。**"""
    return sorted(state for state in job_states()
                  if not (reachable_from(state) & set(JOB_TERMINAL)))


def unreachable_states() -> list[str]:
    """受付（queued）から到達できない状態。図にあるのに通らない道は消す。"""
    return sorted(set(job_states()) - reachable_from("queued"))


def flow_violations() -> list[str]:
    out: list[str] = []
    missing = sorted(set(job_states()) - set(OWNERS))
    if missing:
        out.append(f"担当が書かれていない状態があります: {', '.join(missing)}")
    stuck = dead_ends()
    if stuck:
        out.append(f"終端に到達できない状態があります: {', '.join(stuck)}")
    unused = unreachable_states()
    if unused:
        out.append(f"受付から到達できない状態があります: {', '.join(unused)}")
    return out


# ---------------------------------------------------------------------------
# 3. 運用の信頼境界と検査5カ所
#
# 検査そのものは S12・中間プロジェクト02から1つも増やしていない。足したのは
# 「引き継ぎ後の担当」と「壊れたと分かる方法」の2列だけである。
# ---------------------------------------------------------------------------
CHECKPOINTS: tuple[tuple[str, str, str, str], ...] = (
    ("入力検査・構造分離", "ツール結果が戻った直後", "当番（週次で警告件数を見る）",
     "警告が0件のまま注入が通る"),
    ("権限制限", "レジストリを組むとき", "開発担当（変更はレビュー必須）",
     "許可リストに無い道具が呼べる"),
    ("引数の確定", "呼び出しを組み立てるとき", "開発担当",
     "金額・宛先がモデルの提案で上書きされる"),
    ("出力検査", "実行の直前", "当番（遮断件数を日次で見る）",
     "遮断が0件のまま社外宛が出る"),
    ("人間承認", "取り返しのつかない操作の前", "承認者（所属長）",
     "承認より前に実行の記録がある"),
)

TRUST_FLOW_MERMAID = """flowchart LR
    req["利用者の依頼<br/>受付フォーム"]
    human(["承認者（人間）"])
    subgraph untrusted["信頼できない入力"]
        docs["社内文書 docs.jsonl<br/>DOC-0004 に注入"]
        prev["前の走行が書いた<br/>作業領域のファイル"]
    end
    subgraph queue["受付とキュー"]
        q["キュー<br/>レート上限 2 回/秒・多重度 2"]
    end
    subgraph worker["ワーカー（1ジョブ 8 ステップまで）"]
        c1{{"入力検査・構造分離"}}
        agent["エージェント本体"]
        c2{{"権限制限"}}
        c3{{"引数の確定"}}
        c4{{"出力検査"}}
    end
    subgraph exits["出口（取り消しにくい順）"]
        chat["社内チャット"]
        expsys["経費システム"]
        room["予約システム"]
        ws["作業領域"]
    end
    subgraph store["記録（引き継ぎの一次情報）"]
        tr["軌跡 traces/"]
        au["監査ログ"]
    end
    req --> q
    q --> agent
    docs --> c1
    prev --> c1
    c1 --> agent
    agent --> c2
    c2 --> c3
    c3 --> c4
    c4 -- 承認が必要 --> human
    human -- 承認/却下 --> c4
    c4 --> chat
    c4 --> expsys
    c4 --> room
    c4 --> ws
    agent --> tr
    agent --> au"""


# ---------------------------------------------------------------------------
# 設計書の生成
# ---------------------------------------------------------------------------
def render_spec_md(registry=None, approval: dict[str, str] | None = None) -> str:
    lines = [SPEC_TABLE_HEAD, "| :--- | :--- | :--- | :--- | :--- |"]
    for row in spec_rows(registry, approval):
        lines.append(
            f"| {row['name']} | {row['exit']} | "
            f"{'はい' if row['idempotent'] else 'いいえ'} | "
            f"{MODE_LABEL[row['mode']]} | {row['undo']} |")
    return "\n".join(lines)


def render_owner_md() -> str:
    lines = [OWNER_TABLE_HEAD, "| :--- | :--- | :--- | :--- |"]
    for state in job_states():
        owner, budget, first = OWNERS[state]
        lines.append(f"| {state} | {owner} | {budget} | {first} |")
    return "\n".join(lines)


def render_checkpoints_md() -> str:
    lines = ["| 検査 | どこで効くか | 引き継ぎ後の担当 | 壊れたと分かる兆候 |",
             "| :--- | :--- | :--- | :--- |"]
    for name, where, owner, broken in CHECKPOINTS:
        lines.append(f"| {name} | {where} | {owner} | {broken} |")
    return "\n".join(lines)


def render_config_md(cfg: OpsConfig | None = None) -> str:
    cfg = cfg or OpsConfig.load()
    keep = ("workers", "rate_limit_per_second", "max_steps_per_job",
            "canary_percents", "min_success_rate", "max_step_ratio")
    rows = dict(cfg.as_rows())
    lines = ["| 設定 | 値 | 変えてよいのは誰か |", "| :--- | :--- | :--- |"]
    who = {"workers": "当番（滞留時のみ・上限4）",
           "rate_limit_per_second": "開発担当（契約に依存する）",
           "max_steps_per_job": "開発担当（評価をやり直す）",
           "canary_percents": "開発担当",
           "min_success_rate": "開発担当（下げるときは記録を残す）",
           "max_step_ratio": "開発担当"}
    for key in keep:
        lines.append(f"| {key} | {rows[key]} | {who[key]} |")
    return "\n".join(lines)


def design_md(cfg: OpsConfig | None = None) -> str:
    cfg = cfg or OpsConfig.load()
    rows = spec_rows()
    writes = [r for r in rows if r["write"]]
    return "\n".join([
        f"# 引き継ぎ設計書：{SYSTEM_NAME}",
        "",
        "## 0. この文書の読み方",
        "",
        "この1枚は「引き継ぐ人が最初に読むもの」です。作り方ではなく、"
        "**動いているものが止まったときに、誰が何を見て何をするか**を書いてあります。",
        "コードから生成しているので、実装を変えれば表も変わります。手で直さないでください。",
        "",
        "## 1. 道具（ツール仕様）",
        "",
        f"登録されている道具は {len(rows)} 個、うち副作用のあるものが {len(writes)} 個です。",
        "",
        render_spec_md(),
        "",
        "### 宛先や金額で段階が上がる規則",
        "",
        "| ツール | 条件 | そのときの段階 |",
        "| :--- | :--- | :--- |",
        *[f"| {name} | {cond} | {mode} |" for name, cond, mode in CONDITIONAL_RULES],
        "",
        "## 2. ジョブの状態遷移と担当",
        "",
        f"状態 {len(job_states())} / 遷移 {JOB_TRANSITION_COUNT} 本。"
        "中間プロジェクト2の承認フロー図が「1本の走行の中」を表すのに対し、"
        "こちらは「1件のジョブの一生」を表します。",
        "",
        "```mermaid",
        job_mermaid(),
        "```",
        "",
        render_owner_md(),
        "",
        f"- {EXIT_REACH_NOTE}（`handover.dead_ends()` が空であることで検査しています）",
        "- 受付から到達できない状態はありません（`handover.unreachable_states()` が空）",
        "",
        "## 3. 運用の信頼境界と検査5カ所",
        "",
        "```mermaid",
        TRUST_FLOW_MERMAID,
        "```",
        "",
        render_checkpoints_md(),
        "",
        "## 4. 承認フロー",
        "",
        "- 事前承認以上の操作は、承認より前に実行の記録があってはいけません（監査ログの順序で検査）",
        "- 承認された内容と実行する内容は、照合用ハッシュで一致を確認します",
        "- 承認が 24 時間で期限切れになったときは、**戻さずに人へ渡します**"
        "（期限切れは却下ではないため）",
        "",
        "## 5. 上限と設定",
        "",
        render_config_md(cfg),
        "",
        "## 6. エスカレーション",
        "",
        "| 段 | 誰 | 上げる条件 |",
        "| :--- | :--- | :--- |",
        *[f"| {level} | {who} | {when} |" for level, who, when in ESCALATION],
        "",
    ])


def main() -> None:
    print(design_md())
    print("\n=== 実行前の検査 ===")
    print(f"ツール仕様の違反: {spec_violations() or 'なし'}")
    print(f"状態遷移の違反: {flow_violations() or 'なし'}")
    for violation in spec_violations(approval=LOOSE_APPROVAL):
        print(f"比較用（送信を事後通知に落とした宣言）: {violation}")


if __name__ == "__main__":
    main()
