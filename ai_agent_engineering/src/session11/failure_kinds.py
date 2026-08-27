#!/usr/bin/env python3
"""失敗の切り分けと、再試行の可否判定（セッション11）。

「例外が出たからもう一度」は設計ではない。次の3つを別々に判定する。

  1. どういう失敗か     … 部分的 / 恒久的 / 一時的 / 分類できない
  2. 同じ引数で通るのか … エラーが代替案を示しているか（セッション4の is_actionable の考え方）
  3. 再試行してよいのか … その操作が冪等かどうか（宣言ではなく実装で決まる）

LLM は使わない。文字列の検査だけで決定的に判定する。判定に LLM を使うと、
「再試行してよいか」の判断そのものが不確実になり、二重実行の原因になる。
"""

from __future__ import annotations

from dataclasses import dataclass

# --- 失敗の種類 -------------------------------------------------------------
PARTIAL = "partial"       # 部分的：実行されたかどうかが呼び出し側から分からない
PERMANENT = "permanent"   # 恒久的：同じ入力なら何度呼んでも同じ結果になる
TRANSIENT = "transient"   # 一時的：時間をおけば結果が変わりうる
UNKNOWN = "unknown"       # 分類できない

KINDS = (PARTIAL, PERMANENT, TRANSIENT, UNKNOWN)
KIND_JA = {PARTIAL: "部分的", PERMANENT: "恒久的", TRANSIENT: "一時的", UNKNOWN: "不明"}

# 判定は「取り違えたときの被害が大きい順」に見る。
# 部分的を一時的と誤ると二重実行になる。恒久的を一時的と誤ると無駄な再試行が増える。
PARTIAL_MARKS = ("応答が返りませんでした", "確認できません", "結果を取得できませんでした",
                 "状態が不明")
PERMANENT_MARKS = ("存在しません", "見つかりません", "既に予約されています",
                   "不正です", "権限がありません",
                   "ValueError", "TypeError", "KeyError", "400", "403", "404")
TRANSIENT_MARKS = ("一時的", "タイムアウト", "timeout", "混雑", "しばらく",
                   "TimeoutError", "ConnectionError", "429", "503")

# 「次の行動が示されているか」と「具体的な候補が示されているか」の両方が要る。
# 片方だけの文（「やり直してください」だけ、候補の羅列だけ）はモデルが動けない。
NEXT_ACTION_MARKS = ("してください", "指定できる", "使えるツール", "選び直")
CANDIDATE_MARKS = ("別の", "指定できる", ": ", "例:", "いずれか", "次の中から",
                   "までです", "分割")

# 再試行の判断（`Decision.action` が取りうる値）
RETRY_SAME = "retry_same"        # 同じ引数でもう一度呼ぶ
RETRY_ALTERED = "retry_altered"  # 引数を変えて呼び直す（＝モデルに選び直させる）
HANDOFF = "handoff"              # 人に渡す
STOP = "stop"                    # 何もせず失敗として終える

ACTION_JA = {RETRY_SAME: "同じ引数で再試行", RETRY_ALTERED: "引数を変えて再試行",
             HANDOFF: "人に渡す", STOP: "再試行しない"}


@dataclass(frozen=True)
class Decision:
    """再試行の判断。理由を必ず持たせる（あとで軌跡から追えるようにするため）。"""

    action: str
    kind: str
    reason: str


def _has(message: str, marks: tuple[str, ...]) -> bool:
    return any(m in message for m in marks)


def classify_error(message: str) -> str:
    """エラーメッセージから失敗の種類を決める（決定的）。"""
    if not message:
        return UNKNOWN
    if _has(message, PARTIAL_MARKS):
        return PARTIAL
    if _has(message, PERMANENT_MARKS):
        return PERMANENT
    if _has(message, TRANSIENT_MARKS):
        return TRANSIENT
    return UNKNOWN


def classify_exception(exc: BaseException) -> str:
    """例外を分類する。型名も判定材料に含める。"""
    return classify_error(f"{type(exc).__name__}: {exc}")


def has_alternative(message: str) -> bool:
    """「引数を変えれば通る」手がかりがメッセージに含まれているか。"""
    return _has(message, NEXT_ACTION_MARKS) and _has(message, CANDIDATE_MARKS)


def retry_decision(message: str, *, idempotent: bool, attempts: int = 1,
                   max_retries: int = 1) -> Decision:
    """1回の失敗に対して、次に何をするかを決める。

    attempts は「いま何回目の試行だったか」（1始まり）。
    """
    kind = classify_error(message)
    alt = has_alternative(message)

    # 分類できないが代替案が書いてある＝呼び方を変えれば通る見込みがある
    if kind == UNKNOWN and alt:
        kind = PERMANENT

    if kind == PERMANENT:
        if alt:
            return Decision(RETRY_ALTERED, kind,
                            "同じ引数では通らない。示された候補から選び直させる")
        return Decision(STOP, kind, "同じ引数でも通らず、代替案も示されていない")

    if kind == UNKNOWN:
        return Decision(HANDOFF, kind, "分類できない失敗。勝手に再試行しない")

    # ここから先は一時的・部分的。ここで冪等性を見るのが本章の要点
    if not idempotent:
        return Decision(HANDOFF, kind,
                        "冪等でない操作は、実行されたか分からないまま再送しない")
    if attempts > max_retries:
        return Decision(HANDOFF, kind, f"再試行の上限（{max_retries}回）に達した")
    return Decision(RETRY_SAME, kind, "冪等なので同じ引数で再試行してよい")


# --- 本文・練習問題で使うサンプル -------------------------------------------
DECISION_CASES: list[tuple[str, str, bool]] = [
    ("会議室の競合",
     "みなと の 10:00 は既に予約されています。別の時間帯（例: 11:00）"
     "または別の会議室を指定してください。", False),
    ("存在しない会議室",
     "会議室 'かもめ' は存在しません。指定できる会議室: うみかぜ, ふ頭, みなと, 大会議室", False),
    ("連続利用の上限",
     "連続利用は4時間（240分）までです。分割して予約してください。", False),
    ("接続できない（冪等なツール）",
     "経費システムに接続できませんでした（一時的な障害）。"
     "しばらく待ってから同じ内容で再実行してください。", True),
    ("接続できない（冪等でないツール）",
     "経費システムに接続できませんでした（一時的な障害）。"
     "しばらく待ってから同じ内容で再実行してください。", False),
    ("応答が返らない（冪等なツール）",
     "経費システムから応答が返りませんでした（タイムアウト）。"
     "申請が登録されたかどうかは確認できません。", True),
    ("応答が返らない（冪等でないツール）",
     "経費システムから応答が返りませんでした（タイムアウト）。"
     "申請が登録されたかどうかは確認できません。", False),
    ("引数の型が違う",
     "引数 'amount' は整数で指定してください（受け取った値: '68,000'）。", False),
    ("内部エラー", "内部エラー（ZeroDivisionError）", True),
]


def render_decisions(cases: list[tuple[str, str, bool]] | None = None) -> str:
    """判断の一覧を Markdown 表で返す（本文の表の出典）。"""
    rows = ["| ケース | 種類 | 代替案 | 冪等 | 判断 |",
            "| :--- | :--- | :--- | :--- | :--- |"]
    for label, message, idem in (cases or DECISION_CASES):
        d = retry_decision(message, idempotent=idem, attempts=1, max_retries=1)
        rows.append(f"| {label} | {KIND_JA[d.kind]} | "
                    f"{'あり' if has_alternative(message) else 'なし'} | "
                    f"{'はい' if idem else 'いいえ'} | {ACTION_JA[d.action]} |")
    return "\n".join(rows)


if __name__ == "__main__":
    print(render_decisions())
