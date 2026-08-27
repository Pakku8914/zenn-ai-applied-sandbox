#!/usr/bin/env python3
"""セッション7の自己検証：溢れる過程・圧縮・長期メモリが主張どおりに動くこと。

本文（body / practice / solutions）に載せた出力・数値もここで検証している。
数値が変わる変更をしたときは、NG 行に出る実測値に合わせて本文を直すこと。
検証の前後で `tools/make_data.py` を走らせるので、データは初期状態に戻る。

    python src/session07/verify.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.biztools import WORKSPACE  # noqa: E402
from agentkit.memory import ShortTermMemory, extract_constraints  # noqa: E402
from bigtools import (CONSTRAINT_LINE, fetch_audit_log,  # noqa: E402
                      list_expense_records, read_audit_policy)
from compress import apply_policy, groups  # noqa: E402
from longterm import (AuditMemory, pollution_report, recall_modes,  # noqa: E402
                      reset_data)
from records import (RECORD_WIDTH, TOKENS_PER_RECORD, body_of,  # noqa: E402
                     breakdown, constraints, kind_of, record, retention,
                     to_records, tokens)
from runner import (MAX_CONTEXT, active_rules, build, judge,  # noqa: E402
                    render_run)

EXPECTED_NONE = """task_id=TASK-007 policy=none stop_reason=budget 手数=4
  step 0 記録=6 近似=66 （ツールなし）
  step 1 記録=7 近似=77 read_audit_policy:ok +3
  step 2 記録=11 近似=121 fetch_audit_log:ok +120
  step 3 記録=132 近似=1452 fetch_audit_log:ok +120
  final: コンテキスト上限を超えました（記録253 / 近似2783 > 上限1980）。\
圧縮方式 none では続行できません。"""

EXPECTED_KEEP = """task_id=TASK-007 policy=keep stop_reason=done 手数=7
  step 0 記録=6 近似=66 （ツールなし）
  step 1 記録=7 近似=77 read_audit_policy:ok +3
  step 2 記録=11 近似=121 fetch_audit_log:ok +120
  step 3 記録=132 近似=1452 fetch_audit_log:ok +120
  step 4 記録=180 近似=1980 [圧縮] list_expense_records:ok +6
  step 5 記録=180 近似=1980 [圧縮] write_audit_report:ok +1
  step 6 記録=180 近似=1980 [圧縮] （ツールなし）
  final: 監査を終え、レポートを保存しました。"""

# 方式 → (手数, 最終記録数, 近似トークン, 制約, 指摘, 停止理由, 圧縮回数)
EXPECTED_RESULTS = {
    "none": (4, 253, 2783, "7/7", 0, "budget", 0),
    "truncate": (7, 181, 1991, "1/7", 0, "done", 3),
    "summarize": (7, 145, 1595, "6/7", 2, "done", 1),
    "keep": (7, 181, 1991, "7/7", 3, "done", 3),
    "externalize": (7, 27, 297, "7/7", 3, "done", 0),
    "summarize_all": (7, 18, 198, "0/7", 0, "done", 1),
}

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def run(policy: str):
    memory = AuditMemory(f"verify_{policy}")
    memory.clear()
    runner = build(policy, longterm=memory)
    return runner, runner.run()


reset_data()

# --- 1. 記録の正規化 --------------------------------------------------------
rec = record("制約", "5万円以上は必ず事前承認が必要。")
check("1記録は33文字・近似11トークン",
      len(rec) == RECORD_WIDTH == 33 and TOKENS_PER_RECORD == 11,
      f"{len(rec)}文字 / {TOKENS_PER_RECORD}トークン")
check("種別と本文を取り出せる",
      kind_of(rec) == "制約" and body_of(rec) == "5万円以上は必ず事前承認が必要。",
      f"{kind_of(rec)} / {body_of(rec)}")
check("近似トークン数は記録数×11で決まる",
      tokens([rec] * 180) == 1_980 == MAX_CONTEXT, str(tokens([rec] * 180)))

# --- 2. ツール結果の大きさ --------------------------------------------------
log07 = to_records(fetch_audit_log("2026-07"))
log08 = to_records(fetch_audit_log("2026-08"))
policy_recs = to_records(read_audit_policy("経費精算"))
expense_recs = to_records(list_expense_records("all"))
check("監査ログは1か月120記録（近似1,320トークン）",
      len(log07) == len(log08) == 120 and tokens(log07) == 1_320,
      f"{len(log07)} / {tokens(log07)}")
check(f"{CONSTRAINT_LINE}行目に監査方針の追記（制約）が紛れている",
      kind_of(log07[CONSTRAINT_LINE - 1]) == "制約"
      and body_of(log07[CONSTRAINT_LINE - 1]) == "07-031 必ず注記のある申請も対象に。"
      and body_of(log08[CONSTRAINT_LINE - 1]) == "08-031 上限: 監査は6件まで。",
      body_of(log07[CONSTRAINT_LINE - 1]))
check("ログは実データの申請を参照している（7月1件・8月5件）",
      sum(1 for r in log07 if "起票" in r) == 1
      and sum(1 for r in log08 if "起票" in r) == 5
      and body_of(log07[10]) == "07-011 EXP-0004 145000円 起票",
      body_of(log07[10]))
check("規程は3記録（うち制約2）・一覧は6記録",
      len(policy_recs) == 3 and len(constraints(policy_recs)) == 2
      and len(expense_recs) == 6, f"{len(policy_recs)} / {len(expense_recs)}")
check("ログ1回ぶんが1つのかたまりとして見える",
      groups(log07) == [(0, 120, "07")]
      and groups(log07 + log08) == [(0, 120, "07"), (120, 240, "08")],
      str(groups(log07)))

# --- 3. 既定の ShortTermMemory は何も圧縮しない -----------------------------
plain = ShortTermMemory(items=list(log07 + log08), max_tokens=MAX_CONTEXT)
check("240記録を入れても勝手に縮まない（わざと残した欠け）",
      len(plain.items) == 240 and plain.total_tokens() == 2_640
      and plain.overflowing(),
      f"{len(plain.items)}記録 / {plain.total_tokens()}トークン")

# --- 4. 溢れる過程 ---------------------------------------------------------
naive, traj = run("none")
check("圧縮なしはステップ4の手前で溢れて止まる",
      render_run(traj) == EXPECTED_NONE,
      "" if render_run(traj) == EXPECTED_NONE else "\n" + render_run(traj))
check("ステップ別の記録数は 6 → 7 → 11 → 132",
      [s.usage["records"] for s in traj.steps] == [6, 7, 11, 132],
      str([s.usage["records"] for s in traj.steps]))
check("溢れた瞬間の内訳はツール結果が94.5%",
      [(r["要素"], r["記録数"], r["割合"]) for r in breakdown(naive.memory.items)]
      == [("指示・制約", 10, 4.0), ("思考", 4, 1.6), ("ツール結果", 239, 94.5)],
      str(breakdown(naive.memory.items)))
logs_in_memory = [r for r in naive.memory.items
                  if r.startswith("[ログ]") or r.startswith("[制約] 0")]
check("うち監査ログ由来が240記録（94.9%）",
      len(logs_in_memory) == 240
      and round(len(logs_in_memory) / len(naive.memory.items) * 100, 1) == 94.9,
      f"{len(logs_in_memory)}記録")
check("溢れても制約は落ちていない（落としたのは圧縮の側）",
      retention(naive.first_seen, naive.memory.items)["残った制約"] == 7,
      str(retention(naive.first_seen, naive.memory.items)))

# --- 5. 圧縮方式を1回だけ適用したときの比較 --------------------------------
snapshot = naive.memory
expected_once = {"truncate": (180, 1_980, 1), "summarize": (135, 1_485, 6),
                 "keep": (180, 1_980, 7), "summarize_all": (8, 88, 0)}
for name, (n, tok, kept) in expected_once.items():
    after = apply_policy(name, snapshot)
    info = retention(snapshot.items, after.items)
    check(f"{name}: {n}記録 / 近似{tok} / 制約{kept}件",
          len(after.items) == n and after.total_tokens() == tok
          and info["残った制約"] == kept and not after.overflowing(),
          f"{len(after.items)}記録 / {after.total_tokens()} / "
          f"制約{info['残った制約']}件")
check("切り捨ては同じ大きさでも制約を6件落とす（選択的保持は0件）",
      len(retention(snapshot.items, apply_policy('truncate', snapshot).items)
          ["落ちた制約"]) == 6
      and retention(snapshot.items, apply_policy('keep', snapshot).items)
      ["落ちた制約"] == [])
check("順序は保たれる（選択的保持は制約を先頭に寄せない）",
      apply_policy("keep", snapshot).items[0] == snapshot.items[0]
      and apply_policy("keep", snapshot).items[-1] == snapshot.items[-1])
regex_first = snapshot.keep_constraints()
check("agentkit の keep_constraints は制約を先頭に寄せる（順序が変わる）",
      kind_of(regex_first.items[0]) == "制約"
      and regex_first.items[0] != snapshot.items[0],
      body_of(regex_first.items[0]))

# --- 6. 完走させたときの成果 ------------------------------------------------
runners = {}
trajs = {}
for policy, expected in EXPECTED_RESULTS.items():
    runner, t = run(policy)
    runners[policy] = runner
    trajs[policy] = t
    row = runner.result(t)
    got = (row["手数"], row["最終記録数"], row["近似トークン"], row["制約"],
           row["指摘"], row["停止理由"], row["圧縮回数"])
    check(f"{policy}: 手数{expected[0]} 記録{expected[1]} 近似{expected[2]} "
          f"制約{expected[3]} 指摘{expected[4]}件 {expected[5]}",
          got == expected, str(got))
    if policy == "keep":
        check("選択的保持の実行ログが本文の表示と一致する",
              render_run(t) == EXPECTED_KEEP,
              "" if render_run(t) == EXPECTED_KEEP else "\n" + render_run(t))

check("切り捨てと選択的保持は同じ大きさに収まる（成果だけが違う）",
      runners["truncate"].memory.total_tokens()
      == runners["keep"].memory.total_tokens() == 1_991
      and len(judge(runners["truncate"].memory.items)) == 0
      and len(judge(runners["keep"].memory.items)) == 3)
check("いちばん安い方式（全部要約）がいちばん成果が無い",
      runners["summarize_all"].memory.total_tokens() == 198
      and len(judge(runners["summarize_all"].memory.items)) == 0)

# --- 7. 成果物（レポート）の中身 --------------------------------------------
def report(policy: str) -> str:
    path = WORKSPACE / "session07" / f"audit_{policy}.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


keep_report = report("keep")
check("選択的保持のレポートは指摘3件（EXP-0002 / EXP-0004 / EXP-0005）",
      "指摘: 3 件" in keep_report
      and "- EXP-0002 ← 金額 / 注記" in keep_report
      and "- EXP-0004 ← 金額 / 期限 / 注記" in keep_report
      and "- EXP-0005 ← 注記" in keep_report
      and "適用した制約: 金額 / 期限 / 注記 / 件数上限" in keep_report,
      keep_report.replace("\n", " / "))
check("切り捨てのレポートは「件数上限」しか適用できず0件",
      "適用した制約: 件数上限" in report("truncate")
      and "指摘: 0 件" in report("truncate")
      and "（判定に使える制約がメモリに残っていません）" in report("truncate"))
check("要約のレポートは注記の制約を失って2件になる",
      "指摘: 2 件" in report("summarize")
      and "- EXP-0005" not in report("summarize")
      and "適用した制約: 金額 / 期限 / 件数上限" in report("summarize"))
check("外部化のレポートは圧縮なしと同じ結論に到達する",
      "指摘: 3 件" in report("externalize"))
check("完走した4方式は最終回答も停止理由も同じ（成果物を見ないと気づけない）",
      {p: (trajs[p].final, trajs[p].stop_reason)
       for p in ("truncate", "summarize", "keep", "externalize")}
      == {p: ("監査を終え、レポートを保存しました。", "done")
          for p in ("truncate", "summarize", "keep", "externalize")},
      str({p: trajs[p].final for p in ("truncate", "keep")}))

# --- 8. 制約の見つけ方（種別タグ と 正規表現）------------------------------
all_constraints: list[str] = []
for r in constraints(runners["keep"].first_seen):
    if r not in all_constraints:
        all_constraints.append(r)
regex_hits = [r for r in all_constraints if extract_constraints(r)]
check("種別タグでは7件、正規表現では5件しか制約と見なせない",
      len(all_constraints) == 7 and len(regex_hits) == 5,
      f"タグ{len(all_constraints)}件 / 正規表現{len(regex_hits)}件")
check("取りこぼすのは期限に関する2件",
      sorted(body_of(r) for r in all_constraints if r not in regex_hits)
      == ["支出日から10日以内に申請。", "申請は支出日から10日以内。"],
      str([body_of(r) for r in all_constraints if r not in regex_hits]))
check("有効な判定規則は制約から導かれる",
      active_rules(runners["keep"].memory.items)
      == ["amount", "deadline", "note", "cap"]
      and active_rules(runners["truncate"].memory.items) == ["cap"]
      and active_rules(runners["summarize"].memory.items)
      == ["amount", "deadline", "cap"],
      str(active_rules(runners["truncate"].memory.items)))

# --- 9. 外部化と引き戻し ----------------------------------------------------
ext_memory = AuditMemory("verify_externalize")
lines = ext_memory.recall_lines("EXP-0004")
check("長期メモリから行単位で引き戻せる（全部戻さない）",
      len(lines) == 1 and body_of(lines[0]) == "07-011 EXP-0004 145000円 起票",
      str([body_of(x) for x in lines]))
check("外部化しても制約は短期メモリに残す",
      any("必ず注記のある申請も対象に。" in body_of(r)
          for r in constraints(runners["externalize"].memory.items)))
check("長期メモリに入ったのはログ2回ぶんだけ",
      [row["key"] for row in ext_memory.rows()]
      == ["fetch_audit_log:2026-07", "fetch_audit_log:2026-08"],
      str([row["key"] for row in ext_memory.rows()]))

# --- 10. 忘却設計（期限と重要度）-------------------------------------------
forget_mem = AuditMemory("verify_forget")
forget_mem.clear()
forget_mem.remember("notice:工事", "みなと は7月末まで工事中", kind="notice",
                    importance=1, expires_on="2026-07-31", source="設備部の連絡")
forget_mem.remember("policy:承認", "5万円以上は事前承認", kind="fact",
                    importance=3, expires_on=None, source="規程")
expired_hits = forget_mem.recall("みなと 工事")
check("期限切れの記憶は引かれない（保存はされている）",
      len(forget_mem.rows()) == 2
      and all("工事" not in hit["body"] for hit in expired_hits)
      and any("5万円以上は事前承認" == hit["body"]
              for hit in forget_mem.recall("5万円 承認")),
      f"{len(forget_mem.rows())}件保存 / "
      f"引けた記憶={[hit['body'] for hit in expired_hits]}")
check("期限切れを掃除すると1件だけ残る",
      forget_mem.forget_expired() == 1 and len(forget_mem.rows()) == 1
      and forget_mem.rows()[0]["importance"] == 3)

# --- 11. いつ引くか ---------------------------------------------------------
modes = recall_modes()
check("引かないと1回失敗する / 毎回引くと3回引く / 直前だけなら1回",
      [(m["方式"], m["引いた回数"], m["予約の試行"], m["失敗"], m["押さえた枠"])
       for m in modes]
      == [("none", 0, 2, 1, "11:00"), ("always", 3, 1, 0, "11:00"),
          ("conditional", 1, 1, 0, "11:00")],
      str(modes))
check("どの方式でも予約は1件（記憶は結果を変えず、回り道だけを変える）",
      all(m["予約された行数"] == 1 for m in modes),
      str([m["予約された行数"] for m in modes]))

# --- 12. メモリの汚染 -------------------------------------------------------
poll = pollution_report()
check("偽の競合は失敗として現れない（成功するので気づけない）",
      poll["偽の競合"]["予約の試行"] == 1 and poll["偽の競合"]["失敗"] == 0
      and poll["偽の競合"]["押さえた枠"] == "10:00", str(poll["偽の競合"]))
check("空きだと誤って覚えた枠は失敗になる（こちらは気づける）",
      poll["見落とし"]["予約の試行"] == 2 and poll["見落とし"]["失敗"] == 1
      and poll["見落とし"]["押さえた枠"] == "14:00", str(poll["見落とし"]))
check("外部の事実と照合すると誤った記憶2件を検出できる",
      len(poll["照合結果"]) == 3
      and sum(1 for r in poll["照合結果"] if not r["一致"]) == 2
      and poll["破棄した記憶"] == 2,
      str([(r["記憶"], r["一致"]) for r in poll["照合結果"]]))
check("破棄すると本来使えた枠（09:00）を使えるようになる",
      poll["破棄後"]["押さえた枠"] == "09:00"
      and poll["破棄後"]["失敗"] == 0, str(poll["破棄後"]))

# --- 13. 上限を変えたときの溢れる位置（練習問題2）--------------------------
for limit, steps, reason, recs, toks in ((1_000, 3, "budget", 132, 1_452),
                                        (3_000, 7, "done", 263, 2_893)):
    runner = build("none", max_context_tokens=limit)
    t = runner.run()
    check(f"上限{limit}: 手数{steps} / {reason} / {recs}記録",
          (len(t.steps), t.stop_reason, len(runner.memory.items),
           runner.memory.total_tokens()) == (steps, reason, recs, toks),
          f"{len(t.steps)}手 / {t.stop_reason} / {len(runner.memory.items)}記録 / "
          f"{runner.memory.total_tokens()}")
ratio = round(2_893 / runners["externalize"].memory.total_tokens(), 1)
check("上限を上げて完走させると、外部化の約9.7倍のプロンプトを送り続ける",
      ratio == 9.7, f"{ratio}倍")

# --- 14. 練習問題の解答コード ----------------------------------------------
from ex_memory import (guard_report, recall_into_memory,  # noqa: E402
                       run_with_keep_summary)

kept_runner, kept_traj = run_with_keep_summary()
kept_row = kept_runner.result(kept_traj)
check("問題5: 制約を残す要約器なら146記録・制約7/7・指摘3件",
      (kept_row["手数"], kept_row["最終記録数"], kept_row["近似トークン"],
       kept_row["制約"], kept_row["指摘"], kept_row["停止理由"],
       kept_row["圧縮回数"]) == (7, 146, 1_606, "7/7", 3, "done", 1),
      str(kept_row))

ext_runner = runners["externalize"]
before_records = len(ext_runner.memory.items)
recalled = recall_into_memory(ext_runner, "EXP-0004")
check("問題6: 引き戻すのは1行だけ（27記録 → 28記録）",
      len(recalled) == 1 and before_records == 27
      and len(ext_runner.memory.items) == 28
      and ext_runner.memory.total_tokens() == 308,
      f"{before_records} → {len(ext_runner.memory.items)}")

guard = guard_report()
check("問題8: ガードは欠けた規則を名前で報告する",
      guard["truncate"]["欠けた規則"] == ["amount", "deadline", "note"]
      and guard["summarize"]["欠けた規則"] == ["note"]
      and guard["keep"]["欠けた規則"] == []
      and guard["externalize"]["欠けた規則"] == [],
      str({k: v["欠けた規則"] for k, v in guard.items()}))
check("問題8: 欠けた規則の数と指摘の減り方が対応する",
      [(len(guard[p]["欠けた規則"]), guard[p]["指摘"])
       for p in ("truncate", "summarize", "keep")]
      == [(3, 0), (1, 2), (0, 3)],
      str({k: v["指摘"] for k, v in guard.items()}))

reset_data()

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション7の検証はすべて成功しました。")
