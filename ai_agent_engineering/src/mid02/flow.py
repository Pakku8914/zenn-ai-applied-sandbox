#!/usr/bin/env python3
"""承認フロー（成果物①）と信頼境界（成果物②）の定義。

    python src/mid02/flow.py          # 2枚の図（Mermaid）を出力する

この章で分けて持つのは、中間プロジェクト01と同じ3つである。混ぜると何も説明できなくなる。

  状態       … どこまで進んだか（planning / preparing / ... / done / failed）
  停止理由   … なぜ止まったか（done / budget / max_steps / error / awaiting_approval / loop_detected）
  結果       … 人に何を渡したか（report / partial / insufficient / handoff）

中間プロジェクト01との違いは、**副作用が絡む状態が3つ増える**ことだけである。

  requesting   … これから出す副作用の段階を判定し、必要なら承認を依頼する
  waiting      … 承認待ちで中断する（`awaiting_approval`）
  compensating … 出してしまった副作用を逆順に打ち消す

`agentkit.state.Machine` はそのまま使う。足したのは「状態ごとの許可リスト」
「同じ状態に留まってよい回数」「モデルに聞く状態」だけである。
"""

from __future__ import annotations

from _paths import setup

ROOT = setup()

from agentkit.state import Machine  # noqa: E402

# ---------------------------------------------------------------------------
# 状態と遷移。{現在の状態: {イベント: 次の状態}}
#
# 設計上の約束が4つある。
#   1. 副作用を出したあとに止まるときは、必ず compensating を通る（黙って残さない）
#   2. compensating / reporting / handoff は**上限の外**に置く（後片付けを上限で殺さない）
#   3. executing も上限の外に置く（承認と実行の間で止めると、承認だけが宙に浮く）。
#      上限は「新しい行動を始める前」＝ preparing と requesting でだけ判定する
#   4. 却下は戻す（compensating）が、期限切れは戻さず人へ渡す（handoff）
# ---------------------------------------------------------------------------
TRANSITIONS: dict[str, dict[str, str]] = {
    "planning": {"plan_ready": "preparing", "invalid_plan": "handoff"},
    "preparing": {"prepared": "requesting", "need_more": "preparing",
                  "blocked": "handoff", "over_budget": "handoff"},
    "requesting": {"needs_approval": "waiting", "auto_ok": "executing",
                   "all_done": "reporting", "refused": "compensating",
                   "blocked": "handoff", "over_budget": "compensating"},
    "waiting": {"approved": "executing", "amended": "executing",
                "rejected": "compensating", "expired": "handoff"},
    "executing": {"advanced": "requesting", "retry_altered": "requesting",
                  "uncertain": "handoff", "failed": "compensating"},
    "compensating": {"compensated": "handoff", "uncompensated": "handoff"},
    "reporting": {"reported": "done", "crossed": "compensating", "blocked": "handoff"},
    "handoff": {"escalated": "failed"},
}

# 遷移の本数（Mermaid の行数は見出しを足して +1）。図と実装がずれないよう定数にしない
TRANSITION_COUNT = sum(len(events) for events in TRANSITIONS.values())

# 出口のない状態（ここに来たら走行は終わり）
TERMINAL = ("done", "failed")

# 状態ごとに使ってよいツール（S04 の許可リストを「状態」に紐づける）
#   preparing … 読み取りだけ（副作用なし）
#   executing … 副作用のある操作だけ（承認の判定を通ったものに限る）
#   その他    … 成果物を書く write_file だけ
#
# **段階の許可リストと権限の許可リストは別の層である。** ここが決めるのは
# 「いつ使ってよいか」であって「そもそも持たせるか」ではない。だから読み取り系の
# get_employee / read_file は preparing に載せておき、この業務に要らないという判断は
# 権限制限（`ops_spec.TASK_ALLOW_OPS`）の側で下す。両方を混ぜると、権限を外した効果と
# 段階で断った効果を切り分けて測れなくなる。
STATE_TOOLS: dict[str, tuple[str, ...]] = {
    "planning": (),
    "preparing": ("get_policy", "find_expenses", "search_docs",
                  "get_employee", "read_file"),
    "requesting": (),
    "waiting": (),
    "executing": ("book_room", "submit_expense", "send_message", "write_file"),
    "compensating": (),
    "reporting": ("write_file",),
    "handoff": ("write_file",),
    "done": (),
    "failed": (),
}

# モデルに聞く状態。ここ以外は状態から決まるので聞かない（＝手数に数えない）
ASK_STATES = ("preparing", "requesting")

# 同じ状態に留まってよい回数の上限。ループには必ず上限を置く
# （requesting は計画の操作ごとに1回ずつ通るので、計画の長さより大きくする）
LOOP_LIMITS: dict[str, int] = {"preparing": 3, "requesting": 8}

# 判定の材料（これがそろうまで preparing に留まる）
REQUIRED_SOURCES = ("get_policy", "find_expenses")

# 根拠として状態に採用するツール。search_docs は採用しない（信頼境界の線）
MATERIAL_TOOLS = ("get_policy", "find_expenses")

# 人に渡すものの種類（中間プロジェクト01の軸をそのまま踏襲する）
OUTCOMES = ("report", "partial", "insufficient", "handoff")
OUTCOME_LABELS = {
    "report": "報告",
    "partial": "打ち切り（部分結果）",
    "insufficient": "情報不足",
    "handoff": "引き継ぎ",
}

# 成果物の置き場所（workspace/ からの相対パス）
ARTIFACT_PATH = "mid02/report.md"
HANDOFF_PATH = "mid02/handoff.md"
RUNBOOK_STALLED_PATH = "mid02/runbook_stalled.md"
RUNBOOK_DOUBLE_PATH = "mid02/runbook_double.md"
SUMMARY_INPUT_PATH = "mid02/input/expenses.csv"


def build_machine(initial: str = "planning") -> Machine:
    """状態機械を作る。未定義の状態から始めようとしたらそこで落とす。"""
    if initial not in TRANSITIONS and initial not in TERMINAL:
        raise ValueError(f"未定義の状態です: {initial!r}")
    return Machine(initial, TRANSITIONS)


def stage_error(state: str, name: str, allowed: tuple[str, ...]) -> str:
    """段階外のツール呼び出しを断るときのメッセージ。

    S04 の `is_actionable()` が True になる形にしてある（許容値と次の一手を含む）。
    """
    return (f"いまは '{state}' の段階なので、ツール '{name}' は実行できません。"
            f"この段階で使えるツール: {', '.join(allowed) if allowed else 'なし'}。")


# ---------------------------------------------------------------------------
# 信頼境界（成果物②）。「誰が書いた文字列か」でゾーンを分ける
# ---------------------------------------------------------------------------
TRUST_ZONES: tuple[tuple[str, str, str], ...] = (
    ("利用者の依頼", "信頼できる", "誰が書いたか分かっている"),
    ("規程・経費データ（policies / expenses）", "信頼できる", "社内で管理された構造化データ"),
    ("社員データ（employees）", "信頼できるが機密", "住所・評価は許可リストで持たせない"),
    ("社内文書（docs）", "信頼できない", "本文は社内の誰でも書き換えられる（DOC-0004 に注入）"),
    ("作業領域のファイル", "信頼できない", "前の走行や他人が書いたもの"),
    ("外部システムの応答", "信頼できない", "経費・予約・チャットが返す文字列も外から来る"),
    ("隔離コンテナ（tool-runner）", "信頼しない前提で囲う", "ネットワークなし・読み取り専用"),
)

# 検査の置き場所（4カ所）。どの層がどの脅威を止めるかを1対1で言えるようにする
CHECKPOINTS: tuple[tuple[str, str, str], ...] = (
    ("入力検査・構造分離", "ツール結果が戻った直後", "注入の混入を検出して隔離する（警告は出るが止めない）"),
    ("権限制限", "レジストリを組むとき", "要らない道具を持たせない（機密流入を止める）"),
    ("引数の確定", "呼び出しを組み立てるとき", "金額・宛先・冪等キーをモデルに書かせない"),
    ("出力検査", "実行の直前", "外へ出る宛先と本文をコードで検査する（越境を止める）"),
    ("人間承認", "取り返しのつかない操作の前", "実行を人の判断まで持ち上げる"),
)

TRUST_BOUNDARY_MERMAID = """flowchart LR
    user["利用者の依頼<br/>信頼できる"]
    human(["承認者（人間）"])
    subgraph untrusted["信頼できない入力"]
        docs["社内文書 docs.jsonl<br/>DOC-0004 に注入"]
        wsin["作業領域のファイル"]
    end
    subgraph trusted["信頼できる構造化データ"]
        pol["規程 policies.jsonl"]
        exp["経費 expenses.jsonl"]
        emp["社員 employees.jsonl<br/>住所・評価（機密）"]
    end
    subgraph app["app コンテナ（エージェント本体）"]
        agent["OpsAgent<br/>状態・計画・監査ログ"]
        detect{{"入力検査・構造分離"}}
        confirm{{"引数の確定"}}
        inspect{{"出力検査"}}
    end
    subgraph runner["tool-runner（隔離実行）"]
        calc["集計コード<br/>network none / read_only"]
    end
    subgraph exits["出口"]
        room["予約システム"]
        expsys["経費システム"]
        chat["社内チャット"]
        outside["社外（越境）"]
    end
    user --> agent
    docs --> detect
    wsin --> detect
    detect --> agent
    pol --> agent
    exp --> agent
    emp -. 許可リストで持たせない .-> agent
    agent -- 渡してよい列だけ --> calc
    calc -- 標準出力と参照 --> agent
    agent --> confirm --> inspect
    inspect -- 承認が必要 --> human
    human -- 承認/却下 --> inspect
    inspect --> room
    inspect --> expsys
    inspect --> chat
    inspect -. 遮断 .-> outside"""


def approval_flow_mermaid() -> str:
    """承認フロー図（成果物①）。状態機械から生成するので実装とずれない。"""
    return build_machine().to_mermaid()


def render_checkpoints() -> str:
    lines = ["| 検査 | どこで効くか | 何を止めるか |", "| :--- | :--- | :--- |"]
    lines += [f"| {name} | {where} | {what} |" for name, where, what in CHECKPOINTS]
    return "\n".join(lines)


def render_zones() -> str:
    lines = ["| 入力 | 信頼 | 理由 |", "| :--- | :--- | :--- |"]
    lines += [f"| {name} | {level} | {note} |" for name, level, note in TRUST_ZONES]
    return "\n".join(lines)


def main() -> None:
    print("=== 成果物①：承認フロー図（状態機械から生成） ===")
    print(approval_flow_mermaid())
    print(f"\n状態 {len(TRANSITIONS) + len(TERMINAL)} / 遷移 {TRANSITION_COUNT} 本")
    print("\n=== 成果物②：信頼境界図 ===")
    print(TRUST_BOUNDARY_MERMAID)
    print("\n=== 信頼境界の分類 ===")
    print(render_zones())
    print("\n=== 検査の置き場所 ===")
    print(render_checkpoints())


if __name__ == "__main__":
    main()
