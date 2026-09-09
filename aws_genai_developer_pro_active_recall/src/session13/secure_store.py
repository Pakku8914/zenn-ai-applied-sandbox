#!/usr/bin/env python3
"""セッション13: 会話履歴の保存経路に匿名化を挟む。

セッション6の `conversation_store` は **1文字も変えません**。
保存の窓口をこのモジュールに1本だけ作り、その中で

    ① 格付けで「入れてよいか」を決める（拒否ならここで終わり）
    ② 伏せる（ガードレール → 自社書式 → アプリが知っている値）
    ③ はじめて保存する（`conversation_store.append_turn` を呼ぶ）

の順に通します。**順序が設計です。** ②を先にすると、機密のデータが
「伏せるため」という理由で外部の API へ出てしまいます。
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session06")
sys.path.insert(0, "/workspace/src/session13")

from awskit import clients  # noqa: E402

import conversation_store as store  # noqa: E402

import anonymize  # noqa: E402
import classification as cls  # noqa: E402


class BlockedError(Exception):
    """格付けで止めた。**外部に1回も出さず、保存もしない。**"""


@dataclass(frozen=True)
class Saved:
    conversation_id: str
    turn_no: int
    action: str
    level: str
    text: str
    audit: dict


def ingest(
    runtime,
    ddb,
    *,
    conversation_id: str,
    turn_no: int,
    role: str,
    text: str,
    kind: str,
    known: dict[str, str] | None = None,
) -> Saved:
    """1ターンを、格付け → 匿名化 → 保存の順で受け入れる。"""
    # ① まず格付け。ここで止まれば、ガードレールにも基盤モデルにも渡さない
    verdict = cls.judge_kind(kind)
    if verdict.action == cls.BLOCK:
        raise BlockedError(
            f"{kind}（{verdict.level}）: {verdict.reason} [{verdict.rule}]"
        )

    # ② 伏せる。申告が無い経路でも必ず通す（申告漏れを捕まえる二重の網）
    masked = anonymize.scrub(runtime, text, known=known)
    undeclared = verdict.action == cls.SEND and bool(masked.entities)

    # ③ 保存はセッション6の関数に任せる。渡すのは伏せたあとの本文だけ
    store.append_turn(ddb, conversation_id, turn_no, role, masked.text)

    audit = {
        "kind": kind,
        "level": verdict.level,
        "action": verdict.action,
        "rule": verdict.rule,
        "undeclared": undeclared,
        **masked.summary(),
    }
    return Saved(conversation_id, turn_no, verdict.action, verdict.level, masked.text, audit)


DEMO: tuple[tuple[str, str, dict[str, str] | None], ...] = (
    (
        "問い合わせ本文",
        anonymize.SAMPLE_TURN,
        # フォームの氏名欄・住所欄から取れる値。**知っている値は探さずに消す**
        {"NAME": "山田太郎", "ADDRESS": "東京都千代田区1-1-1"},
    ),
    ("社内FAQ", "格付け: 社内限定\n返却先は support@example.com でよいですか。", None),
    ("顧客マスタの抜粋", "格付け: 機密\n顧客一覧を貼ります。", None),
)


def main() -> None:
    runtime = clients.bedrock_runtime()
    ddb = store.ensure_table()
    conversation_id = f"s13-demo-{int(time.time())}"

    print("=== 保存経路（格付け → 匿名化 → 保存） ===")
    for turn_no, (kind, text, known) in enumerate(DEMO, start=1):
        try:
            saved = ingest(
                runtime,
                ddb,
                conversation_id=conversation_id,
                turn_no=turn_no,
                role="user",
                text=text,
                kind=kind,
                known=known,
            )
        except BlockedError as error:
            print(f"{kind} | block | 保存も外部呼び出しもしていません（{error}）")
            continue
        note = (
            f"申告なしの PII を検出: {saved.audit['piiTypes']}"
            if saved.audit["undeclared"]
            else "保存しました"
        )
        print(f"{kind} | {saved.action} | {note}")

    print()
    print("=== 保存された本文（原文は1文字も入っていない） ===")
    for row in store.turns(ddb, conversation_id):
        print(f"turn{row['turnNo']}: {row['text'].splitlines()[-1]}")


if __name__ == "__main__":
    main()
