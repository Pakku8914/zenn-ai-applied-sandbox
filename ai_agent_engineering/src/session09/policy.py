#!/usr/bin/env python3
"""コード実行を許すかどうかの判断（セッション9）。

ここには実行の実装を置かない（実行の入口は guard.py の1本に絞る）。
判断を純粋関数にしておくと、設計レビューの結論をテストとして残せる。

    python src/session09/policy.py
"""

from __future__ import annotations

from dataclasses import dataclass

# 3択。「許す／許さない」の2択にしないことが要点
CHOICES = ("許さない", "限定的に許す", "隔離して許す")


@dataclass(frozen=True)
class Request:
    """コード実行を許すかどうかを決めるための入力。"""

    name: str
    enumerable: bool       # やることを事前に列挙できるか（できるならツールにすればよい）
    personal_data: bool    # 個人情報に触るか
    per_call_audit: bool   # 実行1件ごとに内容を監査で示す必要があるか
    isolated: bool         # 隔離実行環境を用意・維持できるか


def decide(req: Request) -> tuple[str, str]:
    """3択のどれを選ぶかと、その理由を返す。"""
    if not req.isolated:
        return "許さない", "隔離できる場所が無い。同じ場所で動かすのは許可ではなく事故"
    if req.enumerable:
        return "限定的に許す", "やることを列挙できる。ツールとして出せば任意コードは不要"
    if req.personal_data and req.per_call_audit:
        return "限定的に許す", "任意コードは1件ごとの監査に耐えない。許可した集計だけを出す"
    return "隔離して許す", "経路が事前に決まらず、隔離の境界をテストで示せる"


CASES = [
    Request("経費申請の合計を出す",
            enumerable=True, personal_data=False, per_call_audit=False, isolated=True),
    Request("毎月書式が変わる CSV を取り込んで整形する",
            enumerable=False, personal_data=False, per_call_audit=False, isolated=True),
    Request("経費の推移を図にする",
            enumerable=False, personal_data=False, per_call_audit=False, isolated=True),
    Request("社員名簿から部門別の人数を数える",
            enumerable=False, personal_data=True, per_call_audit=True, isolated=True),
    Request("本番データベースを直すスクリプトを動かす",
            enumerable=False, personal_data=True, per_call_audit=True, isolated=False),
    Request("取引先から届いたスクリプトを社内環境で動かす",
            enumerable=False, personal_data=True, per_call_audit=False, isolated=False),
]


def predict_nonroot(run_as_uid: int, dir_owner_uid: int, other_writable: bool,
                    needs_write: bool) -> str:
    """非 root 実行にしたとき、共有ディレクトリに書けるかを予測する。

    `cap_drop: [ALL]` で CAP_DAC_OVERRIDE を落としているため、
    「root なら所有者に関係なく書ける」は成り立たない前提で判定する。
    """
    if not needs_write:
        return "読み取りだけなら動く"
    if run_as_uid == dir_owner_uid:
        return "書ける（所有者が一致している）"
    if other_writable:
        return "書ける（その他ユーザーに書き込みが開いている）"
    return "書けない（Permission denied）"


NONROOT_CASES = [
    (0, 0, False, True),
    (1000, 0, False, True),
    (1000, 0, True, True),
    (1000, 1000, False, True),
    (1000, 0, False, False),
    (0, 1000, False, True),
]


def yn(flag: bool) -> str:
    return "はい" if flag else "いいえ"


def render() -> str:
    lines = ["=== コード実行を許すかどうかの判断 ===",
             "要求 | 列挙できる | 個人情報 | 件別監査 | 隔離できる | 判断"]
    for req in CASES:
        choice, _ = decide(req)
        lines.append(f"{req.name} | {yn(req.enumerable)} | {yn(req.personal_data)} | "
                     f"{yn(req.per_call_audit)} | {yn(req.isolated)} | {choice}")
    return "\n".join(lines)


def render_nonroot() -> str:
    lines = ["=== 非 root 実行にしたときの予測 ===",
             "実行 uid | 所有者 uid | その他書き込み | 書き込みが必要 | 予測"]
    for uid, owner, other, need in NONROOT_CASES:
        lines.append(f"{uid} | {owner} | {yn(other)} | {yn(need)} | "
                     f"{predict_nonroot(uid, owner, other, need)}")
    return "\n".join(lines)


def main() -> None:
    print(render())
    print()
    print(render_nonroot())


if __name__ == "__main__":
    main()
