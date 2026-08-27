#!/usr/bin/env python3
"""セッション4の自己検証：ツールの設計改善が実際に効いていること。

本文（body / practice / solutions）に載せた数値もここで検証している。
数値が変わる変更をしたときは、NG 行に出る実測値に合わせて本文の表を直すこと。
検証の前後で `tools/make_data.py` を走らせるので、データは初期状態に戻る。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agentkit.models import ToolCall  # noqa: E402
from agentkit.tools import ToolError  # noqa: E402
from badtools import build_bad_registry, policy_lookup  # noqa: E402
from goodtools import (FIND_EXPENSES_SCHEMA, build_good_registry,  # noqa: E402
                      find_expenses, get_policy_v2, is_actionable, submit_expense_once)
from measure import (BAD_SCENARIO, GOOD_SCENARIO, approx, reset_data,  # noqa: E402
                     row_count, run_trajectory, section1, section2, section3,
                     section4, section5, section6)
from toolschema import validate_args  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def call_good(args: dict):
    return build_good_registry().call(ToolCall("c1", "submit_expense", args))


VALID = {"employee": "高橋 涼", "amount": 68000, "category": "接待交際費",
         "idempotency_key": "2026-08-15-EMP-003-68000"}

reset_data()

# --- スキーマ検証：モデルの誤りを構造的に止める -----------------------------
res = call_good({**VALID, "category": "打ち上げ"})
check("列挙外の区分を拒否し、許容値を全部挙げる",
      not res.ok and all(c in (res.error or "") for c in
                         ("交通費", "出張旅費", "接待交際費", "備品")),
      res.error or "")

res = call_good({k: v for k, v in VALID.items() if k != "amount"})
check("必須の引数の欠落を拒否し、必要な引数を挙げる",
      not res.ok and "必須の引数 'amount'" in (res.error or "")
      and "employee" in (res.error or ""), res.error or "")

res = call_good({**VALID, "amount": -3000})
check("範囲外の金額を拒否し、範囲を挙げる",
      not res.ok and "1 以上 1000000 以下" in (res.error or ""), res.error or "")

res = call_good({**VALID, "amonut": 1})
check("使えない引数名を拒否し、使える引数を挙げる",
      not res.ok and "'amonut' は使えません" in (res.error or "")
      and "employee" in (res.error or ""), res.error or "")

res = call_good({**VALID, "amount": "68000"})
check("型違いを拒否する",
      not res.ok and "整数で指定してください" in (res.error or ""), res.error or "")

filled = validate_args(FIND_EXPENSES_SCHEMA, {})
check("省略した引数に既定値が入る",
      filled == {"status": "all", "min_amount": 0, "limit": 5}, str(filled))

reset_data()
before = row_count()
res = call_good(dict(VALID))
check("正しい引数は通り、1 行増える",
      res.ok and row_count() - before == 1, res.content)

# --- スキーマは宣言。検証しなければ守られない -------------------------------
s2 = section2()
check("検証なしのレジストリでは不正が副作用に到達する",
      s2["検証なし"]["reached"] == 2 and s2["検証なし"]["added"] == 2,
      f"到達 {s2['検証なし']['reached']} 件 / 増えた行 {s2['検証なし']['added']}")
check("検証ありのレジストリでは副作用に到達しない",
      s2["検証あり"]["reached"] == 0 and s2["検証あり"]["added"] == 0,
      f"到達 {s2['検証あり']['reached']} 件 / 増えた行 {s2['検証あり']['added']}")

# --- 結果の量：本文の表と一致すること ---------------------------------------
texts = [text for _, text in section1()]
lengths = [len(t) for t in texts]
tokens = [approx(t) for t in texts]
check("結果の文字数が本文の表と一致する", lengths == [1038, 366, 151, 102], str(lengths))
check("近似トークン数が本文の表と一致する", tokens == [346, 122, 50, 34], str(tokens))

many = find_expenses("all", 0, 2)
check("件数が limit を超えたら残り件数を知らせる",
      "該当 6 件（表示 2 件）" in many and "残り 4 件" in many,
      many.splitlines()[0])

empty = find_expenses("rejected", 100_000)
check("該当 0 件でも次の行動を促す",
      "該当 0 件" in empty and "条件を緩めて" in empty, empty)

# --- エラーメッセージ：次の行動が決まる形か ---------------------------------
try:
    policy_lookup("出張")
    bad_msg = ""
except ToolError as exc:
    bad_msg = str(exc)
check("悪いエラーは次の行動の手がかりを持たない",
      bad_msg == "not found", bad_msg)

try:
    get_policy_v2("出張")
    good_msg = ""
except ToolError as exc:
    good_msg = str(exc)
check("良いエラーは指定できる項目を全部挙げる",
      all(t in good_msg for t in ("経費精算", "接待交際費", "会議室予約",
                                  "情報の持ち出し", "社外連絡"))
      and "選び直してください" in good_msg, f"{len(good_msg)} 文字")

enum_msg = call_good({**VALID, "category": "打ち上げ"}).error or ""
check("エラーメッセージの良し悪しを機械判定できる",
      is_actionable(good_msg) and is_actionable(enum_msg) and not is_actionable(bad_msg),
      f"良={is_actionable(good_msg)} / 悪={is_actionable(bad_msg)}")

raw = build_bad_registry().call(ToolCall("c2", "expense_report_raw", {"query": "8月"}))
check("Traceback を返すツールは失敗を成功として返している",
      raw.ok and "Traceback (most recent call last)" in raw.content
      and "ValueError" in raw.content,
      f"ok={raw.ok} / {raw.content.splitlines()[0]}")

# --- 読み取りと書き込みの分離 -----------------------------------------------
s4 = section4()
check("読み取り専用レジストリに書き込み系が無い",
      s4["names"] == ["find_expenses", "get_policy", "search_docs"], str(s4["names"]))
check("書き込みの呼び出しが拒否され、使えるツール名が返る",
      not s4["ok"] and "存在しません" in s4["message"]
      and "find_expenses" in s4["message"], s4["message"])
check("拒否されたあとデータが増えていない", s4["added"] == 0, f"増えた行 {s4['added']}")

# --- 冪等性 -----------------------------------------------------------------
s3 = section3()
default_key = "submit_expense（agentkit の既定）"
once_key = "submit_expense_once（冪等キーで吸収）"
check("既定の submit_expense は 2 回呼ぶと 2 行増える",
      s3[default_key]["added"] == 2 and s3[default_key]["ids"] == ["EXP-0007", "EXP-0008"],
      str(s3[default_key]))
check("冪等化した submit_expense_once は 2 回呼んでも 1 行",
      s3[once_key]["added"] == 1 and s3[once_key]["ids"] == ["EXP-0007", "EXP-0007"],
      str(s3[once_key]))

reset_data()
try:
    submit_expense_once("高橋 涼", 68000, "接待交際費", idempotency_key="")
    empty_key_msg = ""
except ToolError as exc:
    empty_key_msg = str(exc)
check("冪等キーが空ならエラーで、次の行動を促す",
      "一意な文字列" in empty_key_msg and row_count() == 6, empty_key_msg[:40] + "…")

# --- 軌跡：道具の差が手数と停止理由に出る -----------------------------------
s5 = section5()
bad_key = "悪い道具（自由文字列1引数・エラーは「処理できませんでした。」）"
good_key = "良い道具（スキーマ検証・許容値を返すエラー）"
check("悪い道具の軌跡は打ち切られる（max_steps）",
      s5[bad_key] == {"steps": 4, "calls": 4, "ok_calls": 0, "stop_reason": "max_steps"},
      str(s5[bad_key]))
check("良い道具の軌跡は 3 手で完了する（done）",
      s5[good_key] == {"steps": 3, "calls": 2, "ok_calls": 1, "stop_reason": "done"},
      str(s5[good_key]))

t_a = run_trajectory(GOOD_SCENARIO, build_good_registry())
t_b = run_trajectory(GOOD_SCENARIO, build_good_registry())
check("同じシナリオを2回走らせて軌跡が一致する",
      t_a.tool_names == t_b.tool_names and t_a.final == t_b.final
      and [r.ok for s in t_a.steps for r in s.results]
      == [r.ok for s in t_b.steps for r in s.results],
      f"{t_a.tool_names} / {t_a.stop_reason}")

t_bad = run_trajectory(BAD_SCENARIO, build_bad_registry())
errors = {r.error for s in t_bad.steps for r in s.results}
check("悪い道具は同じ役に立たないエラーを繰り返し返す",
      errors == {"処理できませんでした。"}, str(errors))

# --- ツール仕様書 -----------------------------------------------------------
spec = section6()
check("ツール仕様書に全ツールと副作用・冪等・承認が載る",
      all(n in spec for n in ("find_expenses", "get_policy", "search_docs",
                              "submit_expense"))
      and "| submit_expense | あり | はい | 必要 |" in spec,
      spec.splitlines()[-1])

reset_data()

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション4の検証はすべて成功しました。")
