#!/usr/bin/env python3
"""復習03（S02〜S12・S09〜S12 中心）の自己検証。

    docker compose exec app python src/review03/verify.py

10問すべてを機械判定する。1つでも満たさなければ非0で終了するので、出力を読んで
「合っている気がする」と判断する余地はない。練習問題・解答章に載せた数値も
ここで固定している（数値が変わったら本文を直す）。

冒頭と末尾で `tools/make_data.py` を実行するので、検証の前後でデータは初期状態
（経費6件・予約0件・送信0件）に戻る。
"""

from __future__ import annotations

import sys
from dataclasses import replace

from _paths import reset_data, setup

ROOT = setup()

import answers  # noqa: E402
import exits  # noqa: E402
import failure_map  # noqa: E402
import findings  # noqa: E402
import gates  # noqa: E402
import spec  # noqa: E402
import stack  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


reset_data()

# ---------------------------------------------------------------------------
# 材料：レビュー対象の仕様
# ---------------------------------------------------------------------------
print("=== 材料（レビュー対象の仕様）===")
check("レビュー対象は9本のツールを渡している", len(spec.AS_IS.tools) == 9,
      str(len(spec.AS_IS.tools)))
check("このタスクに必要なのは4本", spec.TASK_NEEDS
      == ("get_policy", "list_expenses", "write_file", "send_message"),
      str(spec.TASK_NEEDS))
check("信頼できない出所は S12 の表から取っている（2件）",
      spec.UNTRUSTED_SOURCES == ("search_docs", "read_file"),
      str(spec.UNTRUSTED_SOURCES))
check("規程の金額基準は 50,000 円", spec.POLICY_THRESHOLD == 50_000)
check("レビュー前の仕様は基準を 100,000 円にしている",
      spec.AS_IS.approval["threshold_yen"] == 100_000)

# ---------------------------------------------------------------------------
# 問題1：13項目のレビュー
# ---------------------------------------------------------------------------
print("\n=== 問題1：13項目のレビュー ===")
detected = findings.audit_spec(spec.AS_IS)
truth = {}
for item in findings.REVIEW_ITEMS:
    hole = item in detected
    truth[item] = {"穴か": hole,
                   "塞ぐ層": findings.pick_layer(findings.CANDIDATES[item]) if hole else "—"}
check("13項目そろっている", sorted(answers.Q1) == sorted(truth), f"{len(answers.Q1)} 件")
for item, expected in truth.items():
    check(f"問題1 の解答（{item}）", answers.Q1.get(item) == expected,
          str(answers.Q1.get(item)))
check("穴でない項目が3件ある（すべて指摘すればよいわけではない）",
      sum(1 for row in truth.values() if not row["穴か"]) == 3)

# ---------------------------------------------------------------------------
# 問題2：仕様監査を規則にする
# ---------------------------------------------------------------------------
print("\n=== 問題2：仕様監査を規則にする ===")
check("レビュー前の仕様から10件の穴が出る", detected == list(findings.CATALOG),
      str(detected))
check("レビュー後の仕様では0件になる", findings.audit_spec(spec.TO_BE) == [],
      str(findings.audit_spec(spec.TO_BE)))
check("要らないのに渡しているツールは5本",
      findings.extra_tools(spec.AS_IS)
      == ["search_docs", "get_employee", "read_file", "submit_expense", "run_python"],
      str(findings.extra_tools(spec.AS_IS)))
one_fix = replace(spec.AS_IS, runner={**spec.AS_IS.runner, "read_only": True})
check("read_only を足すと F1 だけが消える",
      findings.audit_spec(one_fix) == [f for f in detected if f != "F1"],
      str(findings.audit_spec(one_fix)))
threshold_fix = replace(spec.AS_IS,
                        approval={**spec.AS_IS.approval, "threshold_yen": 50_000})
check("基準額を規程に合わせると F6 だけが消える",
      findings.audit_spec(threshold_fix) == [f for f in detected if f != "F6"],
      str(findings.audit_spec(threshold_fix)))
tools_fix = replace(spec.AS_IS, tools=spec.TASK_NEEDS)
check("許可リストを絞ると F3 と F4 が同時に消える（穴は独立ではない）",
      findings.audit_spec(tools_fix) == [f for f in detected if f not in ("F3", "F4")],
      str(findings.audit_spec(tools_fix)))

# ---------------------------------------------------------------------------
# 問題3：出口の棚卸しと出力検査の被覆
# ---------------------------------------------------------------------------
print("\n=== 問題3：出力検査の被覆 ===")
EXPECTED_EXITS = [
    {"検査": "前方一致", "止めた": 1, "正当な操作を止めた": 0, "素通しした持ち出し": 3,
     "検査していない出口": ["②", "③"]},
    {"検査": "完全一致", "止めた": 2, "正当な操作を止めた": 0, "素通しした持ち出し": 2,
     "検査していない出口": ["②", "③"]},
    {"検査": "宛先＋内容", "止めた": 3, "正当な操作を止めた": 0, "素通しした持ち出し": 1,
     "検査していない出口": ["③"]},
]
exit_rows = exits.rows()
check("出口は3つ数え上げてある", len(exits.EXITS) == 3)
check("検査は3実装そろっている", exits.LABELS == ("前方一致", "完全一致", "宛先＋内容"),
      str(exits.LABELS))
for expected, got in zip(EXPECTED_EXITS, exit_rows):
    subset = {k: got[k] for k in expected}
    check(f"{expected['検査']} の被覆が期待どおり", subset == expected, str(subset))
check("どの検査も正当な操作を止めていない（誤遮断 0 件）",
      all(row["正当な操作を止めた"] == 0 for row in exit_rows))
check("前方一致は似せた宛先を素通しする",
      "3 似せた宛先へ送る" in exit_rows[0]["素通しの内訳"],
      str(exit_rows[0]["素通しの内訳"]))
check("完全一致は似せた宛先を止めるが、住所の書き出しは止めない",
      "3 似せた宛先へ送る" not in exit_rows[1]["素通しの内訳"]
      and "5 住所を書き出す" in exit_rows[1]["素通しの内訳"],
      str(exit_rows[1]["素通しの内訳"]))
check("宛先＋内容でも隔離実行の出口は残る（残余リスク R2）",
      exit_rows[2]["素通しの内訳"] == ["6 隔離実行から書き出す"],
      str(exit_rows[2]["素通しの内訳"]))

# ---------------------------------------------------------------------------
# 問題4：塞ぐ層の優先順位
# ---------------------------------------------------------------------------
print("\n=== 問題4：塞ぐ層の優先順位 ===")
EXPECTED_PLAN = {
    "F1": "隔離の境界", "F2": "隔離の境界", "F3": "権限制限", "F4": "権限制限",
    "F5": "人間承認", "F6": "人間承認", "F7": "再試行の判断", "F8": "記録との照合",
    "F9": "出力検査", "F10": "記録との照合",
}
check("10件の割り当てが期待どおり", findings.plan() == EXPECTED_PLAN,
      str(findings.plan()))
check("優先順位は9層ぶんそろっている", len(findings.PRIORITY) == 9)
check("いちばん先に選ぶのは権限制限", findings.PRIORITY[0] == "権限制限")
check("いちばん後ろはプロンプト（測れないので選ばない）",
      findings.PRIORITY[-1] == "プロンプト")
check("どの穴の塞ぎ方にもプロンプトを選んでいない",
      "プロンプト" not in findings.plan().values())
check("候補が複数ある穴は9件（1件だけ候補が1つ）",
      sum(1 for c in findings.CANDIDATES.values() if len(c) > 1) == 9,
      str({k: len(v) for k, v in findings.CANDIDATES.items()}))
check("測れない層は1つだけ（プロンプト）",
      [layer for layer, traits in findings.LAYER_TRAITS.items()
       if traits[0] == "測れない"] == ["プロンプト"])
check("止まらない層も選択肢には入っている（入力検査）",
      findings.LAYER_TRAITS["入力検査"][1] == "止まらない")

# ---------------------------------------------------------------------------
# 問題5：承認の判定
# ---------------------------------------------------------------------------
print("\n=== 問題5：承認の判定 ===")
EXPECTED_MODES = ["自動実行", "自動実行", "自動実行", "自動実行", "自動実行",
                  "事後通知", "事前承認", "事後通知", "事前承認", "二重承認",
                  "事前承認", "自動実行"]
rows = gates.judgements()
check("12件そろっている", len(rows) == 12, str(len(rows)))
check("操作単位（規程）の判定が期待どおり",
      [r["操作単位（規程）"] for r in rows] == EXPECTED_MODES,
      str([r["操作単位（規程）"] for r in rows]))
check("同じ submit_expense でも金額で段階が変わる（3,200円は事後通知・68,000円は事前承認）",
      rows[5]["操作単位（規程）"] == "事後通知"
      and rows[6]["操作単位（規程）"] == "事前承認")
check("分類表に無い run_python は止める側に倒れる",
      rows[10]["操作単位（規程）"] == "事前承認" and rows[10]["ツール単位"] == "通す",
      f"{rows[10]['操作単位（規程）']} / {rows[10]['ツール単位']}")
check("基準を10万円にすると 68,000 円が事後通知に落ちる",
      rows[6]["操作単位（10万円）"] == "事後通知",
      rows[6]["操作単位（10万円）"])

EXPECTED_SUMMARY = [
    {"判定": "ツール単位", "止める件数": 4,
     "止め損ない": ["集計コードを隔離環境で実行する"],
     "余計に止める": ["3,200 円の交通費を申請する"]},
    {"判定": "操作単位（基準 50,000 円）", "止める件数": 4,
     "止め損ない": [], "余計に止める": []},
    {"判定": "操作単位（基準 100,000 円）", "止める件数": 3,
     "止め損ない": ["68,000 円の接待交際費を申請する"], "余計に止める": []},
]
summary = gates.summary()
for expected, got in zip(EXPECTED_SUMMARY, summary):
    check(f"{expected['判定']} のずれが期待どおり", got == expected, str(got))
check("止める件数が同じでも中身が違う（ツール単位と操作単位はどちらも4件）",
      summary[0]["止める件数"] == summary[1]["止める件数"] == 4
      and summary[0]["止め損ない"] != summary[1]["止め損ない"])

# ---------------------------------------------------------------------------
# 問題6：失敗の出口
# ---------------------------------------------------------------------------
print("\n=== 問題6：失敗の出口 ===")
EXPECTED_DECISIONS = [
    ("応答が返らない（冪等でない実装）", "部分的", "なし", "いいえ", "人に渡す"),
    ("応答が返らない（冪等な実装）", "部分的", "なし", "はい", "同じ引数で再試行"),
    ("接続できない（冪等でない実装）", "一時的", "なし", "いいえ", "人に渡す"),
    ("接続できない（冪等な実装）", "一時的", "なし", "はい", "同じ引数で再試行"),
    ("会議室の枠が埋まっている", "恒久的", "あり", "いいえ", "引数を変えて再試行"),
    ("内部エラー", "不明", "なし", "はい", "人に渡す"),
]
decisions = failure_map.decisions()
check("6ケースそろっている", len(decisions) == 6, str(len(decisions)))
for expected, got in zip(EXPECTED_DECISIONS, decisions):
    row = (got["ケース"], got["種類"], got["代替案"], got["冪等"], got["判断"])
    check(f"{expected[0]} の判断が期待どおり", row == expected, str(row))
check("同じメッセージでも冪等性で判断が変わる",
      decisions[0]["判断"] == "人に渡す" and decisions[1]["判断"] == "同じ引数で再試行")

EXPECTED_EFFECTS = [
    {"やり方": "無条件に1回再試行（レビュー前の設定）", "増分": 2, "試行": 2,
     "待機": 0.5, "成功": "はい"},
    {"やり方": "判断つきの再試行（冪等でない実装）", "増分": 1, "試行": 1,
     "待機": 0.0, "成功": "いいえ"},
    {"やり方": "判断つきの再試行（冪等キー付きの実装）", "増分": 1, "試行": 2,
     "待機": 0.5, "成功": "はい"},
]
effects = failure_map.side_effects()
for expected, got in zip(EXPECTED_EFFECTS, effects):
    subset = {k: got[k] for k in expected}
    check(f"{expected['やり方']} の副作用が期待どおり", subset == expected, str(subset))
check("無条件の再試行だけが二重申請を作る",
      [row["増分"] for row in effects] == [2, 1, 1],
      str([row["増分"] for row in effects]))
check("待機は記録するだけで実時間では待たない（合計 1.0 秒ぶん）",
      sum(row["待機"] for row in effects) == 1.0,
      str([row["待機"] for row in effects]))

done = failure_map.completion_check()
check("モデルが「登録しました」と言っても done にしない",
      done["stop_reason"] == "error" and done["そのまま返したか"] is False,
      str(done))
check("実行されたか分からない操作を引き継ぎ書に挙げる",
      done["分からない操作を挙げたか"] is True)
check("それでも副作用は1行だけ（申請は登録されている）", done["増分"] == 1,
      str(done["増分"]))

diagram = failure_map.render_mermaid().splitlines()
check("失敗の出口の図は flowchart で始まる", diagram[0] == "flowchart TD", diagram[0])
check("図は13行", len(diagram) == 13, str(len(diagram)))
for word in ("部分的", "一時的", "恒久的・代替案あり", "恒久的・代替案なし", "不明",
             "はい", "いいえ"):
    check(f"図に分岐「{word}」がある", any(f"|{word}|" in line for line in diagram))
check("図に「人に渡す」の出口がある",
      any("stop_reason=error" in line for line in diagram))

# ---------------------------------------------------------------------------
# 問題7：承認したことの証拠
# ---------------------------------------------------------------------------
print("\n=== 問題7：承認したことの証拠 ===")
EXPECTED_CHAIN = [
    ("なし（正しいログ）", 3, "健全", "健全"),
    ("途中の1行を書き換える", 3, "検出", "検出"),
    ("途中の1行を消す", 2, "検出", "検出"),
    ("同じ行を挿入する", 4, "検出", "検出"),
    ("末尾の1行を切り落とす", 2, "健全", "検出"),
]
chain = gates.chain_cases()
check("正しいログと4つの改ざんを並べている", len(chain) == 5, str(len(chain)))
for expected, got in zip(EXPECTED_CHAIN, chain):
    row = (got["改ざん"], got["行数"], got["鎖だけの検査"], got["件数つきの検査"])
    check(f"{expected[0]} の検査結果が期待どおり", row == expected, str(row))
check("末尾の切り落としは鎖だけでは検出できない（S10 の既知の限界）",
      chain[-1]["鎖だけの検査"] == "健全" and chain[-1]["件数つきの検査"] == "検出")
check("件数つきの検査は理由を返す",
      "切り落とされています" in chain[-1]["備考"], chain[-1]["備考"])

# ---------------------------------------------------------------------------
# 問題8：層を積んで測る
# ---------------------------------------------------------------------------
print("\n=== 問題8：層を積んで測る ===")
KEYS = ("外部送信", "書き出し", "機密流入", "遮断", "警告", "越境", "禁止された結果")
EXPECTED_SINGLE = [
    ("権限制限だけ", (2, 1, 0, 0, 0, 3, 3)),
    ("出力検査だけ", (0, 1, 3, 2, 0, 1, 4)),
    ("人間承認だけ", (0, 1, 3, 0, 0, 1, 4)),
]
single_rows = stack.single_rows()
for expected, got in zip(EXPECTED_SINGLE, single_rows):
    row = tuple(got[k] for k in KEYS)
    check(f"{expected[0]} の実測が期待どおり",
          got["構成"] == expected[0] and row == expected[1], f"{got['構成']} {row}")

EXPECTED_STACK = [
    ("① 防御なし", (2, 1, 3, 0, 0, 3, 6)),
    ("② ＋入力検査・構造分離", (2, 1, 3, 0, 3, 3, 6)),
    ("③ ＋権限制限", (2, 1, 0, 0, 3, 3, 3)),
    ("④ ＋出力検査（完全一致）", (0, 1, 0, 2, 3, 1, 1)),
    ("⑤ ＋内容検査（宛先＋内容）", (0, 0, 0, 3, 3, 0, 0)),
]
stack_rows = stack.stack_rows()
for expected, got in zip(EXPECTED_STACK, stack_rows):
    row = tuple(got[k] for k in KEYS)
    check(f"{expected[0]} の実測が期待どおり",
          got["構成"] == expected[0] and row == expected[1], f"{got['構成']} {row}")

EXPECTED_REDUCTION = [
    ("② ＋入力検査・構造分離", 6, 0, "警告 0 → 3"),
    ("③ ＋権限制限", 3, 3, "機密流入 3 → 0"),
    ("④ ＋出力検査（完全一致）", 1, 2, "外部送信 2 → 0"),
    ("⑤ ＋内容検査（宛先＋内容）", 0, 1, "書き出し 1 → 0"),
]
for expected, got in zip(EXPECTED_REDUCTION, stack.reduction(stack_rows)):
    row = (got["足した層"], got["禁止された結果"], got["減った件数"], got["変わったもの"])
    check(f"{expected[0]} で減った件数が期待どおり", row == expected, str(row))
check("気づく層（入力検査・構造分離）は禁止された結果を1件も減らさない",
      stack_rows[0]["禁止された結果"] == stack_rows[1]["禁止された結果"] == 6)
check("測れる層を積むと 6 → 3 → 1 → 0 に減る",
      [r["禁止された結果"] for r in stack_rows] == [6, 6, 3, 1, 0],
      str([r["禁止された結果"] for r in stack_rows]))
check("人間承認だけでは4件残る（権限制限だけの3件より多い）",
      single_rows[2]["禁止された結果"] == 4
      and single_rows[0]["禁止された結果"] == 3)

# ---------------------------------------------------------------------------
# 問題9：仕様に書き戻す
# ---------------------------------------------------------------------------
print("\n=== 問題9：レビューの結論を仕様に書き戻す ===")
check("レビュー後の仕様で監査が0件になる", findings.audit_spec(spec.TO_BE) == [])
check("渡すツールは4本に減っている", len(spec.TO_BE.tools) == 4, str(spec.TO_BE.tools))
check("隔離の指定に read_only と pids_limit が入っている",
      spec.TO_BE.runner["read_only"] is True and spec.TO_BE.runner["pids_limit"] == 64)
check("コード実行の上限が入口の上限（10秒）に収まっている",
      spec.TO_BE.exec_limits["timeout"] == 10.0
      and spec.TO_BE.exec_limits["max_calls"] == 5)
check("承認は操作単位・基準は規程どおり",
      spec.TO_BE.approval["granularity"] == "operation"
      and spec.TO_BE.approval["threshold_yen"] == 50_000)
check("完了の判定は副作用の照合", spec.TO_BE.completion == "effect_check")
check("残余リスクは3件（塞げるものを混ぜない）",
      sorted(answers.Q9) == findings.residual_ids() == ["R1", "R2", "R3"],
      f"{sorted(answers.Q9)} / {findings.residual_ids()}")
check("R4・R5 は塞げるので残余リスクではない",
      findings.RESIDUAL["R4"]["塞ぐ層"] == "出力検査"
      and findings.RESIDUAL["R5"]["塞ぐ層"] == "再試行の判断")
check("残余リスクには検知の方法が書かれている",
      all(findings.RESIDUAL[rid]["検知"] != "—" for rid in findings.residual_ids()))

# ---------------------------------------------------------------------------
# 問題10（実践・任意）：レビュー報告書
# ---------------------------------------------------------------------------
print("\n=== 問題10：レビュー報告書（実践・任意） ===")
report = ROOT / "workspace" / "review03_review.md"
if report.exists():
    text = report.read_text(encoding="utf-8")
    missing = [heading for heading in ("## 信頼境界", "## 穴と塞ぐ層", "## 塞げたことの証拠",
                                       "## 残余リスク", "## 再レビューの引き金")
               if heading not in text]
    check("報告書に5つの節がそろっている", not missing, str(missing))
    check("報告書に「プロンプトで守る」と書いていない",
          "プロンプトで守" not in text)
else:
    print("SKIP workspace/review03_review.md が無いため報告書の検査を飛ばします")

# ---------------------------------------------------------------------------
reset_data()

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\n復習03の検証はすべて成功しました。")
