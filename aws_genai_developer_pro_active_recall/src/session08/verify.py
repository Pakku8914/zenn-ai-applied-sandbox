#!/usr/bin/env python3
"""セッション8の検証。

MCP サーバー（stdio / JSON-RPC 2.0）・ツール定義の書き方・ツール側のエラー処理・
マルチエージェントの編成・人の承認ゲートの5点を確かめます。
**期待値と一致しなければ非0で終了します。**

    docker compose exec app python src/session08/verify.py

判定に使うのは「選ばれたツール名」「JSON-RPC の応答の形」「エラーコード」「往復の回数」の
ように決定的な性質だけです。生成された文章そのものの一致は条件にしていません
（唯一の例外は、規程に書かれた数値 15000 が回答に含まれるかどうかです）。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, "/workspace")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from awskit import clients  # noqa: E402

import approval  # noqa: E402
import mcp_agent  # noqa: E402
import mcp_client  # noqa: E402
import squad  # noqa: E402

FAILURES: list[str] = []

QUESTION = "出張の宿泊費の上限はいくらですか？"
KB_QUERY = "有給休暇 繰越 上限"
# ex-001（出張旅費の精算）に書かれた国内出張の宿泊費上限。
# これが回答に出れば「資料を根拠に答えた」と言える
GROUND_TRUTH = "15000"

RESET_ACTION = ("reset_user_password", {"employee_id": "EMP-0042"})
DENIED_ACTION = ("reset_user_password", {"employee_id": "EMP-0777"})


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


def text_of(result: dict) -> str:
    return "\n".join(block.get("text", "") for block in result.get("content", []))


def payload_of(result: dict) -> dict:
    return json.loads(text_of(result))


def drain_queue(sqs, queue_url: str, max_rounds: int = 12) -> list[dict]:
    """キューを空になるまで受信して削除し、本文を返す（前回の実行分を消す）。"""
    drained: list[dict] = []
    empty_rounds = 0
    for _ in range(max_rounds):
        response = sqs.receive_message(
            QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=1
        )
        messages = response.get("Messages", [])
        if not messages:
            empty_rounds += 1
            if empty_rounds >= 2:
                break
            continue
        empty_rounds = 0
        for message in messages:
            drained.append(json.loads(message["Body"]))
            sqs.delete_message(
                QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"]
            )
    return drained


def first_tool(trace: dict) -> str:
    return trace["tool_calls"][0]["name"] if trace["tool_calls"] else ""


def main() -> int:
    # 前の演習の障害注入設定と会計が残っていると測定値が変わるため必ずリセットする
    mock_post("/_mock/reset", {})

    runtime = clients.bedrock_runtime()
    client = mcp_client.MCPClient()
    init = client.start()
    try:
        executor = mcp_agent.make_executor(client)

        # ------------------------------------------------------------------
        section("1. MCP サーバーとの3つのやりとり")
        check(
            "initialize がプロトコル版・能力・サーバー名を返す",
            init["protocolVersion"] == mcp_client.PROTOCOL_VERSION
            and "tools" in init["capabilities"]
            and init["serverInfo"]["name"] == "sample-shoji-helpdesk-tools",
            init,
        )
        # 通知（id なし）に応答が返っていれば、この直後の tools/list で id がずれる
        client.notify("notifications/initialized")
        tools = client.list_tools()
        check("tools/list が5本の道具を返す", len(tools) == 5, [t["name"] for t in tools])
        check(
            "どの道具にも名前・説明文・入力スキーマがある",
            all(
                t.get("name") and t.get("description") and t.get("inputSchema")
                for t in tools
            ),
        )
        by_name = {t["name"]: t for t in tools}
        search_schema = by_name["search_internal_docs"]["inputSchema"]
        check("検索の必須引数は query だけ", search_schema["required"] == ["query"])
        check(
            "件数（top_k）はスキーマに無い（チューニング値はサーバーの既定に持たせる）",
            "top_k" not in search_schema["properties"],
            list(search_schema["properties"]),
        )
        check(
            "読み取り専用かどうかのヒントが付いている",
            by_name["search_internal_docs"]["annotations"]["readOnlyHint"] is True
            and by_name["reset_user_password"]["annotations"]["readOnlyHint"] is False,
        )

        hit_result = client.call_tool("search_internal_docs", {"query": KB_QUERY})
        hits = payload_of(hit_result)["hits"]
        check("tools/call で検索できる（上位3件）", len(hits) == 3, len(hits))
        check(
            "「有給休暇 繰越 上限」の1位は年次有給休暇の文書",
            hits[0]["uri"].endswith("hr/paid-leave.md"),
            hits[0]["uri"],
        )

        tool_config = mcp_client.to_tool_config(tools)
        spec = tool_config["tools"][0]["toolSpec"]
        check(
            "MCP のスキーマが Converse の inputSchema.json に入る",
            spec["inputSchema"]["json"]["type"] == "object"
            and spec["name"] == tools[0]["name"]
            and spec["description"] == tools[0]["description"],
        )
        check(
            "名前を指定すると渡す道具を絞れる",
            len(mcp_client.to_tool_config(tools, names=["search_internal_docs"])["tools"])
            == 1,
        )
        rejected = False
        try:
            mcp_client.to_tool_config(tools, names=["search_the_web"])
        except mcp_client.MCPError:
            rejected = True
        check("サーバーに無い道具を指定すると弾かれる", rejected)

        # ------------------------------------------------------------------
        section("2. JSON-RPC のエラーの返し方（呼び出し側のバグ）")
        codes: dict[str, int | None] = {}
        for label, call in (
            ("未対応のメソッド", lambda: client.request("resources/list")),
            ("未知のツール", lambda: client.call_tool("search_the_web", {})),
        ):
            codes[label] = None
            try:
                call()
            except mcp_client.MCPRpcError as error:
                codes[label] = error.code
        check("未対応のメソッドは -32601", codes["未対応のメソッド"] == -32601, codes)
        check("未知のツールは -32602", codes["未知のツール"] == -32602, codes)

        broken = client.send_raw_line("{ これは JSON ではありません\n")
        check(
            "壊れた行は -32700（Parse error）で、接続は生きたまま",
            broken["error"]["code"] == -32700,
            broken,
        )
        check("パースエラーのあとも通信を続けられる", len(client.list_tools()) == 5)

        bare = mcp_client.MCPClient()
        bare.start(initialize=False)
        try:
            uninitialized: int | None = None
            try:
                bare.request("tools/list")
            except mcp_client.MCPRpcError as error:
                uninitialized = error.code
            check(
                "initialize の前の tools/list は -32002（実装が使える予約帯）",
                uninitialized == -32002,
                uninitialized,
            )
        finally:
            bare.close()  # 使い終わったプロセスは必ず落とす

        # ------------------------------------------------------------------
        section("3. ツール側のエラー処理（引数検証と部分失敗）")
        missing = client.call_tool("search_internal_docs", {})
        check(
            "必須引数の欠落は JSON-RPC エラーではなく isError で返る",
            missing["isError"] is True and "query は必須です" in text_of(missing),
            text_of(missing),
        )
        bad_enum = client.call_tool(
            "search_internal_docs", {"query": KB_QUERY, "category": "宿泊費"}
        )
        check(
            "候補外の値は「使える候補」まで書いて返す",
            bad_enum["isError"] is True and "セキュリティ" in text_of(bad_enum),
            text_of(bad_enum),
        )
        unknown_arg = client.call_tool(
            "search_internal_docs", {"query": KB_QUERY, "top_k": 5}
        )
        check(
            "スキーマに無い引数は受け付けない",
            unknown_arg["isError"] is True and "受け付けない引数" in text_of(unknown_arg),
            text_of(unknown_arg),
        )
        wrong_type = client.call_tool("run_maintenance_scan", {"duration_ms": "1000"})
        check(
            "型違いは integer で渡すよう指摘する",
            wrong_type["isError"] is True and "integer" in text_of(wrong_type),
            text_of(wrong_type),
        )
        too_long = client.call_tool("run_maintenance_scan", {"duration_ms": 5000})
        check(
            "サーバー自身が上限（2000ms）を持っている",
            too_long["isError"] is True and "2000" in text_of(too_long),
            text_of(too_long),
        )

        bad_id = client.call_tool("lookup_expense_report", {"report_id": "宿泊費"})
        check(
            "申請番号の形が違えば、代わりに何をすべきかまで書いて返す",
            bad_id["isError"] is True and "社内規程の検索" in text_of(bad_id),
            text_of(bad_id),
        )
        found = client.call_tool("lookup_expense_report", {"report_id": "EXP-000123"})
        check(
            "正しい申請番号なら進捗が返る",
            found["isError"] is False and payload_of(found)["status"] == "承認待ち",
            text_of(found),
        )
        not_found = client.call_tool(
            "lookup_expense_report", {"report_id": "EXP-999999"}
        )
        check(
            "「見つからない」は失敗ではない（isError にしない）",
            not_found["isError"] is False and payload_of(not_found)["found"] is False,
            text_of(not_found),
        )

        health = client.call_tool("check_service_health", {})
        health_payload = payload_of(health)
        check(
            "targets を省略すると3系統すべてを確認する",
            health_payload["checked"] == 3,
            health_payload,
        )
        check(
            "1系統が失敗しても成功分と失敗分を分けて返す（isError にしない）",
            health["isError"] is False
            and len(health_payload["ok"]) == 2
            and len(health_payload["failed"]) == 1
            and health_payload["partial"] is True,
            health_payload,
        )
        null_targets = client.call_tool("check_service_health", {"targets": None})
        check(
            "null を渡されても既定に落として動く",
            payload_of(null_targets)["checked"] == 3,
        )
        bad_target = client.call_tool(
            "check_service_health", {"targets": ["vpn", "nas"]}
        )
        check(
            "配列の要素も候補で検証する",
            bad_target["isError"] is True and "要素に使えるのは" in text_of(bad_target),
            text_of(bad_target),
        )

        # ------------------------------------------------------------------
        section("4. 応答が返らないときに固まらない")
        started = time.monotonic()
        timed_out = False
        try:
            client.call_tool(
                "run_maintenance_scan", {"duration_ms": 1200}, timeout=0.3
            )
        except mcp_client.MCPTimeout:
            timed_out = True
        elapsed = time.monotonic() - started
        check("0.3秒のタイムアウトで打ち切られる", timed_out and elapsed < 1.0, elapsed)
        desynced = False
        try:
            client.list_tools()
        except mcp_client.MCPDesynced:
            desynced = True
        check("打ち切った接続は使い回さない（取りこぼした応答が残る）", desynced)
        client.restart()
        tools = client.list_tools()
        check("接続を作り直せば復帰する", len(tools) == 5, len(tools))
        executor = mcp_agent.make_executor(client)

        # ------------------------------------------------------------------
        section("5. ツール定義の書き方が「選ばれ方」を変える")
        vague = mcp_agent.run_agent(
            runtime,
            QUESTION,
            tool_config=mcp_client.to_tool_config([mcp_agent.VAGUE_TOOL]),
            executor=executor,
        )
        check(
            "曖昧な説明文（helper）だと道具が呼ばれない",
            vague["tool_calls"] == [] and vague["stop_reason"] == "end_turn",
            vague,
        )
        check(
            "道具を呼ばないと規程どおりの数値が出ない（作り話になる）",
            GROUND_TRUTH not in vague["answer"],
            vague["answer"],
        )

        good = mcp_agent.run_agent(
            runtime,
            QUESTION,
            tool_config=mcp_client.to_tool_config(
                tools, names=["search_internal_docs"]
            ),
            executor=executor,
        )
        check(
            "質問の語彙に合わせた説明文なら検索が呼ばれる",
            first_tool(good) == "search_internal_docs",
            good["tool_calls"],
        )
        check(
            "検索を1回呼んで規程どおりの上限を答える",
            len(good["tool_calls"]) == 1
            and good["model_calls"] == 2
            and GROUND_TRUTH in good["answer"],
            {"calls": good["tool_calls"], "answer": good["answer"]},
        )

        two_tools = ["search_internal_docs", "lookup_expense_report"]
        sloppy = mcp_agent.run_agent(
            runtime,
            QUESTION,
            tool_config=mcp_client.to_tool_config(
                mcp_agent.with_description(
                    tools, "lookup_expense_report", mcp_agent.SLOPPY_LOOKUP_DESCRIPTION
                ),
                names=two_tools,
            ),
            executor=executor,
        )
        check(
            "責務が重なる説明文だと誤った道具が先に呼ばれる",
            first_tool(sloppy) == "lookup_expense_report",
            sloppy["tool_calls"],
        )
        check(
            "誤った呼び出しは引数検証で弾かれ、往復が1回増える",
            sloppy["tool_calls"][0]["is_error"] is True
            and len(sloppy["tool_calls"]) == 2
            and sloppy["model_calls"] == 3,
            {"calls": sloppy["tool_calls"], "model_calls": sloppy["model_calls"]},
        )
        check(
            "混ざったエラー文のせいで次の検索語まで質問から外れる",
            sloppy["tool_calls"][1]["input"]["query"] != "宿泊費",
            sloppy["tool_calls"][1]["input"],
        )

        fixed = mcp_agent.run_agent(
            runtime,
            QUESTION,
            tool_config=mcp_client.to_tool_config(tools, names=two_tools),
            executor=executor,
        )
        check(
            "責務を分けた説明文なら2本あっても検索が選ばれる",
            first_tool(fixed) == "search_internal_docs"
            and len(fixed["tool_calls"]) == 1
            and fixed["model_calls"] == 2,
            fixed["tool_calls"],
        )
        check(
            "説明文を直しただけで往復が3回から2回に減る",
            sloppy["model_calls"] - fixed["model_calls"] == 1,
            (sloppy["model_calls"], fixed["model_calls"]),
        )
        check(
            "責務を分けた側は規程どおりの上限を答える",
            GROUND_TRUTH in fixed["answer"],
            fixed["answer"],
        )

        # ------------------------------------------------------------------
        section("6. 引数の手当てと復帰")
        strict = mcp_agent.run_agent(
            runtime,
            QUESTION,
            tool_config=mcp_client.to_tool_config(
                tools, names=["search_internal_docs"]
            ),
            executor=executor,
            repair=False,
        )
        check(
            "手当てしないと、任意引数の誤り（category）だけで検索が失敗する",
            strict["tool_calls"][0]["is_error"] is True
            and strict["tool_calls"][0]["input"].get("category") == "宿泊費",
            strict["tool_calls"],
        )
        check(
            "失敗した1回で会話が終わり、根拠のない回答になる",
            GROUND_TRUTH not in strict["answer"],
            strict["answer"],
        )
        # good（section 5）が repair=True の側。同じ入力・同じ道具で結果を比べる
        check(
            "任意引数を落として実行すれば、同じ質問に根拠付きで答えられる",
            good["tool_calls"][0]["is_error"] is False
            and GROUND_TRUTH in good["answer"],
            good["tool_calls"],
        )
        check(
            "手当てした内容は記録に残す（黙って直さない）",
            any("category" in note for note in good["tool_calls"][0]["notes"]),
            good["tool_calls"][0]["notes"],
        )
        repaired_args, notes = mcp_agent.repair_arguments(
            search_schema, {"query": "宿泊費", "category": "宿泊費", "top_k": 9}
        )
        check(
            "必須引数は触らず、候補外の任意引数と余計な引数だけを落とす",
            repaired_args == {"query": "宿泊費"} and len(notes) == 2,
            (repaired_args, notes),
        )
        kept, _ = mcp_agent.repair_arguments(search_schema, {"query": None})
        check("必須引数の誤りは手当てしない（サーバーに指摘させる）", kept == {"query": None})

        # ------------------------------------------------------------------
        section("7. 単一エージェントと監督役＋専門役")
        single = squad.run_single(runtime, tools, QUESTION, executor=executor)
        team = squad.run_squad(runtime, tools, QUESTION, executor=executor)
        check(
            "単一エージェントには読み取り系4本が見えている",
            len(single["exposed_tools"]) == 4,
            single["exposed_tools"],
        )
        check("監督役は経費の専門役に割り当てる", team["role"] == "expense_agent", team["role"])
        check(
            "専門役に見せる道具は2本だけ（誤選択の余地を減らす）",
            len(team["exposed_tools"]) == 2
            and "check_service_health" not in team["exposed_tools"],
            team["exposed_tools"],
        )
        check(
            "どちらの編成でも規程どおりの上限を答える",
            GROUND_TRUTH in single["answer"] and GROUND_TRUTH in team["answer"],
            {"single": single["answer"], "squad": team["answer"]},
        )
        check(
            "VPN の問い合わせは IT の専門役へ",
            squad.route("VPNに接続できません。どうすればよいですか？") == "it_agent",
        )
        check(
            "有給休暇の問い合わせは人事の専門役へ",
            squad.route("有給休暇の繰越上限は何日ですか？") == "hr_agent",
        )
        escalated = squad.run_squad(
            runtime, tools, "来期の売上予測を出してください", executor=executor
        )
        check(
            "担当が無い問い合わせは回答を作らず人へ引き継ぐ（モデルを呼ばない）",
            escalated["escalated"] is True and escalated["model_calls"] == 0,
            escalated,
        )
        check(
            "書き込みの専門役はチャットの経路からは呼ばれない",
            "it_write_agent" not in squad.CHAT_ROLES
            and "reset_user_password" not in squad.SINGLE_AGENT_TOOLS,
        )

        # ------------------------------------------------------------------
        section("8. 人の承認を挟むゲート（Human-in-the-loop）")
        sqs, ddb, queue_url = approval.ensure_infra()
        drain_queue(sqs, queue_url)
        for name, arguments in (RESET_ACTION, DENIED_ACTION):
            ddb.delete_item(
                TableName=approval.TABLE_NAME,
                Key={"approvalId": {"S": approval.approval_id(name, arguments)}},
            )
        gated = approval.gated_executor(client, infra=(sqs, ddb, queue_url))

        passthrough = gated("search_internal_docs", {"query": KB_QUERY})
        check("読み取り系は承認なしで通る", passthrough["isError"] is False)

        name, arguments = RESET_ACTION
        aid = approval.approval_id(name, arguments)
        blocked = gated(name, arguments)
        check(
            "書き込み系は初回で止まり、承認IDを返す",
            blocked["isError"] is True and aid in text_of(blocked),
            text_of(blocked),
        )
        requests = drain_queue(sqs, queue_url)
        check(
            "審査キューに依頼が1件だけ届く",
            len(requests) == 1 and requests[0]["approvalId"] == aid,
            requests,
        )
        again = gated(name, arguments)
        check(
            "審査中は何度呼ばれても実行しない",
            again["isError"] is True and "審査中" in text_of(again),
            text_of(again),
        )
        record = approval.decide(
            aid, decision="APPROVED", reviewer="admin@example.com", comment="本人確認済み"
        )
        check(
            "決裁が誰の判断として記録される",
            record["status"] == "APPROVED" and record["reviewer"] == "admin@example.com",
            record,
        )
        executed = gated(name, arguments)
        check(
            "承認後は実行される",
            executed["isError"] is False and "初期化しました" in text_of(executed),
            text_of(executed),
        )
        replayed = gated(name, arguments)
        check(
            "同じ承認IDで2回目は実行できない（冪等）",
            replayed["isError"] is True and "使用済み" in text_of(replayed),
            text_of(replayed),
        )

        denied_name, denied_arguments = DENIED_ACTION
        gated(denied_name, denied_arguments)
        denied_id = approval.approval_id(denied_name, denied_arguments)
        approval.decide(
            denied_id,
            decision="DENIED",
            reviewer="admin@example.com",
            comment="対象者の在籍が確認できない",
        )
        denied = gated(denied_name, denied_arguments)
        check(
            "却下された操作は実行されない",
            denied["isError"] is True and "却下" in text_of(denied),
            text_of(denied),
        )
        check(
            "承認IDは引数の書き順に依存しない（同じ操作なら同じ ID）",
            approval.approval_id("reset_user_password", {"employee_id": "EMP-0042"})
            == aid,
        )
        drain_queue(sqs, queue_url)
    finally:
        # ここを忘れると MCP サーバーのプロセスが残り、後続の検証に影響する
        client.close()

    print()
    if FAILURES:
        print(f"NG: {len(FAILURES)} 件の検証に失敗しました -> {FAILURES}")
        return 1
    print("セッション8の検証に成功しました（課金は一切発生していません）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
