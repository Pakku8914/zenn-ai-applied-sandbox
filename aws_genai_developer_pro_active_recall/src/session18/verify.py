#!/usr/bin/env python3
"""セッション18の検証。

    docker compose exec app python src/session18/verify.py

**期待値と一致しなければ非0で終了します。** 判定に使うのは決定的な性質だけです。

    * ゴールデンデータセットの形（正解文書・正解の値・答えが無い質問・カバレッジ）
    * 検索の評価が設定で動くこと。動きの向きが説明できること（k・分類フィルタ）
    * 生成の評価が検索と分かれていること（正解文書を必ず含む文脈で測る）
    * 検索が当たっているのに答えられない件を、生成の問題として切り分けられること
    * 採点役の判定を、機械判定が覆せること（拒否権）と、一致率で採否を決める手順
    * 品質ゲートが、ベースラインでは合格し、目標のしきい値では非0で終了すること

**検索スコアの絶対値は判定に使いません。** モックの埋め込みは文字 n-gram のハッシュで、
値そのものに意味が無いためです。使うのは「必ずこうなる」関係だけです。

    k=12（全件を返す）なら Recall@k は 1.0 で、精度は 1/12
    正しい分類で絞れば母集団は3件なので Recall@k は 1.0 で、精度は 1/3
    誤った分類で絞ると正解が母集団から消えるので Recall@k は 0.0

採点役の一致率も合否条件にしていません（同梱モックの採点役は採点していないため）。
見るのは「同じ入力なら同じ採点か」「計算が正しいか」「ゲートに使わない判断ができるか」です。
"""

from __future__ import annotations

import json
import sys
import urllib.request

sys.path.insert(0, "/workspace")
for _dir in ("session04", "session05", "session06", "session14", "session15", "session18"):
    sys.path.insert(0, f"/workspace/src/{_dir}")

from awskit import clients  # noqa: E402

import judge  # noqa: E402  セッション15

import eval_dataset as dataset  # noqa: E402
import eval_harness as harness  # noqa: E402
import gate  # noqa: E402
import judge_check  # noqa: E402

FAILURES: list[str] = []

EXPECTED_TOTAL = 12
EXPECTED_ANSWERABLE = 10
EXPECTED_UNANSWERABLE = 2
EXPECTED_COVERAGE = 8

# 呼び出しは「生成の評価12件」「再現性の確認1件」「採点役12件＋再現性1件」だけ
EXPECTED_GENERATION_CALLS = 12
EXPECTED_REDO_CALLS = 1
EXPECTED_JUDGE_CALLS = 13

# **これは「正しい姿」ではなく「いまの姿」です。** カタカナ語だけで聞いた2件は資料に
# 答えがあるのに答えられていません。ベースラインに固定しておくと、直したときに気づけます
EXPECTED_GENERATION_PROBLEMS = ["q-09", "q-10"]
EXPECTED_MECHANICAL_PASS = ["q-01", "q-02", "q-03", "q-04", "q-05", "q-06", "q-07", "q-08"]
EXPECTED_BLIND_SPOTS = ["q-11", "q-12"]
EXPECTED_EMPTY_REWRITES = ["q-05", "q-06", "q-07", "q-08"]
EXPECTED_TARGET_FAILURES = ["generationGrounded", "generationFactual", "supportRatio"]


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def mock_post(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        f"{clients.mock_base_url()}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def mock_calls() -> int:
    with urllib.request.urlopen(f"{clients.mock_base_url()}/_mock/usage", timeout=10) as res:
        return json.loads(res.read())["calls"]


def main() -> int:
    # 前の演習の障害注入と会計が残っていると、突き合わせが狂う
    mock_post("/_mock/reset", {})

    agent = clients.agent_runtime()
    runtime = clients.bedrock_runtime()
    rows = dataset.rows()
    answerable = dataset.answerable(rows)

    # ------------------------------------------------------------------
    section("1. ゴールデンデータセット")
    check(
        f"質問は {EXPECTED_TOTAL} 件（答えられる {EXPECTED_ANSWERABLE} / 答えが無い"
        f" {EXPECTED_UNANSWERABLE}）",
        (len(rows), len(answerable), len(dataset.unanswerable(rows)))
        == (EXPECTED_TOTAL, EXPECTED_ANSWERABLE, EXPECTED_UNANSWERABLE),
        (len(rows), len(answerable)),
    )
    counts = dataset.category_counts(rows)
    check("分類は4つとも 3 件ずつ", set(counts.values()) == {3}, counts)
    check(
        "答えられる質問には正解文書と正解の値がある",
        all(row["docId"] in dataset.URI_OF and row["goldValue"] for row in answerable),
        [row["id"] for row in answerable if not row["goldValue"]],
    )
    check(
        "答えが無い質問には正解文書も正解の値も置かない",
        all(
            row["docId"] is None and row["goldValue"] is None
            for row in dataset.unanswerable(rows)
        ),
    )
    covered, total_docs = dataset.coverage(rows)
    check(
        f"正解文書のカバレッジは {total_docs} 文書のうち {EXPECTED_COVERAGE} 件",
        (covered, total_docs) == (EXPECTED_COVERAGE, 12),
        (covered, total_docs),
    )
    check(
        "質問文に重複が無い",
        len({row["question"] for row in rows}) == len(rows),
    )
    check(
        "誤った分類は正解の分類と必ず別になる",
        all(
            dataset.WRONG_CATEGORY_OF[category] != category
            for category in dataset.CATEGORIES
        ),
    )

    # ------------------------------------------------------------------
    section("2. 検索の評価（設定を変えると点が動く）")
    before = mock_calls()
    reports = {
        config["id"]: harness.evaluate_retrieval(agent, config, answerable)
        for config in harness.CONFIGS
    }
    again = harness.evaluate_retrieval(agent, harness.config_by_id("cfg-03"), answerable)
    retrieval_calls = mock_calls() - before

    check(
        "k を 1 -> 3 に増やすと Recall@k は下がらない",
        reports["cfg-02"]["recall"] >= reports["cfg-01"]["recall"],
        (reports["cfg-01"]["recall"], reports["cfg-02"]["recall"]),
    )
    check(
        "k=12（母集団の全件）なら Recall@k は 1.0",
        reports["cfg-06"]["recall"] == 1.0,
        reports["cfg-06"]["recall"],
    )
    check(
        "k=12 のときの精度は 0.0833（正解1件 ÷ 12件）",
        reports["cfg-06"]["precision"] == 0.0833,
        reports["cfg-06"]["precision"],
    )
    check(
        "正しい分類で絞れば k=3 でも Recall@k は 1.0",
        reports["cfg-07"]["recall"] == 1.0,
        reports["cfg-07"]["recall"],
    )
    check(
        "正しい分類で絞ったときの精度は 0.3333（正解1件 ÷ 3件）",
        reports["cfg-07"]["precision"] == 0.3333,
        reports["cfg-07"]["precision"],
    )
    check(
        "誤った分類で絞ると Recall@k は 0.0（正解が母集団から消える）",
        reports["cfg-08"]["recall"] == 0.0,
        reports["cfg-08"]["recall"],
    )
    check(
        "Recall を k で買うと精度は下がる",
        reports["cfg-06"]["precision"] < reports["cfg-07"]["precision"],
    )
    check("誤った分類では MRR も 0.0 になる", reports["cfg-08"]["mrr"] == 0.0)
    check(
        "同じ設定を2回流すと同じスコアになる（決定的）",
        (again["recall"], again["precision"], again["mrr"])
        == (
            reports["cfg-03"]["recall"],
            reports["cfg-03"]["precision"],
            reports["cfg-03"]["mrr"],
        ),
    )
    check(
        f"クエリ書き換えが空になる質問が {len(EXPECTED_EMPTY_REWRITES)} 件ある"
        "（語彙辞書に無い語で聞かれている）",
        reports["cfg-04"]["emptyRewrites"] == EXPECTED_EMPTY_REWRITES,
        reports["cfg-04"]["emptyRewrites"],
    )
    empty_row = next(row for row in answerable if row["id"] == "q-05")
    check(
        "書き換えが空のときは元の質問に戻している（空文字を投げない）",
        harness.query_for(harness.config_by_id("cfg-04"), empty_row)
        == (empty_row["question"], True),
    )
    check(
        "検索の採点で基盤モデルを1回も呼んでいない",
        retrieval_calls == 0,
        retrieval_calls,
    )

    # ------------------------------------------------------------------
    section("3. 生成の評価（検索を満点にした状態で測る）")
    before = mock_calls()
    generation = harness.evaluate_generation(runtime, agent, rows)
    generation_calls = mock_calls() - before
    check(
        f"生成で呼んだ回数は {EXPECTED_GENERATION_CALLS} 回（1件につき1回）",
        generation_calls == EXPECTED_GENERATION_CALLS,
        generation_calls,
    )
    check(
        "引用は全件で3件（正しい分類の3文書）",
        all(row["citationCount"] == 3 for row in generation["rows"]),
        [row["citationCount"] for row in generation["rows"]],
    )
    check(
        "根拠提示率は 0.8（8/10）",
        (generation["grounded"], generation["groundedRate"]) == (8, 0.8),
        (generation["grounded"], generation["groundedRate"]),
    )
    check(
        "事実一致率は 0.8（8/10）",
        (generation["factual"], generation["factualRate"]) == (8, 0.8),
        (generation["factual"], generation["factualRate"]),
    )
    check("裏取りの平均は 0.8", generation["supportMean"] == 0.8, generation["supportMean"])
    check(
        "答えが無い2件はどちらも断れている（適切な拒否率 1.0）",
        (generation["refused"], generation["refusalRate"]) == (2, 1.0),
        (generation["refused"], generation["refusalRate"]),
    )
    check(
        "ハルシネーション率は 0.0",
        generation["hallucinationRate"] == 0.0,
        generation["hallucinationRate"],
    )
    check(
        "答えられなかったのは q-09 と q-10（カタカナ語だけで聞いた質問）",
        generation["generationProblems"] == EXPECTED_GENERATION_PROBLEMS,
        generation["generationProblems"],
    )
    check(
        "答えられた8件は裏取りが 1.0（資料の文をそのまま引いている）",
        all(row["support"] == 1.0 for row in generation["answerable"] if row["ok"]),
    )
    check(
        "答えられなかった2件は「資料の範囲外」と応答している",
        all(
            row["refused"] and row["support"] == 0.0
            for row in generation["answerable"]
            if not row["ok"]
        ),
    )
    first = generation["rows"][0]
    before = mock_calls()
    citations, sources = harness.context_for(agent, rows[0])
    redo = harness.generate(runtime, rows[0]["question"], sources)
    redo_calls = mock_calls() - before
    check(
        "同じ質問を2回投げると同じ答えになる（呼び出し1回ぶん）",
        redo == first["answer"] and redo_calls == EXPECTED_REDO_CALLS,
        redo_calls,
    )
    check(
        "文脈の並び順は文書 ID の昇順に固定されている",
        [citation["docId"] for citation in citations]
        == sorted(citation["docId"] for citation in citations),
        [citation["docId"] for citation in citations],
    )

    # ------------------------------------------------------------------
    section("4. 切り分け（検索の問題か、生成の問題か）")
    shipped = harness.diagnose(reports[harness.SHIPPED_CONFIG_ID], generation)
    broken = harness.diagnose(reports["cfg-08"], generation)
    check(
        "正しい分類では 検索の問題 0 件 / 生成の問題 2 件 / ok 8 件",
        (len(shipped["retrievalProblems"]), len(shipped["generationProblems"]), len(shipped["ok"]))
        == (0, 2, 8),
        (shipped["retrievalProblems"], shipped["generationProblems"]),
    )
    check(
        "生成の問題と判定されたのは q-09 と q-10",
        shipped["generationProblems"] == EXPECTED_GENERATION_PROBLEMS,
        shipped["generationProblems"],
    )
    check(
        "誤った分類では 10 件すべてが検索の問題",
        len(broken["retrievalProblems"]) == 10 and broken["generationProblems"] == [],
        (len(broken["retrievalProblems"]), broken["generationProblems"]),
    )
    check(
        "検索が外れている件は、生成の点にかかわらず検索の問題と判定される",
        all(verdict == "retrieval" for verdict in broken["verdicts"].values()),
    )

    # ------------------------------------------------------------------
    section("5. 採点役（LLM-as-a-Judge）の妥当性")
    cases = judge_check.cases_from(generation)
    before = mock_calls()
    reviewed = judge_check.review(runtime, cases)
    twice = judge.score_answer(
        runtime, answer=cases[0]["answer"], evidence=cases[0]["evidence"]
    )
    judge_calls = mock_calls() - before
    check(
        "生成役と採点役は別のモデル",
        reviewed["generatorModelId"] != reviewed["judgeModelId"],
        (reviewed["generatorModelId"], reviewed["judgeModelId"]),
    )
    check(
        f"採点役の呼び出しは {EXPECTED_JUDGE_CALLS} 回（12件 ＋ 再現性の確認1回）",
        judge_calls == EXPECTED_JUDGE_CALLS,
        judge_calls,
    )
    check(
        "同じ入力なら同じ採点になる",
        twice["verdict"] == reviewed["rows"][0]["judge"],
        (twice["verdict"], reviewed["rows"][0]["judge"]),
    )
    check(
        "機械判定が合格にするのは引用付きで答えた8件だけ",
        reviewed["mechanicalPass"] == EXPECTED_MECHANICAL_PASS,
        reviewed["mechanicalPass"],
    )
    check(
        "機械判定が不合格なら最終判定も不合格（拒否権）",
        judge_check.veto_respected(reviewed),
        [row for row in reviewed["rows"] if row["mechanical"] != "pass"],
    )
    check(
        "断るのが正解の2件も機械判定は不合格にする（機械判定の限界）",
        reviewed["mechanicalBlindSpots"] == EXPECTED_BLIND_SPOTS,
        reviewed["mechanicalBlindSpots"],
    )
    check(
        "一致率は一致件数と母数から計算されている",
        reviewed["agreementRate"] == round(reviewed["agreed"] / reviewed["total"], 4)
        and 0.0 <= reviewed["agreementRate"] <= 1.0,
        reviewed["agreementRate"],
    )
    check(
        "一致率がしきい値を下回る採点役はゲートに使わない",
        judge_check.usable_in_gate({"agreementRate": 0.89}) is False
        and judge_check.usable_in_gate({"agreementRate": 0.9}) is True,
    )

    # ------------------------------------------------------------------
    section("6. 品質ゲート")
    metrics = harness.measure(retrieval=reports[harness.SHIPPED_CONFIG_ID], generation=generation)
    check("ゲートが読む指標は7つ", tuple(metrics) == gate.METRICS, tuple(metrics))
    baseline = gate.decide(metrics, "baseline")
    target = gate.decide(metrics, "target")
    check(
        "baseline のしきい値では合格（終了コード 0）",
        baseline["passed"] and gate.exit_code(baseline) == 0,
        baseline["failed"],
    )
    check(
        "target のしきい値では不合格（終了コード 1）",
        not target["passed"] and gate.exit_code(target) == 1,
        target["failed"],
    )
    check(
        "target で割るのは 根拠提示率・事実一致率・裏取り の3つ",
        target["failed"] == EXPECTED_TARGET_FAILURES,
        target["failed"],
    )
    regressed = gate.decide({**metrics, "generationFactual": 0.7}, "baseline")
    check(
        "事実一致率が 0.8 -> 0.7 に落ちるとベースラインが落ちる（回帰の検知）",
        regressed["failed"] == ["generationFactual"],
        regressed["failed"],
    )
    worse = gate.decide({**metrics, "hallucinationRate": 0.5}, "baseline")
    check(
        "ハルシネーション率は上限として判定される",
        worse["failed"] == ["hallucinationRate"],
        worse["failed"],
    )
    latency_row = next(
        row for row in baseline["rows"] if row["metric"] == "retrievalLatencyMsP95"
    )
    check(
        "環境で変わる指標（検索レイテンシ）は実測値を表示しない",
        latency_row["hidden"] and "(非表示)" in gate.report_line(latency_row),
        gate.report_line(latency_row),
    )

    print()
    if FAILURES:
        print(f"NG: {len(FAILURES)} 件の検証に失敗しました -> {FAILURES}")
        return 1
    print("セッション18の検証に成功しました（課金は一切発生していません）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
