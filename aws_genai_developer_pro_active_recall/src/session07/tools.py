#!/usr/bin/env python3
"""セッション7: エージェントに持たせる「道具」と、その入力の検証。

道具はすべて同じプロセス内の Python 関数です（MCP でのツール公開と、複数エージェントへの
分担はセッション8で扱います）。本章の関心はこの2点だけです。

* ツールの `name` と `description` は、モデルが読む**唯一の仕様書**である
* モデルが返した `toolUse.input` は、**利用者の入力と同じ強度で検証する**

2点目は理屈ではなく実際に必要です。同梱モックは `category` に列挙値の外の文字列を
入れて返してくるため、検証せずにメタデータフィルタへ渡すと検索結果が0件になります。
実サービスでも「もっともらしいが仕様外の引数」は普通に返ってきます。
"""

from __future__ import annotations

import re
import sys

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session05")

import retriever  # noqa: E402

# 検索ツールは前章の定義をそのまま道具にする。定義を2か所に持つと、
# 検索側の仕様変更がエージェント側に伝わらない（説明文だけ古いという最悪の形になる）
SEARCH_TOOL = retriever.TOOL_SPEC

LEAVE_TOOL = {
    "toolSpec": {
        "name": "get_leave_balance",
        "description": (
            "社員の有給休暇の残日数を取得する。"
            "有給休暇の残日数を確認する必要がある質問で呼び出すこと。"
            "付与日数・取得済み日数・繰越日数の内訳を返す。"
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "employee_id": {
                        "type": "string",
                        "description": "社員番号。EMP-0000 の形式。推測してはならない",
                    }
                },
                "required": ["employee_id"],
            }
        },
    }
}

CONTACT_TOOL = {
    "toolSpec": {
        "name": "get_helpdesk_contact",
        "description": (
            "社内ヘルプデスクの担当窓口と内線番号を返す。"
            "回答の最後に問い合わせ先を案内するとき、"
            "または社内規程では判断できないときに呼び出すこと。"
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "問い合わせの分野"}
                },
                "required": ["topic"],
            }
        },
    }
}

TOOL_SPECS = [SEARCH_TOOL, LEAVE_TOOL, CONTACT_TOOL]
TOOL_CONFIG = {"tools": TOOL_SPECS}
TOOL_NAMES = tuple(spec["toolSpec"]["name"] for spec in TOOL_SPECS)

# 実行を許すツール。モデルに見せる一覧（toolConfig）とは別の層に置く。
# 実 AWS では、この許可リストに対応するものをツール側の IAM ポリシーで**もう一度**表す
DEFAULT_ALLOWED = frozenset(TOOL_NAMES)

# 検索ツールの引数の値域。スキーマに書いても守られる保証はないので、実行側でも持つ
CATEGORIES = ("IT", "経費", "人事", "セキュリティ")
DEFAULT_TOP_K = 3
MAX_TOP_K = 5
MAX_QUERY_CHARS = 100
MAX_TOPIC_CHARS = 30

EMPLOYEE_ID = re.compile(r"^EMP-\d{4}$")

# 資料と指示の境界を作るタグ。ツールの入力・出力に混ざっていたら必ず落とす。
# 残したまま `<context>` で包むと、資料の中から境界を閉じられる（間接的な指示の注入）
_BOUNDARY_TAG = re.compile(r"</?(?:context|documents|資料)>")


def sanitize(text: object) -> str:
    """境界タグを落として前後の空白を整える。ツールの入出力は必ずここを通す。"""
    return _BOUNDARY_TAG.sub("", str(text)).strip()


# ---------------------------------------------------------------------------
# 入力の検証（モデルの出力は「入力」である）
# ---------------------------------------------------------------------------


def validate_input(
    name: str,
    raw: dict,
    *,
    question: str = "",
    facts: dict | None = None,
) -> tuple[dict, list[str]]:
    """モデルが返した `toolUse.input` を、実行してよい引数に直す。

    返すのは (実際に渡す引数, 直した理由のリスト) です。理由を戻すのは、
    あとで「なぜこの引数で動いたのか」を追えるようにするためです（記録は監視へ出す）。
    """
    facts = facts or {}
    raw = raw if isinstance(raw, dict) else {}
    notes: list[str] = []

    if name == "search_internal_docs":
        raw_query = str(raw.get("query") or "")
        query = sanitize(raw_query)[:MAX_QUERY_CHARS]
        if query != raw_query.strip():
            notes.append("query から境界タグや上限を超える文字を落としました")
        if not query:
            # 社内用語辞書による書き換え（前章の to_keywords）に落とす。
            # 空の検索語で全件を引くより、決定的な既定値を使うほうが安全
            query = retriever.to_keywords(question) or question[:MAX_QUERY_CHARS]
            notes.append("query が空だったので質問から検索語を作りました")

        category = raw.get("category")
        if category is not None and category not in CATEGORIES:
            notes.append(f"category='{category}' は許可リスト外なので破棄しました")
            category = None

        top_k = raw.get("top_k")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= MAX_TOP_K:
            notes.append(f"top_k={top_k!r} は範囲外なので {DEFAULT_TOP_K} に直しました")
            top_k = DEFAULT_TOP_K
        return {"query": query, "category": category, "top_k": top_k}, notes

    if name == "get_leave_balance":
        raw_id = sanitize(raw.get("employee_id") or "")
        if not EMPLOYEE_ID.match(raw_id):
            # 識別子はモデルに作らせない。長期メモリにある確定した値を使う
            remembered = facts.get("employeeId", "")
            notes.append(
                f"employee_id='{raw_id}' は形式が不正なので長期メモリの値に差し替えました"
            )
            raw_id = remembered
        return {"employee_id": raw_id}, notes

    if name == "get_helpdesk_contact":
        topic = sanitize(raw.get("topic") or "")[:MAX_TOPIC_CHARS] or "全般"
        return {"topic": topic}, notes

    # 検証規則を書いていないツールは実行しない（fail closed）
    raise KeyError(f"検証規則のないツールです: {name}")


# ---------------------------------------------------------------------------
# ツールの実装（すべて自プロセス内の関数）
# ---------------------------------------------------------------------------

LEAVE_BALANCE = {
    "EMP-0042": (
        "あなたの有給休暇の残日数は12日です。"
        "今年度の付与は10日、前年度からの繰越は5日、取得済みは3日です。"
    )
}

CONTACT_TEXT = (
    "人事制度の問い合わせ窓口は人事部ヘルプデスク（内線1234）です。"
    "受付時間は平日9時から17時までです。"
)


def search_internal_docs(
    agent,
    *,
    query: str,
    category: str | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> str:
    """社内文書を検索し、出典付きの抜粋を返す（前章の `search()` をそのまま使う）。"""
    hits = retriever.search(agent, query, mode="HYBRID", top_k=top_k, category=category)
    if not hits:
        return "該当する社内文書は見つかりませんでした。"
    lines: list[str] = []
    for hit in hits:
        # 出典を先に書く。あとで回答に出典を付けられるのは、観測にそれが残っているときだけ
        lines.append(f"出典: {hit['uri']}（{hit['title']}）")
        lines.append(sanitize(hit["text"]))
    return "\n".join(lines)


def get_leave_balance(*, employee_id: str) -> str:
    """社員番号から残日数を引く。形式が違えば実行しない。"""
    if not EMPLOYEE_ID.match(str(employee_id)):
        raise ValueError(f"社員番号の形式が不正です: {employee_id!r}")
    return LEAVE_BALANCE.get(
        employee_id, "その社員番号の残日数は登録されていません。"
    )


def get_helpdesk_contact(*, topic: str) -> str:
    """担当窓口を返す。実務では topic で窓口表を引くが、教材では固定値にしている。"""
    return CONTACT_TEXT


def call(name: str, args: dict, *, agent=None) -> str:
    """名前でツールを実行する。ここに無い名前は実行できない。"""
    if name == "search_internal_docs":
        return search_internal_docs(agent, **args)
    if name == "get_leave_balance":
        return get_leave_balance(**args)
    if name == "get_helpdesk_contact":
        return get_helpdesk_contact(**args)
    raise KeyError(f"実装のないツールです: {name}")
