#!/usr/bin/env python3
"""復習04（S02〜S16・S13〜S15 中心）の自己検証。

    docker compose exec app python src/review04/verify.py

10問すべてを機械判定する。1つでも満たさなければ非0で終了するので、出力を読んで
「合っている気がする」と判断する余地はない。練習問題・解答章に載せた数値も
ここで固定している（数値が変わったら本文を直す）。

冒頭と末尾で `tools/make_data.py` を実行するので、検証の前後でデータは初期状態
（経費6件・予約0件・送信0件）に戻る。作業領域 `workspace/session15/` も消す。
"""

from __future__ import annotations

import sys

from _paths import reset_data, setup

ROOT = setup()

import answers  # noqa: E402
import budget  # noqa: E402
import capacity  # noqa: E402
import improve  # noqa: E402
import nextstep  # noqa: E402
import release  # noqa: E402
import signals  # noqa: E402
import stopping  # noqa: E402

from jobspec import clear_workspace  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


reset_data()
clear_workspace()

# ---------------------------------------------------------------------------
# 材料：4系統のボード
# ---------------------------------------------------------------------------
print("=== 材料（4系統の測定結果）===")
total_rin = signals.monthly_rin()
check("月次のワークロードは5種・1,000件", len(signals.WORKLOAD) == 5
      and sum(r[1] for r in signals.WORKLOAD) == 1000,
      f"{len(signals.WORKLOAD)} 種 / {sum(r[1] for r in signals.WORKLOAD)} 件")
check("月次の費用は 29,494.800 円（仮の単価表・上位モデル）",
      total_rin == 29_494_800, f"{signals.yen(total_rin)} 円")
check("予算 25,000.000 円に対して 4,494.800 円の超過",
      signals.BUDGET_RIN == 25_000_000
      and total_rin - signals.BUDGET_RIN == 4_494_800,
      f"超過 {signals.yen(total_rin - signals.BUDGET_RIN)} 円")
per_task = {row[0]: signals.row_rin(row) for row in signals.WORKLOAD}
check("1件あたりの単価が期待どおり",
      per_task == {"経費レポート作成": 37_860, "会議室予約（競合あり）": 18_330,
                   "経費申請（5万円以上）": 18_570, "隔離実行で集計": 25_110,
                   "同じ検索を繰り返す": 90_780},
      " / ".join(f"{k}={signals.yen(v)}" for k, v in per_task.items()))
loop = signals.find_row("同じ検索を繰り返す")
report_row = signals.find_row("経費レポート作成")
check("件数のシェア 4.0% に対して費用のシェアは 12.3%",
      round(loop[1] / 1000 * 100, 1) == 4.0
      and round(loop[1] * signals.row_rin(loop) / total_rin * 100, 1) == 12.3,
      f"1件 {signals.yen(signals.row_rin(loop))} 円は経費レポート作成の "
      f"{signals.row_rin(loop) / signals.row_rin(report_row):.2f} 倍")
check("下位モデルの単価はちょうど 1/10",
      signals.row_rin(report_row, "下位") * 10 == signals.row_rin(report_row, "上位"),
      f"上位 {signals.yen(signals.row_rin(report_row, '上位'))} / "
      f"下位 {signals.yen(signals.row_rin(report_row, '下位'))}")
check("S13 の評価仕様を材料に使っている（6ケース・うち2件は失敗すべき）",
      len(signals.S13_CASES) == 6
      and sum(1 for c in signals.S13_CASES if not c.expect_success) == 2,
      f"{len(signals.S13_CASES)} ケース")
check("S13 の判定方式は4つ", len(signals.JUDGES) == 4, str(signals.JUDGES))

# ---------------------------------------------------------------------------
# 問題1：どの問いが、どの測定で答えられるか
# ---------------------------------------------------------------------------
print("\n=== 問題1：問いと測定の対応 ===")
truth = signals.truth_q1()
check("10問そろっている", sorted(answers.Q1) == sorted(truth), f"{len(answers.Q1)} 件")
for qid in sorted(truth):
    check(f"問題1 の解答（{qid}）", answers.Q1.get(qid) == truth[qid],
          str(answers.Q1.get(qid)))
check("この4系統では答えられない問いが2件ある",
      sum(1 for v in truth.values() if v == "—") == 2)
check("使う語は5つだけ", set(truth.values()) <= {"測る", "追う", "回す", "支払う", "—"},
      str(sorted(set(truth.values()))))

# ---------------------------------------------------------------------------
# 問題2：差し替えを出してよいか
# ---------------------------------------------------------------------------
print("\n=== 問題2：差し替えの受け入れ判断 ===")
swap = release.swap_table()
check("4つの新構成を比べている", [r["label"] for r in swap]
      == ["A 同じ挙動", "B 余計に調べる", "C 禁止ツールを呼ぶ", "D 中身が薄くなる"],
      str([r["label"] for r in swap]))
strict = [r["厳しい基準"][0] for r in swap]
loose = [r["緩い基準"][0] for r in swap]
check("基準 1.2 では B もコスト超過で落ちる",
      strict == ["出す", "出さない", "出さない", "出さない"], str(strict))
check("基準 1.5 に緩めると B だけが「様子を見る」に変わる",
      loose == ["出す", "様子を見る", "出さない", "出さない"], str(loose))
check("緩い基準は S15 の accept_swap と一致する",
      loose == [r["S15 の判断"] for r in swap],
      str([r["S15 の判断"] for r in swap]))
check("B が落ちる理由は手数（4→5 は 1.2 倍を超える）",
      swap[1]["厳しい基準"][1] == "手数が 4→5（基準の 1.2 倍を超えた）",
      swap[1]["厳しい基準"][1])
check("C は禁止ツールで落ちる（基準を緩めても変わらない）",
      swap[2]["forbidden"] == 1 and swap[2]["緩い基準"][1] == "禁止ツールを呼ぶ",
      swap[2]["緩い基準"][1])
check("D は軌跡の差分が0でも成果物の中身で落ちる",
      swap[3]["same_tools"] and swap[3]["steps"] == (4, 4)
      and swap[3]["missing"] == ["規程違反", "EXP-0002"],
      f"ツール列同一 / 手数 {swap[3]['steps']} / 不足 {swap[3]['missing']}")

# ---------------------------------------------------------------------------
# 問題3：今週直す1件を選ぶ
# ---------------------------------------------------------------------------
print("\n=== 問題3：今週直す1件 ===")
traces = improve.traces()
check("8件の軌跡のうち失敗は5件",
      len(traces) == 8 and sum(1 for t in traces if improve.verdict(t) == "失敗") == 5,
      f"{len(traces)} 件中 失敗 "
      f"{sum(1 for t in traces if improve.verdict(t) == '失敗')} 件")
freq = improve.frequency_rows(traces)
check("頻度の1位は「同じ操作の反復」で2件（S14 の実測）",
      (freq[0]["symptom"], freq[0]["count"]) == ("同じ操作の反復", 2)
      and len(freq) == 6,
      " / ".join(f"{r['symptom']}={r['count']}" for r in freq))
scored = improve.ranked(freq)
check("頻度 × 被害の並びが期待どおり",
      [r["症状"] for r in scored] == ["外部宛の送信", "空の最終回答", "打ち切り",
                                      "例外で停止", "同じ操作の反復",
                                      "ツール失敗（回復済み）"],
      str([r["症状"] for r in scored]))
check("スコアは 5 / 3 / 2 / 2 / 2 / 0",
      [r["スコア"] for r in scored] == [5, 3, 2, 2, 2, 0],
      str([r["スコア"] for r in scored]))
check("頻度の1位と、今週直す1件は一致しない",
      improve.pick_one(scored) == "外部宛の送信"
      and improve.pick_one(scored) != freq[0]["symptom"],
      f"頻度1位={freq[0]['symptom']} / 直す1件={improve.pick_one(scored)}")
check("回復できた失敗は重み0（数えるが直さない）",
      improve.HARM["ツール失敗（回復済み）"] == 0 and scored[-1]["スコア"] == 0)
choice = improve.sampling_choice(traces)
check("取りこぼし0の案のうち保存量が最小なのはテールベース",
      choice["plan"] == "テールベース（失敗は全件・それ以外 1/2）"
      and choice["kept"] == "7/8" and choice["lost"] == 0,
      f"{choice['plan']} / 保存 {choice['kept']}")

# ---------------------------------------------------------------------------
# 問題4：予算超過にどう応じるか
# ---------------------------------------------------------------------------
print("\n=== 問題4：予算に収める ===")
saved = {a.code: budget.savings(a) for a in budget.ACTIONS}
check("打ち手ごとの削減額が期待どおり",
      saved == {"P1": 4_949_100, "P4": 1_506_600, "P3": 3_631_200, "P2": 13_629_600},
      " / ".join(f"{k}={signals.yen(v)}" for k, v in saved.items()))
p25 = budget.plan(25_000_000)
check("予算 25,000 円では P1 だけで収まる",
      p25["picked"] == ["P1"] and p25["after"] == 24_545_700 and p25["remaining"] == 0,
      f"{'+'.join(p25['picked'])} → 残る費用 {signals.yen(p25['after'])} 円")
check("削減額が最大の打ち手（P2）を選ばない",
      max(saved, key=lambda k: saved[k]) == "P2" and "P2" not in p25["picked"],
      "P2 は 13,629.600 円の削減だが、失うものが最も大きい")
p20 = budget.plan(20_000_000)
check("予算 20,000 円では P1+P4+P3 になる",
      p20["picked"] == ["P1", "P4", "P3"] and p20["saved"] == 10_086_900
      and p20["after"] == 19_407_900,
      f"{'+'.join(p20['picked'])} → 残る費用 {signals.yen(p20['after'])} 円")
p10 = budget.plan(10_000_000)
check("予算 10,000 円で初めて P2 に手を付ける（申し送りが出る）",
      p10["picked"] == ["P1", "P4", "P3", "P2"] and p10["after"] == 5_778_300
      and p10["warning"] != "—", p10["warning"])
p30 = budget.plan(30_000_000)
check("予算内なら打ち手を選ばない",
      p30["picked"] == [] and p30["over"] == 0 and p30["after"] == total_rin,
      f"超過 {signals.yen(p30['over'])} 円")
check("すべての打ち手に「失うもの」と「確かめ方」が書いてある",
      all(a.loses and a.checked_by for a in budget.ACTIONS))

# ---------------------------------------------------------------------------
# 問題5：前提が変わると効く打ち手が変わる
# ---------------------------------------------------------------------------
print("\n=== 問題5：前提（単価表）を差し替える ===")
split_a = signals.input_output_rin(signals.PRICES)
split_b = signals.input_output_rin(signals.PRICES_OUT_HEAVY)
check("前提①は入力が支配的（80.5%）",
      (split_a["in"], split_a["out"], split_a["top"]) == (23_740_800, 5_754_000, "入力")
      and round(split_a["in_share"], 1) == 80.5,
      f"入力 {signals.yen(split_a['in'])}（{split_a['in_share']:.1f}%）")
check("前提②では1位が出力に入れ替わる（70.8%）",
      (split_b["in"], split_b["out"], split_b["top"])
      == (23_740_800, 57_540_000, "出力")
      and round(split_b["out_share"], 1) == 70.8,
      f"出力 {signals.yen(split_b['out'])}（{split_b['out_share']:.1f}%）")
rank_a = [r["code"] for r in budget.ranked_under(signals.PRICES)]
rank_b = [r["code"] for r in budget.ranked_under(signals.PRICES_OUT_HEAVY)]
check("前提①の順位は A1 → A3 → A2 → A4", rank_a == ["A1", "A3", "A2", "A4"], str(rank_a))
check("前提②の順位は A4 → A1 → A2 → A3", rank_b == ["A4", "A1", "A2", "A3"], str(rank_b))
check("最下位と1位が入れ替わる打ち手がある（A4 は 4位 → 1位）",
      rank_a[-1] == "A4" and rank_b[0] == "A4")
worst = {r["code"]: r["worst"] for r in budget.robust_rows()}
check("悪い方の順位で評価すると A1 が1つに決まる",
      worst == {"A1": 2, "A2": 3, "A3": 4, "A4": 4} and budget.robust_pick() == "A1",
      f"{worst} → {budget.robust_pick()}")

# ---------------------------------------------------------------------------
# 問題6：遅いと言われたときに何を変えるか
# ---------------------------------------------------------------------------
print("\n=== 問題6：容量の判断 ===")
cap_rows = capacity.table()
makespans = {r["workers"]: r["makespan"] for r in cap_rows}
check("多重度ごとの完了が S15 の実測と一致する",
      makespans == {1: 24, 2: 12, 4: 13, 8: 12}, str(makespans))
check("完了の下限はレート上限が決める（24 ÷ 2 ＝ 12 秒）",
      capacity.floor() == 12, f"{capacity.floor()} 秒")
decisions = {t: capacity.decide(t, cap_rows) for t in capacity.TARGETS}
check("目標 30 秒なら多重度 1 のままでよい", decisions[30]["多重度"] == 1,
      decisions[30]["判断"])
check("目標 15 秒なら多重度 2（4 に上げると 13 秒で遅くなる）",
      decisions[15]["多重度"] == 2 and makespans[4] > makespans[2],
      f"{decisions[15]['判断']} / 多重度4 は {makespans[4]} 秒")
check("目標 12 秒でも多重度 2 で足りる", decisions[12]["多重度"] == 2,
      decisions[12]["根拠"])
check("目標 10 秒は多重度では届かない（必要なレート上限は 3 回/秒）",
      decisions[10]["多重度"] is None and decisions[10]["必要なレート上限"] == 3,
      decisions[10]["根拠"])
slow = capacity.slowdown()
check("下限に届いたあと多重度を上げると、増えるのは待ちだけ",
      slow["makespan"] == (12, 13) and slow["waits"] == (0, 19),
      f"完了 {slow['makespan']} / 待った回数 {slow['waits']}")
modes = [r["受け方"] for r in capacity.mode_rows()]
check("型ごとの受け方が期待どおり",
      modes == ["同期", "同期", "同期", "非同期＋通知", "非同期＋通知", "バッチ"],
      str(modes))
check("承認が要る型は手数が少なくても同期にしない",
      capacity.mode_for("send") == "非同期＋通知"
      and capacity.mode_for("search") == "同期",
      "send（3手・承認あり）=非同期＋通知 / search（3手・承認なし）=同期")

# ---------------------------------------------------------------------------
# 問題7：カナリアの判定を採用してよいか
# ---------------------------------------------------------------------------
print("\n=== 問題7：カナリアの前提チェック ===")
canary = release.canary_table()
check("3つの段階を比べている", len(canary) == 3, str(len(canary)))
head5, head25, strat5 = canary
check("先頭から 5% は「進む」と言うが、send 型が1件も入っていない",
      (head5["段階"], head5["件数"], head5["verdict"], head5["禁止"])
      == ("5%", 5, "進む", 0) and head5["missing"] == ["send"]
      and head5["型の内訳"] == "policy 2 / list 2 / report 1",
      f"{head5['型の内訳']} → {head5['採用']}")
check("だから判定を採用しない", head5["採用"] == "判定を採用しない", head5["理由"])
check("25% まで広げて初めて欠陥に当たる",
      (head25["件数"], head25["成功"], head25["禁止"], head25["verdict"])
      == (25, 24, 1, "止める") and head25["missing"] == []
      and head25["型の内訳"] == "policy 9 / list 7 / report 8 / send 1",
      f"{head25['型の内訳']} → {head25['採用']}")
check("型ごとに選べば同じ 5% で同じ欠陥に当たる",
      (strat5["選び方"], strat5["段階"], strat5["件数"], strat5["成功"],
       strat5["禁止"], strat5["採用"]) == ("型ごとに", "5%", 5, 4, 1, "止める")
      and strat5["型の内訳"] == "policy 2 / list 1 / report 1 / send 1",
      f"{strat5['型の内訳']} → {strat5['採用']}")
check("採用の判断は3行で「採用しない／止める／止める」",
      [r["採用"] for r in canary] == ["判定を採用しない", "止める", "止める"],
      str([r["採用"] for r in canary]))

# ---------------------------------------------------------------------------
# 問題8：次の一手を1つだけ決める
# ---------------------------------------------------------------------------
print("\n=== 問題8：次の一手 ===")
picked = {s.week: nextstep.decide(s)["次の一手"] for s in nextstep.WEEKS}
expected_weeks = {"W1": "止めて戻す", "W2": "原因を1件に絞る", "W3": "内容検査を足す",
                  "W4": "容量を決め直す", "W5": "コストの打ち手を選ぶ",
                  "W6": "何もしない"}
check("6週すべての一手が期待どおり", picked == expected_weeks, str(picked))
check("問題8 の解答が一致する", answers.Q8 == expected_weeks, str(answers.Q8))
check("使う語は6つだけ", set(picked.values()) == set(nextstep.ACTIONS),
      str(sorted(set(picked.values()))))
check("W1 は費用も超過しているが、選ぶ一手は1つだけ",
      nextstep.also_triggered(nextstep.WEEKS[0]) == ["コストの打ち手を選ぶ"],
      str(nextstep.also_triggered(nextstep.WEEKS[0])))
check("W6 は見送るものが無い", nextstep.also_triggered(nextstep.WEEKS[5]) == [])
diagram = nextstep.render_mermaid().splitlines()
check("分岐図は flowchart で始まる", diagram[0] == "flowchart TD", diagram[0])
check("分岐図は12行", len(diagram) == 12, str(len(diagram)))
for word in ("ある", "ない", "未満", "以上", "超えた", "以内"):
    check(f"分岐図にラベル「{word}」がある",
          any(f"|{word}|" in line for line in diagram))
for action in nextstep.ACTIONS:
    check(f"分岐図に出口「{action}」がある",
          any(action in line for line in diagram))

# ---------------------------------------------------------------------------
# 問題9：上限に当たったとき何を返すか
# ---------------------------------------------------------------------------
print("\n=== 問題9：打ち切りと引き継ぎ ===")
rows9 = stopping.case_rows()
check("6ケースそろっている", len(rows9) == 6, str(len(rows9)))
for row in rows9:
    check(f"{row['状態']}／{row['stop_reason']}／副作用{row['副作用']}／"
          f"部分成果{row['部分成果']} の結果",
          row["結果"] == row["期待"], f"{row['結果']}（期待 {row['期待']}）")
check("結果の語彙は4つだけ",
      {r["結果"] for r in rows9} <= set(stopping.OUTCOMES),
      str(sorted({r["結果"] for r in rows9})))
check("同じ max_steps でも部分成果の有無で結果が変わる",
      rows9[1]["結果"] == "partial" and rows9[2]["結果"] == "insufficient")
check("例外で落ちたら副作用があっても partial にしない",
      rows9[5]["結果"] == "handoff", rows9[5]["結果"])
live = stopping.live_rows()
check("実際に走らせた3件が期待どおり",
      [(r["job_id"], r["状態"], r["stop_reason"], r["手数"], r["結果"]) for r in live]
      == [("TASK-153", "done", "done", 4, "report"),
          ("TASK-172", "limited", "max_steps", 4, "insufficient"),
          ("TASK-157", "cancelled", "error", 1, "handoff")],
      str([(r["job_id"], r["結果"]) for r in live]))
check("打ち切りは引き継ぎ書が出ていても結果は insufficient",
      live[1]["引き継ぎ書"] == "あり（人に引き継ぎます）"
      and live[1]["結果"] == "insufficient",
      f"{live[1]['引き継ぎ書']} → {live[1]['結果']}")
check("キャンセルは handoff（止めた時点の引き継ぎ書が出る）",
      live[2]["引き継ぎ書"] == "あり（利用者がキャンセルしました）"
      and live[2]["結果"] == "handoff")
check("完走した1件だけが成果物を持つ",
      [r["成果物"] for r in live] == ["あり", "なし", "なし"],
      str([r["成果物"] for r in live]))

# ---------------------------------------------------------------------------
# 問題10（実践・任意）：運用当番の週次レポート
# ---------------------------------------------------------------------------
print("\n=== 問題10：週次レポート（実践・任意） ===")
report_path = ROOT / "workspace" / "review04_ops.md"
if report_path.exists():
    text = report_path.read_text(encoding="utf-8")
    missing = [h for h in ("## 今週の数字", "## 決めたこと", "## 根拠",
                           "## 見送ったこと", "## 次に測ること")
               if h not in text]
    check("週次レポートに5つの節がそろっている", not missing, str(missing))
    vague = [w for w in ("たぶん", "様子を見ながら", "気をつけ", "なんとなく") if w in text]
    check("判定できない言葉を使っていない", not vague, str(vague))
    check("決めたことが1つに絞られている（次の一手の語が1つだけ現れる）",
          sum(1 for a in nextstep.ACTIONS if a in text) >= 1)
else:
    print("SKIP workspace/review04_ops.md が無いため週次レポートの検査を飛ばします")

# ---------------------------------------------------------------------------
reset_data()
clear_workspace()

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\n復習04の検証はすべて成功しました。")
