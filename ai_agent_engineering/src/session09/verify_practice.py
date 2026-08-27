#!/usr/bin/env python3
"""セッション9の練習問題の自己検証。

本文・practice・solutions に載せた主張と数値をここで機械判定する。
1つでも満たさなければ非0で終了するので、出力を読んで判断する必要はない。

    docker compose exec app python src/session09/verify_practice.py

`tool-runner` が動いていない環境では SKIP_RUNNER=1 で隔離実行の検証を飛ばせる
（純粋な判断・打ち切りの検証だけを実行する）。
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ex_probe  # noqa: E402
import leak  # noqa: E402
from artifacts import DEMO_CODE, digests, run_with_artifacts  # noqa: E402
from ex_handback import CODE_EXTRA, CODE_MISSING, run_declared  # noqa: E402
from ex_orphan import orphan_demo, runner_orphan_demo  # noqa: E402
from guard import (AUDIT_PATH, BYPASS_NETWORK, ExecBudget, check_limits,  # noqa: E402
                   clip_stdout, looks_dangerous, run_guarded)
from policy import (CASES, CHOICES, NONROOT_CASES, decide,  # noqa: E402
                    predict_nonroot)
from probes import probe_all  # noqa: E402

SKIP_RUNNER = os.environ.get("SKIP_RUNNER") == "1"
failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def raises_value_error(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    return False


def finish() -> None:
    if failures:
        print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
        sys.exit(1)
    print("\nセッション9の演習の検証はすべて成功しました。")
    sys.exit(0)


# --- 問題2：3択の判断 -------------------------------------------------------
EXPECTED_DECISIONS = ["限定的に許す", "隔離して許す", "隔離して許す",
                      "限定的に許す", "許さない", "許さない"]
decisions = [decide(req)[0] for req in CASES]
check("6つの要求の判断が期待どおり", decisions == EXPECTED_DECISIONS, str(decisions))
check("3つの選択肢すべてが使われている", set(decisions) == set(CHOICES), str(sorted(set(decisions))))
check("判断には必ず理由が付く", all(decide(req)[1] for req in CASES))

# --- 問題9：非 root 実行の予測 ----------------------------------------------
EXPECTED_NONROOT = [
    "書ける（所有者が一致している）",
    "書けない（Permission denied）",
    "書ける（その他ユーザーに書き込みが開いている）",
    "書ける（所有者が一致している）",
    "読み取りだけなら動く",
    "書けない（Permission denied）",
]
predicted = [predict_nonroot(*case) for case in NONROOT_CASES]
check("非 root 実行の予測が期待どおり", predicted == EXPECTED_NONROOT, str(predicted))
check("root でも所有者が違えば書けない",
      predict_nonroot(0, 1000, False, True) == "書けない（Permission denied）")

# --- 問題6：上限の検査 ------------------------------------------------------
check_limits(10.0, 128)  # 例外が出たらここで落ちる（それが期待どおり）
check("上限内の依頼は通る", True)
check("timeout=0 を断る", raises_value_error(lambda: check_limits(0, 128)))
check("timeout が上限超えを断る", raises_value_error(lambda: check_limits(10.1, 128)))
check("memory_mb=0 を断る", raises_value_error(lambda: check_limits(10.0, 0)))
check("memory_mb が上限超えを断る", raises_value_error(lambda: check_limits(10.0, 129)))

budget = ExecBudget(max_calls=2, max_seconds=20.0)
check("予算内なら通す", budget.check(5.0) is None)
budget.record(0.2)
budget.record(0.2)
check("回数の上限で断る", "実行回数" in (budget.check(5.0) or ""), str(budget.check(5.0)))
seconds_budget = ExecBudget(max_calls=5, max_seconds=5.0)
check("最悪の場合で時間の予算を判定する",
      "実行時間" in (seconds_budget.check(6.0) or ""), str(seconds_budget.check(6.0)))

check("上限内の出力はそのまま返す", clip_stdout("abc", 10) == ("abc", 0))
check("上限を超えた出力は切って捨てた量を返す",
      clip_stdout("x" * 3001, 2000) == ("x" * 2000, 1001))

check("文字列検査はそのまま書いた import を止める",
      looks_dangerous("import socket\nprint('ok')\n") == "import socket")
check("文字列検査は組み立てられた import を止められない",
      looks_dangerous(BYPASS_NETWORK) is None)

# --- 問題8：打ち切りと孤児プロセス（隔離コンテナ不要）-----------------------
single = orphan_demo(kill_group=False)
check("直接の子だけを殺すと孫が生き残る",
      single["打ち切った"] and single["孫が生き残った"], str(single))
group = orphan_demo(kill_group=True)
check("プロセスグループごと殺すと孫も止まる",
      group["打ち切った"] and not group["孫が生き残った"], str(group))

if SKIP_RUNNER:
    print("\nSKIP_RUNNER=1 のため、隔離実行を伴う検証を飛ばしました。")
    finish()

# --- 問題1・3：境界のプローブ -----------------------------------------------
rows = probe_all()
check("プローブが15本ある", len(rows) == 15, f"{len(rows)} 本")
ng = [r["境界"] for r in rows if not r["ok"]]
check("すべての境界が期待どおり", not ng, str(ng))
observed = {r["境界"]: r["観測"] for r in rows}
check("実行ユーザーはまだ root", observed.get("実行ユーザー（いまは root）") == "0",
      str(observed.get("実行ユーザー（いまは root）")))

# --- 問題6：唯一の入口 ------------------------------------------------------
first = run_guarded("print(sum(range(10)))", label="verify")
check("入口を通した実行が成功する", first["ok"] and first["stdout"].strip() == "45",
      first["stdout"].strip() or str(first["error"]))
audit_text = json.dumps(first["audit"], ensure_ascii=False)
check("監査にコード本文を残さない", "print" not in audit_text, audit_text)
check("監査にコードの指紋を残す", len(first["audit"]["code_sha256"]) == 16)
last_line = AUDIT_PATH.read_text(encoding="utf-8").strip().splitlines()[-1]
check("監査がファイルに残る",
      json.loads(last_line)["code_sha256"] == first["audit"]["code_sha256"])

one_shot = ExecBudget(max_calls=1, max_seconds=20.0)
ok1 = run_guarded("print('1回目')", timeout=5.0, budget=one_shot, label="verify-budget")
ok2 = run_guarded("print('2回目')", timeout=5.0, budget=one_shot, label="verify-budget")
check("予算を使い切ったら実行せずに断る",
      ok1["ok"] and not ok2["ok"] and bool(ok2["refused"]), str(ok2["refused"]))
check("断った実行は監査に残さない", ok2["audit"] is None)

bypass = run_guarded(BYPASS_NETWORK, timeout=6.0, label="verify-bypass")
check("文字列検査を抜けても境界は抜けられない",
      "BLOCKED" in bypass["stdout"], bypass["stdout"].strip() or str(bypass["error"]))

# --- 問題5：結果の受け渡し --------------------------------------------------
art = run_with_artifacts(DEMO_CODE, job="verify")
check("標準出力が上限で切られる",
      len(art["stdout"]) == 2000 and art["dropped"] == 1001,
      f"{len(art['stdout'])} 文字 / 捨てた {art['dropped']} 文字")
names = [f["name"] for f in art["files"]]
check("マニフェストが3件そろう", names == ["huge.txt", "notes.bin", "summary.csv"], str(names))
check("受け取るのは summary.csv だけ",
      [f["name"] for f in art["files"] if f["accepted"]] == ["summary.csv"])
check("summary.csv は 28 バイト",
      [f["bytes"] for f in art["files"] if f["name"] == "summary.csv"] == [28])
check("捨てた理由が2種類ある",
      sorted(f["reason"] for f in art["files"] if not f["accepted"])
      == ["大きすぎます（上限 65536 バイト）", "許可していない拡張子です（.bin）"],
      str([f["reason"] for f in art["files"] if not f["accepted"]]))
check("モデルには参照だけを渡す",
      art["references"] == ["session09/out/verify/summary.csv"], str(art["references"]))
check("同じコードなら生成物の指紋が一致する",
      digests(art) == digests(run_with_artifacts(DEMO_CODE, job="verify")))

extra = run_declared(CODE_EXTRA, declares=["summary.csv"], job="verify_extra")
check("宣言外のファイルは捨てる",
      extra["ok"] and extra["accepted"] == ["summary.csv"] and extra["missing"] == [],
      str(extra["accepted"]))
check("捨てた理由が「宣言されていません」になる",
      [(f["name"], f["reason"]) for f in extra["files"] if not f["accepted"]]
      == [("scratch.txt", "宣言されていません")],
      str([(f["name"], f["reason"]) for f in extra["files"] if not f["accepted"]]))
missing = run_declared(CODE_MISSING, declares=["summary.csv", "chart.md"],
                       job="verify_missing")
check("宣言したのに作られなかったら失敗にする",
      not missing["ok"] and missing["missing"] == ["chart.md"], str(missing["missing"]))

# --- 問題4：隔離の穴 --------------------------------------------------------
hole = ex_probe.probe()
check("失敗したのに生成物が残る穴を再現できる", hole["ok"], str(hole))
check("残ったのは途中までの 22 バイト", hole["残ったバイト数"] == 22,
      str(hole["残ったバイト数"]))

leaks = leak.run_all()
check("共有しているものは3つとも破れる",
      all(r["破れた"] for r in leaks),
      str([(r["穴"], r["破れた"]) for r in leaks]))

# --- 問題8：同梱の worker は孫を残す ----------------------------------------
runner_row = runner_orphan_demo()
check("同梱の worker は打ち切っても孫を残す",
      runner_row["打ち切った"] and runner_row["孫が生き残った"], str(runner_row))

# --- 問題7：pytest による軌跡テスト -----------------------------------------
if not (ROOT / "data" / "expenses.jsonl").exists():
    check("data/ が生成されている", False, "先に python tools/make_data.py を実行してください")
elif importlib.util.find_spec("pytest") is None:
    print("SKIP pytest が入っていないため軌跡テストの実行を飛ばします")
else:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(HERE / "test_isolation.py"),
         "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, check=False)
    check("pytest による軌跡テストが通る", proc.returncode == 0,
          f"returncode={proc.returncode}")
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)

finish()
