#!/usr/bin/env python3
"""runbook（成果物⑥）。人が夜中に読んでも動ける手順にする。

    python src/mid02/runbook.py     # 2枚の runbook を生成して workspace に置く

runbook に書くのは「何が起きたか」ではなく「**次に何をするか**」である。
だから各手順は、実際に打てるコマンドか、実際に押せるボタンで書く。

2枚だけ用意する。この業務で人が呼び出される事象がこの2つだからである。

  1. 承認が滞ったとき   … `awaiting_approval` のまま進まない
  2. 二重実行が起きたとき … 同じ内容の申請が2件見える／実行されたか分からない操作が残った
"""

from __future__ import annotations

from _paths import setup

ROOT = setup()

from agentkit.biztools import WORKSPACE  # noqa: E402

from flow import RUNBOOK_DOUBLE_PATH, RUNBOOK_STALLED_PATH  # noqa: E402

SECTIONS = ("## 症状", "## 確認", "## 手順", "## やってはいけないこと", "## 再発防止")

STALLED = f"""# runbook: 承認が滞ったとき

## 症状

- 走行が `stop_reason=awaiting_approval` のまま進まない
- 承認画面に何も出ていない、または誰が押すべきか分からない
- 期限（既定 24 時間）が近い、あるいは過ぎている

## 確認

1. 保留中の内容と期限を見る（**中身を読まずに承認しない**）

       docker compose exec app python src/mid02/ops_agent.py

2. 監査ログの `requested` 行で、いつ・どの内容で・誰に依頼したかを確かめる

       docker compose exec app python -c "import sys; sys.path.insert(0, 'src/mid02'); \\
       from _paths import setup; setup(); from audit import AuditLog; \\
       print(AuditLog('TASK-M02-approved').render())"

3. 必要な承認者の人数を見る（社外宛・個人情報を含む場合は 2 名）

## 手順

1. 期限内で、内容が業務として正しい → 承認する。走行を `resume=True` で再開する
2. 期限内で、内容が正しくない → **却下する（理由を必ず書く）**。
   却下すると、出した副作用は逆順に打ち消され、引き継ぎ書が残る
3. 期限内で、金額や本文だけを直したい → 条件付き承認にする。
   金額を変えるときは冪等キーも一緒に変える（別の申請になるため）
4. 期限を過ぎている → 走行は `expired` で人に渡っている。
   **済んだ操作は残っている**ので、`{RUNBOOK_DOUBLE_PATH}` の照合手順で現状を確かめてから、
   改めて依頼を出し直す

## やってはいけないこと

- 承認をスキップして、人が手で同じ操作を実行する
  （監査ログに `executed` が残らず、あとから誰も追えなくなる）
- 内容を読まずに押す。読まずに押す承認は、防御としては「承認なし」と同じ結果になる
- 期限切れの保留を、確認せずに再依頼する（二重実行の主な原因）

## 再発防止

- 承認対象が多すぎないかを見直す。全部を承認対象にすると、承認者は読まずに押すようになる
- 期限（`TTL_HOURS`）と承認者の当番表を、業務の締め切りから逆算して決める
- `awaiting_approval` の滞留時間を監視する（S14 の可観測性で扱う）
"""

DOUBLE = f"""# runbook: 二重実行が起きたとき

## 症状

- 同じ内容の申請が 2 件見える
- 引き継ぎ書の「実行されたか分からない操作」が空でない
- 採点で「二重実行が0件」が落ちている

## 確認

1. **軌跡ではなくデータを見る**（軌跡には「失敗」と書かれていても、相手には届いている）

       docker compose exec app python src/mid02/ledger.py

2. 同じ冪等キーの行を特定する（`二重実行` が 1 以上なら該当あり）
3. 送信については、`messages.jsonl` の宛先と本文で重複を目視する
   （送信には冪等キーが無いため、機械では照合できない）

## 手順

1. 重複している申請のうち、**後から作られた行**を冪等キーで取り消す

       docker compose exec app python -c "import sys; sys.path.insert(0, 'src/mid02'); \\
       from _paths import setup; setup(); from compensate import cancel_expense_by_key; \\
       print(cancel_expense_by_key('2026-08-15-EMP-003-68000'))"

2. 行は消さずに `status: cancelled` にする（誰がいつ取り消したかを残すため）
3. 予約が重複している場合は枠を解放する（枠は解放しないと意味がない）
4. 送信が重複している場合は、訂正の連絡を人が出す。**取り消せない**

## やってはいけないこと

- 重複した行を JSONL から削除する（監査の連続性が切れる）
- 「失敗したからもう一度」で同じ操作を再実行する。
  部分的失敗（実行されたか分からない）に対する再実行が、二重実行そのものである

## 再発防止

- 冪等でない書き込みに対して、判断なしの再試行（blind）を使っていないかを実行前に検査する

       docker compose exec app python src/mid02/ops_spec.py

- 冪等キーは「同じ意図なら同じ値」になる形（`日付-社員ID-金額`）で作る
- 照合できない操作（送信・書き出し）は、部分的失敗のときに再試行せず人に渡す
"""

RUNBOOKS = ((RUNBOOK_STALLED_PATH, STALLED), (RUNBOOK_DOUBLE_PATH, DOUBLE))


def write_all() -> list[str]:
    """runbook を作業領域に置く。走行の産物ではないので、走行のたびには消さない。"""
    written = []
    for path, text in RUNBOOKS:
        target = WORKSPACE / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        written.append(path)
    return written


def main() -> None:
    for path in write_all():
        print(f"生成しました: workspace/{path}")
    print()
    print(STALLED)
    print(DOUBLE)


if __name__ == "__main__":
    main()
