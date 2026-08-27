#!/usr/bin/env python3
"""復習02（S02〜S08・S06〜S08 中心）の自己検証。

    docker compose exec app python src/review02/verify.py

10問すべてを機械判定する。1つでも満たさなければ非0で終了するので、
出力を読んで「合っている気がする」と判断する余地はない。
練習問題・解答章に載せた数値もここで固定している（数値が変わったら本文を直す）。

冒頭と末尾で `tools/make_data.py` を実行するので、検証の前後でデータは初期状態に戻る。
"""

from __future__ import annotations

import sys

from _paths import setup

ROOT = setup()

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.memory import approx_tokens  # noqa: E402
from durability import reset_data  # noqa: E402 (S06)

import answers  # noqa: E402
import defects  # noqa: E402
import memo  # noqa: E402
import resume as resume_mod  # noqa: E402
import split  # noqa: E402
import workload  # noqa: E402
from assign import (BAD_ASSIGNMENT, BROKEN_PLAN, GOOD_ASSIGNMENT,  # noqa: E402
                    MISSING_ASSIGNMENT, TEAM_PLAN, check_assignment,
                    handoff_count, render_team_mermaid, tools_of)
from planner import plan_cost, topo_layers, validate_plan  # noqa: E402 (S05)

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


reset_data()

# ---------------------------------------------------------------------------
# 材料：疑似履歴の形（近似トークン数（比較用）＝文字数÷3）
# ---------------------------------------------------------------------------
print("=== 材料（疑似履歴の形） ===")
ITEM_TOKENS = [approx_tokens(memo.render(item)) for item in memo.HISTORY]
check("6項目の近似トークンが設計どおり", ITEM_TOKENS == [100, 50, 346, 400, 300, 20],
      str(ITEM_TOKENS))
check("項目の文字数がちょうど指定どおりになる",
      [len(memo.render(i)) for i in memo.HISTORY] == [300, 150, 1038, 1200, 900, 60])
check("埋め草には「。」が入らない（制約の抽出が埋め草に反応しない）",
      memo.constraint_items() == ["task"], str(memo.constraint_items()))

# ---------------------------------------------------------------------------
# 問題1：構造を4つ選ぶ
# ---------------------------------------------------------------------------
print("\n=== 問題1：構造を4つ選ぶ ===")
truth = workload.truth()
check("6件そろっている", sorted(answers.Q1) == sorted(truth),
      f"{len(answers.Q1)} 件")
for name, expected in truth.items():
    check(f"問題1 の解答（{name}）", answers.Q1.get(name) == expected,
          str(answers.Q1.get(name)))
check("状態の持ち方が3方式すべて出る",
      {row["状態の持ち方"] for row in truth.values()}
      == {"履歴のみ", "構造体＋履歴", "状態機械"})
check("体制も3種類すべて出る",
      {row["体制"] for row in truth.values()}
      == {"単体", "オーケストレータ", "ハンドオフ"})
check("四半期の棚卸しは 状態機械／単体（S06 で実際にそう作った）",
      truth["四半期の棚卸し（洗い出し→レポート→報告会の予約）"]["状態の持ち方"] == "状態機械"
      and truth["四半期の棚卸し（洗い出し→レポート→報告会の予約）"]["体制"] == "単体")

# ---------------------------------------------------------------------------
# 問題2：判断を規則にする
# ---------------------------------------------------------------------------
print("\n=== 問題2：判断を規則にする ===")
check("取り返しのつかない操作があるものは必ず状態機械",
      all(workload.choose_state(r) == "状態機械"
          for r in workload.REQUESTS if r.irreversible))
check("再開しないならチェックポイントは不要",
      all(workload.choose_checkpoint(r) == "不要"
          for r in workload.REQUESTS if not r.must_resume))
check("ツール結果が小さいなら圧縮は不要",
      all(workload.choose_compression(r) == "不要"
          for r in workload.REQUESTS if not r.big_results))
base = workload.by_name("今月の経費レポートを作る")
FLIPS = {
    "irreversible": ["状態の持ち方"],
    "must_resume": ["状態の持ち方", "圧縮", "チェックポイントの粒度"],
    "parallel_parts": ["体制"],
}
for attr, moved in FLIPS.items():
    effect = workload.flip_effect(base, attr)
    check(f"{attr} を True にすると動く決定が {len(moved)} 個",
          effect["動いた決定"] == moved, str(effect["動いた決定"]))
check("must_resume を立てると圧縮が「状態へ移す＋切り捨て」に変わる",
      workload.flip_effect(base, "must_resume")["変更後"]["圧縮"]
      == "状態へ移す＋切り捨て")

# ---------------------------------------------------------------------------
# 問題3：会話履歴の中身を数える
# ---------------------------------------------------------------------------
print("\n=== 問題3：入力の何がコンテキストを埋めているか ===")
dominance = memo.dominance()
check("ツール結果が入力の 90% を占める",
      dominance == {"合計": 1216, "ツール結果": 1096, "割合(%)": 90,
                    "項目数": 6, "ツール結果の項目数": 4}, str(dominance))
check("6項目のうちツール結果は4項目（数は少ないのに量は支配的）",
      dominance["ツール結果の項目数"] == 4 and dominance["項目数"] == 6)
check("1件の申請一覧（1038 文字）だけで 346 近似トークン",
      approx_tokens(memo.render(memo.HISTORY[2])) == 346)
check("そのままでは予算 600 に収まらない",
      dominance["合計"] > memo.BUDGET, f"{dominance['合計']} / {memo.BUDGET}")

# ---------------------------------------------------------------------------
# 問題4：圧縮4方式の比較
# ---------------------------------------------------------------------------
print("\n=== 問題4：圧縮方式の比較 ===")
EXPECTED_MEMO = [
    {"方式": "そのまま", "近似トークン": 1216, "制約": "3/3", "事実": "2/2",
     "予算内": False, "再開できる": True},
    {"方式": "切り捨て", "近似トークン": 320, "制約": "0/3", "事実": "0/2",
     "予算内": True, "再開できる": False},
    {"方式": "要約", "近似トークン": 280, "制約": "3/3", "事実": "0/2",
     "予算内": True, "再開できる": False},
    {"方式": "選択的保持", "近似トークン": 420, "制約": "3/3", "事実": "0/2",
     "予算内": True, "再開できる": False},
    {"方式": "状態へ移す＋切り捨て", "近似トークン": 320, "制約": "3/3", "事実": "2/2",
     "予算内": True, "再開できる": True},
]
memo_rows = memo.compare()
check("方式は5つ", len(memo_rows) == 5, str(len(memo_rows)))
for expected, got in zip(EXPECTED_MEMO, memo_rows):
    check(f"{expected['方式']} の行が期待どおり", got == expected, str(got))
check("切り捨てでは最初の指示（制約）が最初に消える",
      memo_rows[1]["制約"] == "0/3" and memo_rows[1]["事実"] == "0/2")
check("要約は最も小さいのに、制約は残って事実だけが落ちる",
      memo_rows[2]["近似トークン"] == min(r["近似トークン"] for r in memo_rows)
      and memo_rows[2]["制約"] == "3/3" and memo_rows[2]["事実"] == "0/2")
check("選択的保持は切り捨てより大きい（制約を残すぶん）",
      memo_rows[3]["近似トークン"] > memo_rows[1]["近似トークン"],
      f"{memo_rows[3]['近似トークン']} > {memo_rows[1]['近似トークン']}")

# ---------------------------------------------------------------------------
# 問題5：捨てる前に状態へ移す
# ---------------------------------------------------------------------------
print("\n=== 問題5：捨てる前に状態へ移す ===")
state_memory, state = memo.state_first()
truncated, _ = memo.truncate()
check("履歴の大きさは「切り捨て」と同じ",
      state_memory.total_tokens() == truncated.total_tokens() == 320,
      f"{state_memory.total_tokens()} / {truncated.total_tokens()}")
check("状態に持つのは制約・事実・判定基準の3つだけ",
      sorted(state) == ["事実", "判定基準", "制約"], str(sorted(state)))
check("制約と事実は状態に残る（履歴からは消えている）",
      memo.kept(state_memory, state, memo.CONSTRAINTS) == 3
      and memo.kept(state_memory, state, memo.FACTS) == 2
      and memo.kept(state_memory, {}, memo.FACTS) == 0)
check("状態に本文（1038 文字の一覧）は入れない",
      all(len(str(v)) < 120 for v in state.values()),
      str({k: len(str(v)) for k, v in state.items()}))

# ---------------------------------------------------------------------------
# 問題6：圧縮した保存物から再開する
# ---------------------------------------------------------------------------
print("\n=== 問題6：保存の仕方を変えて再開する ===")
point = resume_mod.crash_point()
check("5手ぶん保存され、状態は booking、違反は2件",
      point == {"保存された手数": 5, "状態": "booking", "違反": 2, "予約の行数": 0},
      str(point))
EXPECTED_RESUME = [
    {"方式": "軌跡だけ残す", "保存した手数": 5, "状態の鍵": 0,
     "基準を変えて再計算できる": False, "再開できる": False, "到達した手数": None,
     "違反": None, "予約の行数": 0, "停止理由": "TypeError"},
    {"方式": "軌跡を圧縮＋状態は全部", "保存した手数": 2, "状態の鍵": 12,
     "基準を変えて再計算できる": True, "再開できる": True, "到達した手数": 6,
     "違反": 2, "予約の行数": 1, "停止理由": "done"},
    {"方式": "全部残す", "保存した手数": 5, "状態の鍵": 12,
     "基準を変えて再計算できる": True, "再開できる": True, "到達した手数": 9,
     "違反": 2, "予約の行数": 1, "停止理由": "done"},
    {"方式": "状態から本文を捨てる", "保存した手数": 5, "状態の鍵": 11,
     "基準を変えて再計算できる": False, "再開できる": True, "到達した手数": 9,
     "違反": 2, "予約の行数": 1, "停止理由": "done"},
]
resume_rows = resume_mod.variants()
check("4通りそろっている", len(resume_rows) == 4, str(len(resume_rows)))
for expected, got in zip(EXPECTED_RESUME, resume_rows):
    check(f"{expected['方式']} の行が期待どおり", got == expected, str(got))
check("状態を捨てると再開できない（軌跡だけでは続きが決められない）",
      resume_rows[0]["再開できる"] is False and resume_rows[0]["停止理由"] == "TypeError")
check("軌跡を圧縮しても再開はできる。ただし軌跡は9手ぶん残らない",
      resume_rows[1]["到達した手数"] == 6 and resume_rows[2]["到達した手数"] == 9)
check("どの再開でも予約は1回だけ（二重予約は起きない）",
      [r["予約の行数"] for r in resume_rows] == [0, 1, 1, 1],
      str([r["予約の行数"] for r in resume_rows]))
check("本文を捨てると、判定基準を変えたやり直しができなくなる",
      resume_rows[3]["再開できる"] is True
      and resume_rows[3]["基準を変えて再計算できる"] is False)

# ---------------------------------------------------------------------------
# 問題7：3つの構成を同じタスクで比べる
# ---------------------------------------------------------------------------
print("\n=== 問題7：単体 / オーケストレータ / ハンドオフ ===")
EXPECTED_SPLIT = [
    {"構成": "単体", "体の数": 1, "手数": 5, "ツール呼び出し": 5, "1体のツール最大": 5,
     "履歴の本数": 1, "最長の履歴": 5, "レポート": True, "予約の行数": 1},
    {"構成": "オーケストレータ", "体の数": 2, "手数": 6, "ツール呼び出し": 5,
     "1体のツール最大": 3, "履歴の本数": 2, "最長の履歴": 3, "レポート": True,
     "予約の行数": 1},
    {"構成": "ハンドオフ", "体の数": 2, "手数": 7, "ツール呼び出し": 6,
     "1体のツール最大": 3, "履歴の本数": 2, "最長の履歴": 4, "レポート": True,
     "予約の行数": 0},
]
split_rows = split.compare()
check("3構成そろっている", len(split_rows) == 3, str(len(split_rows)))
for expected, got in zip(EXPECTED_SPLIT, split_rows):
    check(f"{expected['構成']} の行が期待どおり", got == expected, str(got))
check("分けると手数が増える（5 → 6）",
      split_rows[1]["手数"] > split_rows[0]["手数"],
      f"{split_rows[0]['手数']} → {split_rows[1]['手数']}")
check("分けると1体が持つツールは減る（5 → 3）",
      split_rows[1]["1体のツール最大"] < split_rows[0]["1体のツール最大"])
check("分けると1本の履歴は短くなる（5手 → 3手）",
      split_rows[1]["最長の履歴"] < split_rows[0]["最長の履歴"])
check("渡し方を間違えると成果が出ない（予約 1 → 0）",
      split_rows[1]["予約の行数"] == 1 and split_rows[2]["予約の行数"] == 0)
check("成果が出ないほうが手数は多い（6 → 7）",
      split_rows[2]["手数"] > split_rows[1]["手数"])
check("レポートはどの構成でも作れている（落ちたのは予約だけ）",
      all(row["レポート"] for row in split_rows))

# ---------------------------------------------------------------------------
# 問題8：引き継ぎで落ちる文脈
# ---------------------------------------------------------------------------
print("\n=== 問題8：引き継ぎで落ちる文脈 ===")
loss = split.handoff_loss()
check("必要な項目は3つ", loss["必要な項目"] == list(split.NEEDED), str(loss["必要な項目"]))
check("自由文で渡すと1項目しか残らない", loss["自由文"] == ["EXP-0004"], str(loss["自由文"]))
check("構造化して渡すと3項目すべて残る",
      loss["構造化"] == list(split.NEEDED), str(loss["構造化"]))
check("落ちた項目に「埋まっている枠」が含まれる（予約の失敗と対応する）",
      "10:00 は予約済み" not in loss["自由文"]
      and "10:00 は予約済み" in loss["構造化"])

# ---------------------------------------------------------------------------
# 問題9：分割を計画として書き、配る前に検査する
# ---------------------------------------------------------------------------
print("\n=== 問題9：分割の設計を実行前に検査する ===")
registry = build_registry()
names = registry.names()
check("計画そのものに違反がない", validate_plan(TEAM_PLAN, names) == [],
      str(validate_plan(TEAM_PLAN, names)))
cost = plan_cost(TEAM_PLAN)
check("サブゴール4個・最低8回の LLM 呼び出し",
      cost["subgoals"] == 4 and cost["min_llm_calls"] == 8, str(cost))
check("計画の近似トークンも測れる", cost["approx_plan_tokens"] > 0,
      str(cost["approx_plan_tokens"]))
check("依存は4層に分かれる（並列にできる仕事は無い）",
      [[sg.id for sg in layer] for layer in topo_layers(TEAM_PLAN)]
      == [["sg_collect"], ["sg_check"], ["sg_report"], ["sg_book"]])
BROKEN_EXPECTED = [
    "sg_book: 必要な情報 report を作るサブゴールが依存に入っていません"
    "（needs と consumes の対応を見直してください）",
    "成果キー 'report' を作るサブゴールがありません",
]
check("壊れた計画は実行前に2件の違反で止まる",
      validate_plan(BROKEN_PLAN, names) == BROKEN_EXPECTED,
      str(validate_plan(BROKEN_PLAN, names)))

check("良い割り当ては違反0件", check_assignment(TEAM_PLAN, GOOD_ASSIGNMENT, registry) == [],
      str(check_assignment(TEAM_PLAN, GOOD_ASSIGNMENT, registry)))
BAD_EXPECTED = [
    "researcher: 読み取り専用と副作用のあるツールが混ざっています"
    "（read: get_policy, list_expenses, search_docs / write: book_room）",
    "引き継ぎが 2 回あります（上限 1 回）。渡すたびに文脈が落ちます",
]
check("予約を調査担当に戻すと2件の違反が立つ",
      check_assignment(TEAM_PLAN, BAD_ASSIGNMENT, registry) == BAD_EXPECTED,
      str(check_assignment(TEAM_PLAN, BAD_ASSIGNMENT, registry)))
check("担当の空きも違反になる",
      check_assignment(TEAM_PLAN, MISSING_ASSIGNMENT, registry)
      == ["割り当てられていないサブゴール: sg_book"],
      str(check_assignment(TEAM_PLAN, MISSING_ASSIGNMENT, registry)))
check("引き継ぎ回数が数えられる（良い1回 / 悪い2回）",
      handoff_count(TEAM_PLAN, GOOD_ASSIGNMENT) == 1
      and handoff_count(TEAM_PLAN, BAD_ASSIGNMENT) == 2)
check("担当ごとの許可リストが設計どおり",
      tools_of(TEAM_PLAN, GOOD_ASSIGNMENT, "researcher")
      == ["get_policy", "list_expenses", "search_docs"]
      and tools_of(TEAM_PLAN, GOOD_ASSIGNMENT, "arranger")
      == ["book_room", "write_file"])
EXPECTED_MERMAID = """flowchart LR
  subgraph researcher
    sg_collect["sg_collect"]
    sg_check["sg_check"]
  end
  subgraph arranger
    sg_report["sg_report"]
    sg_book["sg_book"]
  end
  sg_collect --> sg_check
  sg_check -->|引き継ぎ| sg_report
  sg_report --> sg_book"""
check("分割の図が期待どおり",
      render_team_mermaid(TEAM_PLAN, GOOD_ASSIGNMENT) == EXPECTED_MERMAID,
      "\n" + render_team_mermaid(TEAM_PLAN, GOOD_ASSIGNMENT))

# ---------------------------------------------------------------------------
# 問題10（実践・任意）：障害報告を構造の欠陥に切り分ける
# ---------------------------------------------------------------------------
print("\n=== 問題10：構造の欠陥に切り分ける（実践・任意） ===")
EXPECTED_Q10 = {
    "INC-11": {"defect": "副作用の前に意図を保存していない", "first": "S06"},
    "INC-12": {"defect": "遷移を絞っていない", "first": "S06"},
    "INC-13": {"defect": "捨てる前に状態へ移していない", "first": "S07"},
    "INC-14": {"defect": "自由文で引き継いだ", "first": "S08"},
    "INC-15": {"defect": "状態を持っていない", "first": "S06"},
}
for incident, expected in EXPECTED_Q10.items():
    check(f"問題10 の解答（{incident}）", answers.Q10.get(incident) == expected,
          str(answers.Q10.get(incident)))
check("欠陥の名前は5つに固定されている", len(defects.DEFECTS) == 5)
check("解答に使った名前はすべて5分類の中にある",
      all(row["defect"] in defects.DEFECTS for row in answers.Q10.values()))
check("5分類それぞれに手当ての章と確かめ方がある",
      all(len(defects.CATALOG[name]) == 4 for name in defects.DEFECTS))
check("報告は5件そろっている", sorted(defects.INCIDENTS) == sorted(EXPECTED_Q10))

design = ROOT / "workspace" / "review02_design.md"
if design.exists():
    text = design.read_text(encoding="utf-8")
    missing = [heading for heading in ("## 状態の持ち方", "## 圧縮", "## 体制",
                                       "## 再開", "## 確かめ方")
               if heading not in text]
    check("設計メモに5つの節がそろっている", not missing, str(missing))
else:
    print("SKIP workspace/review02_design.md が無いため設計メモの検査を飛ばします")

# ---------------------------------------------------------------------------
reset_data()

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\n復習02の検証はすべて成功しました。")
