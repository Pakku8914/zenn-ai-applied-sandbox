#!/usr/bin/env python3
"""セッション8: 監督役と専門役に分ける（マルチエージェント）。

単一エージェントに道具を足し続けると、ツール選択の誤りとプロンプトの肥大が同時に進みます。
そこで**監督役（supervisor）が担当を決め、専門役（specialist）が小さな道具箱で解く**形にします。

    result = run_squad(runtime, client, tools, "出張の宿泊費の上限はいくらですか？",
                       executor=executor)
    result["role"]           # -> "expense_agent"
    result["exposed_tools"]  # -> 専門役に渡した道具だけ

:::注意:::
実務の監督役は、小型モデル（`amazon.nova-micro-v1:0`）に分類させるのが定石です。
同梱モックの分類応答は固定の3ラベルしか返さないため、ここは**決定的なルーティング表**で
代替しています（AWS Agent Squad も同梱モックには無いので、本文では概念として扱います）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "/workspace")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_agent  # noqa: E402
import mcp_client  # noqa: E402

# 先に一致した行が勝つ。曖昧さを表が隠してしまう点が、この方式の弱点
ROUTES: list[tuple[str, tuple[str, ...]]] = [
    ("expense_agent", ("出張", "宿泊", "旅費", "経費", "精算", "交際費", "備品", "領収書")),
    ("it_agent", ("VPN", "パスワード", "PC", "接続", "ロック", "ポータル", "勤怠")),
    ("hr_agent", ("有給", "休暇", "在宅勤務", "資格", "手当", "繰越")),
]

SPECIALISTS: dict[str, dict] = {
    "expense_agent": {
        "tools": ["search_internal_docs", "lookup_expense_report"],
        "model_id": "amazon.nova-lite-v1:0",
        "system": (
            "あなたはサンプル商事の経費精算の担当者です。"
            "規程の条文と申請の進捗だけを扱い、資料に無いことは推測しません。"
        ),
    },
    "it_agent": {
        "tools": ["search_internal_docs", "check_service_health"],
        "model_id": "amazon.nova-lite-v1:0",
        "system": (
            "あなたはサンプル商事の IT ヘルプデスクの担当者です。"
            "手順書と稼働状況だけを扱い、資料に無いことは推測しません。"
        ),
    },
    "hr_agent": {
        "tools": ["search_internal_docs"],
        "model_id": "amazon.nova-lite-v1:0",
        "system": (
            "あなたはサンプル商事の人事制度の担当者です。"
            "規程の条文だけを扱い、資料に無いことは推測しません。"
        ),
    },
    # 書き込みを伴う専門役。**チャットの経路からは呼ばれない**（route が返さない）。
    # 人が起票した変更作業のときだけ、承認ゲート付きの executor で起動する
    "it_write_agent": {
        "tools": ["search_internal_docs", "reset_user_password"],
        "model_id": "amazon.nova-lite-v1:0",
        "system": (
            "あなたはサンプル商事の IT 運用の担当者です。"
            "書き込みを伴う操作は、人の承認が下りてからしか実行できません。"
        ),
    },
}

# チャットの問い合わせから到達できる専門役
CHAT_ROLES = tuple(role for role, _ in ROUTES)

# 単一エージェントに持たせる読み取り専用の道具（比較用）
SINGLE_AGENT_TOOLS = [
    "search_internal_docs",
    "lookup_expense_report",
    "check_service_health",
    "run_maintenance_scan",
]

ESCALATION_MESSAGE = (
    "担当できる専門役がいないため、人の担当者に引き継ぎます。"
    "回答を作らずに引き継ぐのは、誤った案内を出さないためです。"
)


def route(question: str) -> str | None:
    """質問を専門役に割り当てる。担当が無ければ None（＝人へ引き継ぐ）。"""
    for role, terms in ROUTES:
        if any(term in question for term in terms):
            return role
    return None


def tools_for(role: str) -> list[str]:
    return list(SPECIALISTS[role]["tools"])


def run_squad(runtime, tools: list[dict], question: str, *, executor) -> dict:
    """監督役が担当を決め、専門役が小さな道具箱で答える。"""
    role = route(question)
    if role is None:
        # 監督役が「分からない」と言えることが、この構成の一番の価値
        return {
            "role": None,
            "escalated": True,
            "answer": ESCALATION_MESSAGE,
            "exposed_tools": [],
            "tool_calls": [],
            "model_calls": 0,
            "stop_reason": "escalated",
        }
    spec = SPECIALISTS[role]
    tool_config = mcp_client.to_tool_config(tools, names=spec["tools"])
    trace = mcp_agent.run_agent(
        runtime,
        question,
        tool_config=tool_config,
        executor=executor,
        system=spec["system"],
        model_id=spec["model_id"],
    )
    return {"role": role, "escalated": False, **trace}


def run_single(runtime, tools: list[dict], question: str, *, executor) -> dict:
    """比較用：1体のエージェントに読み取り系の道具を全部持たせる。"""
    tool_config = mcp_client.to_tool_config(tools, names=SINGLE_AGENT_TOOLS)
    trace = mcp_agent.run_agent(
        runtime, question, tool_config=tool_config, executor=executor
    )
    return {"role": "single_agent", "escalated": False, **trace}
