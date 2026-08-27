#!/usr/bin/env python3
"""3択の判定：ワークフロー / ツール付き単発呼び出し / エージェント。

判断基準を文章で書くと、人によって答えがぶれる。特徴を数個に絞って表にし、
コードにしてしまえば「なぜこの要求をエージェントにしたのか」を後から検証できる。

**練習問題を解く前に読まないこと**（基礎2・実践1 の参照解）。
"""

from __future__ import annotations

from dataclasses import dataclass

WORKFLOW = "ワークフロー"
SINGLE_CALL = "ツール付き単発呼び出し"
AGENT = "エージェント"


@dataclass(frozen=True)
class Request:
    """業務要求を、判断に必要な特徴だけで表す。"""

    name: str
    path_fixed: bool           # 経路（どのツールをどの順で呼ぶか）を事前に列挙できるか
    needs_judgment: bool       # 自然言語の解釈・分類・要約が必要か
    steps: int                 # 想定される外部操作の手数（事前に分からないときは 0）
    failure_tolerance: str     # low / medium / high（間違えたときに許されるか）
    irreversible: bool = False  # 取り返しのつかない副作用を含むか
    audit: str = "normal"       # normal / strict（監査・説明責任の要求）


@dataclass(frozen=True)
class Decision:
    choice: str
    reason: str
    guardrails: tuple[str, ...] = ()


def choose(req: Request) -> Decision:
    """3択を決める。上から順に判定し、最初に当たったものを返す。"""
    if not req.path_fixed:
        # 経路が決まらない仕事だけがエージェントの領分。ただし上限は必ず付ける
        guardrails = ["ステップ上限", "コスト上限", "軌跡の記録"]
        if req.irreversible:
            guardrails.append("承認ゲート")
        if req.failure_tolerance == "low" or req.audit == "strict":
            guardrails.append("最終出力を人間が確認する")
        return Decision(
            AGENT, "経路が事前に決まらないので、実行時に次の手を決める必要がある",
            tuple(guardrails))

    if req.steps <= 1 and req.needs_judgment:
        # 呼ぶツールは1つに決まっていて、必要なのは言葉の解釈だけ。ループは不要
        return Decision(
            SINGLE_CALL, "経路は1手で固定できる。必要なのは自然言語の判断だけ",
            ("入力の検査", "出力の形式検査"))

    return Decision(
        WORKFLOW, "経路も例外処理も事前に列挙できる。ループは不要",
        ("分岐の網羅性を定期的に見直す",))


# みなと商事から来た5つの業務要求。特徴の付け方そのものが設計判断である
REQUESTS = [
    Request("経費の分類", path_fixed=True, needs_judgment=True, steps=1,
            failure_tolerance="medium"),
    Request("会議室の予約", path_fixed=True, needs_judgment=False, steps=2,
            failure_tolerance="medium", irreversible=False),
    Request("問い合わせの一次回答", path_fixed=True, needs_judgment=True, steps=1,
            failure_tolerance="medium"),
    Request("月次レポート作成", path_fixed=True, needs_judgment=True, steps=3,
            failure_tolerance="medium"),
    Request("規程改定の影響調査", path_fixed=False, needs_judgment=True, steps=0,
            failure_tolerance="high"),
]


def describe(req: Request) -> str:
    return (f"経路固定={'○' if req.path_fixed else '×'}"
            f" / 判断={'要' if req.needs_judgment else '不要'}"
            f" / 手数={req.steps if req.steps else '不明'}"
            f" / 失敗の許容度={req.failure_tolerance}"
            f" / 監査={req.audit}")


def main() -> None:
    print("=== 5つの業務要求を3択に振り分ける ===")
    for req in REQUESTS:
        decision = choose(req)
        print(f"\n--- {req.name} ---")
        print(f"選択: {decision.choice}")
        print(f"特徴: {describe(req)}")
        print(f"理由: {decision.reason}")
        print(f"付ける仕掛け: {' / '.join(decision.guardrails)}")

    print("\n=== 同じ要求でも、副作用と監査要件が変われば仕掛けが増える ===")
    risky = Request("規程改定の影響調査（社外へ通知まで行う）", path_fixed=False,
                    needs_judgment=True, steps=0, failure_tolerance="low",
                    irreversible=True, audit="strict")
    decision = choose(risky)
    print(f"選択: {decision.choice}")
    print(f"付ける仕掛け: {' / '.join(decision.guardrails)}")


if __name__ == "__main__":
    main()
