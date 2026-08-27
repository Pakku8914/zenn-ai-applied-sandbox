#!/usr/bin/env python3
"""復習02：会話履歴の中身を数え、圧縮方式を比べる（すべて決定的・LLM 呼び出し 0 回）。

    docker compose exec app python src/review02/memo.py

本物の会話履歴は S03・S06 の `build_messages()` が作る。ただし本物の履歴は文字数が
1文字ずれても数値が変わるため、ここでは **長さを明示した疑似履歴** を使う。
`padded()` が「必ずこの語を含む、ちょうど N 文字」のテキストを作るので、
近似トークン数（比較用＝文字数÷3）を実行前に予測できる。

疑似履歴の形は S06 の完走軌跡（9手）と同じ流れをなぞっている。
  指示 → 規程 → 申請一覧 → 文書検索 → 申請一覧（再取得）→ まとめ
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from _paths import setup

ROOT = setup()

from agentkit.memory import (ShortTermMemory, approx_tokens,  # noqa: E402
                             extract_constraints)

# 近似トークンの予算（比較用の値。実 API の上限ではない）
BUDGET = 600

# 要約したツール結果の長さ（1件あたり）
SUMMARY_CHARS = 120

# 判定基準。状態へ移すときに一緒に持っていく
THRESHOLD = 50_000

# 最初の指示に含まれる制約。1文字も変えずに残っているかを数える
CONSTRAINTS = (
    "1件5万円以上は事前承認が必要。",
    "領収書は必ず添付する。",
    "送信は所属長の確認を経てから行う。",
)

# 判断に必要な事実。ツール結果の中にしか無い
FACTS = ("EXP-0002", "EXP-0004")


@dataclass(frozen=True)
class Item:
    """会話履歴の1項目。

    kind  … instruction（最初の指示）/ tool（ツール結果）/ thought（思考）
    tag   … 何の項目か（ツール名）
    chars … 文字数。近似トークン数は chars // 3 になる
    marks … その項目にしか書かれていない語（残っているかを数える目印）
    """

    kind: str
    tag: str
    chars: int
    marks: tuple[str, ...] = ()


HISTORY = (
    Item("instruction", "task", 300, CONSTRAINTS),
    Item("tool", "get_policy", 150),
    Item("tool", "list_expenses", 1038, FACTS),
    Item("tool", "search_docs", 1200),
    Item("tool", "list_expenses_2", 900),
    Item("thought", "wrap_up", 60),
)


def padded(chars: int, *parts: str) -> str:
    """指定した語を必ず含む、ちょうど `chars` 文字のテキストを作る。

    足りない分は「…」で埋める。埋め草に「。」を入れないのが要点で、
    こうしておくと制約の抽出（`extract_constraints`）が埋め草に反応しない。
    """
    core = "／".join(parts)
    if len(core) > chars:
        raise ValueError(f"{chars} 文字には収まりません（{len(core)} 文字必要です）")
    return core + "…" * (chars - len(core))


def render(item: Item) -> str:
    return padded(item.chars, f"[{item.tag}]", *item.marks)


def to_memory(items) -> ShortTermMemory:
    return ShortTermMemory(items=[render(i) for i in items], max_tokens=BUDGET)


# ---------------------------------------------------------------------------
# コンテキストの中身を数える
# ---------------------------------------------------------------------------
def dominance(items=HISTORY) -> dict:
    """入力のうち、ツール結果が占める割合。溢れる原因はここにある。"""
    total = sum(approx_tokens(render(i)) for i in items)
    tool = sum(approx_tokens(render(i)) for i in items if i.kind == "tool")
    return {"合計": total, "ツール結果": tool, "割合(%)": tool * 100 // total,
            "項目数": len(items),
            "ツール結果の項目数": sum(1 for i in items if i.kind == "tool")}


def constraint_items(items=HISTORY) -> list[str]:
    """`extract_constraints` が制約だと判定する項目（選択的保持が守る対象）。"""
    return [i.tag for i in items if extract_constraints(render(i))]


# ---------------------------------------------------------------------------
# 圧縮方式（4種）＋「状態へ移してから捨てる」
# 戻り値はどれも (短期メモリ, 状態) の組にそろえる
# ---------------------------------------------------------------------------
def as_is(items=HISTORY) -> tuple[ShortTermMemory, dict]:
    """何もしない。予算を超えたまま送ることになる。"""
    return to_memory(items), {}


def truncate(items=HISTORY) -> tuple[ShortTermMemory, dict]:
    """古いものから捨てる。最初の指示（＝制約）が最初に消える。"""
    return to_memory(items).truncate_oldest(), {}


def summarize(items=HISTORY) -> tuple[ShortTermMemory, dict]:
    """ツール結果を短い要約に置き換える。行が消えるので個別の事実が落ちる。"""
    shrunk = [Item(i.kind, i.tag, SUMMARY_CHARS) if i.kind == "tool" else i
              for i in items]
    return to_memory(shrunk), {}


def keep_selected(items=HISTORY) -> tuple[ShortTermMemory, dict]:
    """制約らしい項目を必ず残し、それ以外を古い順に捨てる（選択的保持）。"""
    return to_memory(items).keep_constraints(), {}


def state_first(items=HISTORY) -> tuple[ShortTermMemory, dict]:
    """捨てる前に、判断に必要なものを状態へ移す（S06 × S07 の合わせ技）。

    履歴は「切り捨て」と同じところまで削るが、制約と事実は状態に残るので
    プロンプトへ毎回投影できる。捨てたのは本文だけである。
    """
    state = {"制約": list(CONSTRAINTS), "事実": list(FACTS), "判定基準": THRESHOLD}
    return to_memory(items).truncate_oldest(), state


METHODS = (
    ("そのまま", as_is),
    ("切り捨て", truncate),
    ("要約", summarize),
    ("選択的保持", keep_selected),
    ("状態へ移す＋切り捨て", state_first),
)


def kept(memory: ShortTermMemory, state: dict, targets) -> int:
    """圧縮後の履歴＋状態に、目印がいくつ残っているかを数える。"""
    text = memory.render() + json.dumps(state, ensure_ascii=False)
    return sum(1 for t in targets if t in text)


def compare(items=HISTORY) -> list[dict]:
    rows: list[dict] = []
    for name, fn in METHODS:
        memory, state = fn(items)
        constraints = kept(memory, state, CONSTRAINTS)
        facts = kept(memory, state, FACTS)
        rows.append({
            "方式": name,
            "近似トークン": memory.total_tokens(),
            "制約": f"{constraints}/{len(CONSTRAINTS)}",
            "事実": f"{facts}/{len(FACTS)}",
            "予算内": not memory.overflowing(),
            "再開できる": constraints == len(CONSTRAINTS) and facts == len(FACTS),
        })
    return rows


def mark(flag: bool) -> str:
    return "○" if flag else "×"


def main() -> None:
    print("=== 会話履歴の中身（近似トークン数（比較用）＝文字数÷3）===")
    print("項目 | 種別 | 文字数 | 近似トークン")
    for item in HISTORY:
        print(f"{item.tag} | {item.kind} | {item.chars} | {approx_tokens(render(item))}")
    d = dominance()
    print(f"ツール結果が占める割合: {d['ツール結果']} / {d['合計']} = {d['割合(%)']}%")
    print(f"制約だと判定される項目: {constraint_items()}")

    print()
    print(f"=== 圧縮方式の比較（予算 {BUDGET} 近似トークン）===")
    print("方式 | 近似トークン | 制約 | 事実 | 予算内 | 再開できる")
    for row in compare():
        print(f"{row['方式']} | {row['近似トークン']} | {row['制約']} | {row['事実']} | "
              f"{mark(row['予算内'])} | {mark(row['再開できる'])}")


if __name__ == "__main__":
    main()
