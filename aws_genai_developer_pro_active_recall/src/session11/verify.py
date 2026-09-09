#!/usr/bin/env python3
"""セッション11の検証。

    docker compose exec app python src/session11/verify.py

**期待値と一致しなければ非0で終了します。** 判定に使うのは決定的な性質だけです。

    * ポリシー通りに許可／拒否されるか（許可・拒否・理由・Sid）
    * 拒否されたとき、基盤モデル（FM）への呼び出しが1回も出ていないか
    * 上限を超えたら 429 で止まるか
    * 部門別の按分の合計が、請求側（`GET /_mock/usage`）の総額と一致するか
    * 監査ログに必須項目がそろい、本文が残っていないか

トークン数やコストの絶対値は system の長さで変わるため、合否条件にしていません
（「見積りと実測が一致する」「差分が 0」のような関係だけを見ます）。
"""

from __future__ import annotations

import copy
import json
import sys
import urllib.request
import uuid

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session01")
sys.path.insert(0, "/workspace/src/session02")
sys.path.insert(0, "/workspace/src/session06")
sys.path.insert(0, "/workspace/src/session11")

from awskit import clients  # noqa: E402

import authz  # noqa: E402
import chargeback  # noqa: E402
import event_integration  # noqa: E402
import gateway  # noqa: E402
import model_router  # noqa: E402
import pipeline_gates  # noqa: E402
import prompt_audit  # noqa: E402
import prompt_registry as registry  # noqa: E402

FAILURES: list[str] = []

# ゲートウェイを通したすべての要求（成功も拒否も）。監査ログとの突き合わせに使う
CALLS: list[dict] = []

NOVA_LITE = "amazon.nova-lite-v1:0"
NOVA_MICRO = "amazon.nova-micro-v1:0"
NOVA_PRO = "amazon.nova-pro-v1:0"
HAIKU = "anthropic.claude-3-5-haiku-20241022-v1:0"
SONNET = "anthropic.claude-sonnet-4-5-20250929-v1:0"

IT = "情報システム部"
FINANCE = "経理部"
HR = "人事部"

TICKETS = event_integration.TICKETS


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def mock_post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{clients.mock_base_url()}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read())


def usage() -> dict:
    return chargeback.mock_usage()


def calls_so_far() -> int:
    """基盤モデルへの呼び出し回数。拒否が「呼んでいない」ことの証拠に使う。"""
    return usage()["calls"]


def ask(gw, **request) -> dict:
    result = gw.handle(request)
    CALLS.append(result)
    return result


def raises_value_error(func, *args, **kwargs) -> bool:
    try:
        func(*args, **kwargs)
    except ValueError:
        return True
    return False


def raises_federation_error(claims: dict) -> bool:
    try:
        authz.resolve_identity(claims)
    except authz.FederationError:
        return True
    return False


def swap_models(primary: str, fallbacks: list[str], gw) -> None:
    """設定ストアだけを書き換えて読み直す。**呼び出し側のコードは変えない。**"""
    model_router.put_config(
        {**gateway.DEFAULT_MODEL_CONFIG, "primary": primary, "fallbacks": fallbacks}
    )
    gw.reload()


def set_limit(department: str, limit: int, gw) -> None:
    config = copy.deepcopy(gateway.DEFAULT_GATEWAY_CONFIG)
    config["departments"][department]["tokenLimit"] = limit
    gateway.put_gateway_config(config)
    gw.reload()


def main() -> int:
    # 前の演習の障害注入と会計が残っていると按分の突き合わせが狂うため必ずリセットする。
    # **これ以降 /_mock/reset は呼ばない**（呼ぶと請求側の総額が消える）
    mock_post("/_mock/reset", {})

    s3 = gateway.bootstrap()
    # 課金の窓を実行ごとに新しくする。上限も原簿もログストリームもこの窓で分かれるので、
    # 何度実行しても「使用量 0 から始まる」状態を再現できる
    window = f"verify-{uuid.uuid4().hex[:8]}"
    gw = gateway.GenAIGateway(window=window, stream=f"gateway/{window}")
    ddb = gateway.ensure_ledger()
    logs = gateway.logs()

    # ------------------------------------------------------------------
    section("1. ID フェデレーション（誰の要求かを決める）")
    principal = authz.resolve_identity(gateway.CLAIMS["it"])
    check("グループからロールが決まる", principal.role == "helpdesk-it", principal.role)
    check(
        "部門はロールのタグから決まる（自己申告の department を見ない）",
        principal.department == IT and gateway.CLAIMS["it"]["department"] == FINANCE,
        (principal.department, gateway.CLAIMS["it"]["department"]),
    )
    check(
        "監査に残すのは引き受けたロールの ARN",
        principal.arn.startswith("arn:aws:sts::") and "helpdesk-it" in principal.arn,
        principal.arn,
    )
    check("sub が無ければ落とす", raises_federation_error({"groups": ["helpdesk-it-users"]}))
    check("未知のグループは引き受けられない", raises_federation_error({"sub": "u-1", "groups": ["x"]}))
    check(
        "ロールが一意でなければ落とす（広い権限へ寄る事故を防ぐ）",
        raises_federation_error(
            {"sub": "u-1", "groups": ["helpdesk-it-users", "helpdesk-hr-users"]}
        ),
    )

    # ------------------------------------------------------------------
    section("2. ポリシー評価（明示的 Deny > Allow > 暗黙的 Deny）")
    for role, model_id, expected in authz.EXPECTED_MATRIX:
        decision = authz.can_invoke(authz.principal_for_role(role), model_id)
        check(
            f"{authz.ROLE_TAGS[role]['department']} -> {model_id} = "
            f"{'許可' if expected else '拒否'}",
            decision.allowed == expected,
            decision.describe(),
        )

    it = authz.principal_for_role("helpdesk-it", subject="u-1043")
    finance = authz.principal_for_role("helpdesk-finance", subject="u-2071")
    hr = authz.principal_for_role("helpdesk-hr", subject="u-2210")

    sonnet_decision = authz.can_invoke(it, SONNET)
    check(
        "高額モデルは明示的な Deny で止まる",
        sonnet_decision.reason == "explicit_deny"
        and sonnet_decision.sid == "DenyExpensiveModels",
        sonnet_decision.describe(),
    )
    check(
        "列挙に無いモデルは暗黙的な Deny（既定は拒否）",
        authz.can_invoke(it, NOVA_PRO).reason == "implicit_deny",
        authz.can_invoke(it, NOVA_PRO).describe(),
    )
    check(
        "ワイルドカードの Allow は nova 系すべてに当たる",
        authz.can_invoke(finance, NOVA_MICRO).sid == "AllowNovaFamily",
        authz.can_invoke(finance, NOVA_MICRO).describe(),
    )
    check(
        "ワイルドカードの Allow があっても Deny が勝つ",
        authz.can_invoke(finance, NOVA_PRO).reason == "explicit_deny"
        and authz.can_invoke(finance, NOVA_PRO).sid == "DenyOutsideBudget",
        authz.can_invoke(finance, NOVA_PRO).describe(),
    )
    check(
        "条件キー（aws:RequestedRegion）が合えば許可",
        authz.can_invoke(hr, NOVA_LITE, region="us-east-1").allowed,
    )
    check(
        "条件キーが合わなければ許可されない（データ所在の制約）",
        not authz.can_invoke(hr, NOVA_LITE, region="ap-northeast-1").allowed,
        authz.can_invoke(hr, NOVA_LITE, region="ap-northeast-1").describe(),
    )
    check(
        "Bool 条件（aws:SecureTransport）が false なら許可されない",
        not authz.evaluate(
            authz.POLICIES["helpdesk-it"],
            action="bedrock:InvokeModel",
            resource=authz.model_arn(NOVA_LITE),
            context=authz.request_context(it, secure_transport=False),
        ).allowed,
    )
    tampered = authz.Principal(
        subject="u-1043", role="helpdesk-it", tags={"department": "営業部"}
    )
    check(
        "タグが違う主体は ABAC の条件で落ちる",
        not authz.can_invoke(tampered, NOVA_LITE).allowed,
        authz.can_invoke(tampered, NOVA_LITE).describe(),
    )
    check(
        "アクション名の大文字小文字は区別しない（IAM と同じ）",
        authz.can_invoke(it, NOVA_LITE, action="bedrock:converse").allowed,
    )
    check(
        "許可していないアクションは通らない",
        not authz.can_invoke(it, NOVA_LITE, action="bedrock:CreateGuardrail").allowed,
    )

    # ------------------------------------------------------------------
    section("3. ゲートウェイの基本経路（1本の入口を通す）")
    approved_version, _, approved_checksum = registry.load_approved(
        s3, gateway.PROMPT_NAME
    )
    r1 = ask(gw, claims=gateway.CLAIMS["it"], question=gateway.QUESTION,
             context=gateway.CONTEXT)
    check("許可されて 200 が返る", r1["decision"] == "allow" and r1["httpStatus"] == 200,
          (r1["decision"], r1["httpStatus"], r1["reason"]))
    check("解決したモデルは設定の primary", r1["modelId"] == NOVA_LITE, r1["modelId"])
    check("部門はタグ由来（要求の自己申告に従わない）", r1["department"] == IT, r1["department"])
    check("許可した Statement の Sid が残る",
          r1["policySid"] == "AllowStandardHelpdeskModels", r1["policySid"])
    check("承認済みの版で答えている",
          r1["promptVersion"] == approved_version
          and r1["promptChecksum"] == approved_checksum,
          (r1["promptVersion"], approved_version))
    check("呼ぶ前の見積りと実測の入力トークンが一致する",
          r1["estimatedInputTokens"] == r1["inputTokens"],
          (r1["estimatedInputTokens"], r1["inputTokens"]))
    check("出力トークンが計上されている", r1["outputTokens"] > 0, r1["outputTokens"])
    check("資料を根拠に答えている", registry.GROUNDING_MARKER in (r1["text"] or ""),
          (r1["text"] or "")[:40])
    check("最後の試行が成功で終わっている", r1["attempts"][-1]["outcome"] == "ok",
          r1["attempts"])

    # ------------------------------------------------------------------
    section("4. モデルの差し替え（呼び出し側のコードを変えない）")
    swap_models(HAIKU, [NOVA_LITE], gw)
    r2 = ask(gw, claims=gateway.CLAIMS["it"], question=gateway.QUESTION,
             context=gateway.CONTEXT)
    check("設定を書き換えるだけで呼び先が変わる", r2["modelId"] == HAIKU, r2["modelId"])
    check("呼び出し側の引数は1文字も変えていない", r2["decision"] == "allow", r2["reason"])

    r3 = ask(gw, claims=gateway.CLAIMS["finance"], question=gateway.QUESTION,
             context=gateway.CONTEXT)
    check("権限の無い primary は候補から外れ、次の候補に解決される",
          r3["decision"] == "allow" and r3["modelId"] == NOVA_LITE,
          (r3["decision"], r3["modelId"]))
    check("外れた理由が試行の記録に残る",
          any(a["modelId"] == HAIKU and a["outcome"] == "explicit_deny"
              for a in r3["attempts"]),
          r3["attempts"])

    swap_models(SONNET, [], gw)
    before = calls_so_far()
    r4 = ask(gw, claims=gateway.CLAIMS["it"], question=gateway.QUESTION,
             context=gateway.CONTEXT)
    check("認可済みの候補が無ければ 403",
          r4["decision"] == "deny" and r4["httpStatus"] == 403
          and r4["reason"] == "no_authorized_model",
          (r4["decision"], r4["httpStatus"], r4["reason"]))
    check("拒否された要求は基盤モデルを1回も呼んでいない", calls_so_far() == before,
          (before, calls_so_far()))
    check("拒否行にモデル ID は入らない", r4["modelId"] is None, r4["modelId"])

    swap_models(NOVA_LITE, [NOVA_MICRO], gw)
    before = calls_so_far()
    r5 = ask(gw, claims=gateway.CLAIMS["hr"], question=gateway.QUESTION,
             context=gateway.CONTEXT, region="ap-northeast-1")
    check("データ所在の条件に反する要求も入口で止まる",
          r5["httpStatus"] == 403 and r5["reason"] == "no_authorized_model",
          (r5["httpStatus"], r5["reason"]))
    check("条件で止めた要求も基盤モデルを呼んでいない", calls_so_far() == before)

    # ------------------------------------------------------------------
    section("5. 部門別トークン上限（超えたら拒否する）")
    used_it = gateway.used_tokens(ddb, IT, window)
    check("成功した呼び出しが原簿に積まれている", used_it > 0, used_it)

    set_limit(IT, used_it, gw)
    before = calls_so_far()
    r6 = ask(gw, claims=gateway.CLAIMS["it"], question=gateway.QUESTION,
             context=gateway.CONTEXT)
    check("使い切った部門は 429 で拒否される",
          r6["httpStatus"] == 429 and r6["reason"] == "quota_exceeded",
          (r6["httpStatus"], r6["reason"]))
    check("上限で拒否した要求は基盤モデルを呼んでいない", calls_so_far() == before)
    check("判断の材料（使用量・予約・上限）が記録に残る",
          r6["usedTokens"] == used_it and r6["reservedTokens"] > 0
          and r6["tokenLimit"] == used_it,
          (r6.get("usedTokens"), r6.get("reservedTokens"), r6.get("tokenLimit")))
    check("予約は見積り入力ぶんと出力上限の合計",
          r6["reservedTokens"] == r6["estimatedInputTokens"]
          + gateway.DEFAULT_GATEWAY_CONFIG["maxTokens"],
          (r6["reservedTokens"], r6["estimatedInputTokens"]))

    set_limit(IT, 10, gw)
    before = calls_so_far()
    r7 = ask(gw, claims=gateway.CLAIMS["it"], question=gateway.QUESTION,
             context=gateway.CONTEXT)
    check("上限が予約より小さければ、1回目から拒否される",
          r7["httpStatus"] == 429 and r7["reason"] == "quota_exceeded",
          (r7["httpStatus"], r7["reason"]))
    check("枠が無い部門は基盤モデルに到達しない", calls_so_far() == before)
    check("他部門の枠には影響しない",
          gw.reload()["gateway"]["departments"][FINANCE]["tokenLimit"] == 1_000_000)

    gateway.put_gateway_config(gateway.DEFAULT_GATEWAY_CONFIG)
    gw.reload()

    check("壊れた設定は配布前に弾かれる（未知のロール）",
          raises_value_error(
              gateway.validate_gateway_config,
              {"promptName": "x", "maxTokens": 10,
               "departments": {"営業部": {"role": "nope", "tokenLimit": 1,
                                          "costCenter": "CC-9"}}}))
    check("壊れた設定は配布前に弾かれる（上限が 0）",
          raises_value_error(
              gateway.validate_gateway_config,
              {"promptName": "x", "maxTokens": 10,
               "departments": {IT: {"role": "helpdesk-it", "tokenLimit": 0,
                                    "costCenter": "CC-1001"}}}))
    check("壊れた設定は配布前に弾かれる（按分先が無い）",
          raises_value_error(
              gateway.validate_gateway_config,
              {"promptName": "x", "maxTokens": 10,
               "departments": {IT: {"role": "helpdesk-it", "tokenLimit": 10}}}))

    # ------------------------------------------------------------------
    section("6. 冪等（同じ要求を2回処理しない）")
    r8 = ask(gw, claims=gateway.CLAIMS["hr"], question=gateway.QUESTION,
             context=gateway.CONTEXT, requestId="req-hr-dup")
    check("1回目は通常どおり処理される", r8["decision"] == "allow", r8["reason"])
    before = calls_so_far()
    r9 = ask(gw, claims=gateway.CLAIMS["hr"], question=gateway.QUESTION,
             context=gateway.CONTEXT, requestId="req-hr-dup")
    check("2回目は duplicate として返る", r9["decision"] == "duplicate", r9["decision"])
    check("2回目は基盤モデルを呼び直さない", calls_so_far() == before)
    check("2回目は原簿に二重計上されない", r9["inputTokens"] == 0 and r9["outputTokens"] == 0)

    # ------------------------------------------------------------------
    section("7. イベント駆動の統合（EventBridge → SQS → ゲートウェイ）")
    pipeline = event_integration.ensure_pipeline()
    check("キューとルールがそろっている",
          pipeline["queueArn"].endswith(event_integration.QUEUE_NAME)
          and event_integration.RULE_NAME in pipeline["ruleArn"],
          (pipeline["queueArn"], pipeline["ruleArn"]))
    sqs = clients.aws("sqs")
    attributes = sqs.get_queue_attributes(
        QueueUrl=pipeline["queueUrl"], AttributeNames=["Policy", "RedrivePolicy"]
    )["Attributes"]
    check("送り手を名指しで許可するポリシーが付いている",
          "events.amazonaws.com" in attributes.get("Policy", ""))
    check("失敗の行き先（DLQ）が設定されている",
          event_integration.DLQ_NAME in attributes.get("RedrivePolicy", ""),
          attributes.get("RedrivePolicy"))
    event_integration.drain(pipeline["queueUrl"], sqs=sqs)

    event_integration.publish(TICKETS)
    # パターンに合わないイベントは配信されない（取ってから捨てるのではなく入口で絞る）
    clients.aws("events").put_events(
        Entries=[{
            "Source": event_integration.EVENT_SOURCE,
            "DetailType": "TicketClosed",
            "EventBusName": event_integration.BUS_NAME,
            "Detail": json.dumps({"ticketId": "T-8899"}),
        }]
    )
    messages = event_integration.receive(
        pipeline["queueUrl"], expected=len(TICKETS), timeout=45.0, sqs=sqs
    )
    wanted = {t["ticketId"] for t in TICKETS}
    selected: list[dict] = []
    seen: set[str] = set()
    stray = 0
    for message in messages:
        envelope = json.loads(message["Body"])
        detail = envelope.get("detail", envelope)
        ticket_id = detail.get("ticketId")
        if ticket_id in wanted and ticket_id not in seen:
            seen.add(ticket_id)
            selected.append(message)
        elif ticket_id == "T-8899":
            stray += 1
    check("ルールに合致した票だけが届く", seen == wanted, sorted(seen))
    check("パターン外のイベントは届かない（入口で絞られる）", stray == 0, stray)

    results = event_integration.process(gw, selected, queue_url=pipeline["queueUrl"], sqs=sqs)
    CALLS.extend(results)
    check("イベント経由でも同じゲートウェイを通る",
          all(r["decision"] == "allow" for r in results),
          [(r["requestId"], r["decision"], r["reason"]) for r in results])
    check("イベント経由でも部門はタグ由来で決まる",
          {r["department"] for r in results} == {IT, FINANCE},
          {r["department"] for r in results})
    check("票の ID がそのまま requestId になる",
          {r["requestId"] for r in results} == wanted,
          {r["requestId"] for r in results})

    # ------------------------------------------------------------------
    section("8. 部門別のコスト按分（合計が請求側と一致するか）")
    config = gateway.load_gateway_config()
    report = chargeback.report(ddb, config, window)
    billing = usage()
    diff = chargeback.reconcile(report, billing)

    allowed_calls = sum(1 for c in CALLS if c["decision"] == "allow")
    check("成功した要求の数と基盤モデルの呼び出し回数が一致する",
          billing["calls"] == allowed_calls, (billing["calls"], allowed_calls))
    check("按分の呼び出し数が請求側と一致する", diff["callsDiff"] == 0, diff["callsDiff"])
    check("按分の入力トークンが請求側と一致する", diff["inputTokensDiff"] == 0,
          diff["inputTokensDiff"])
    check("按分の出力トークンが請求側と一致する", diff["outputTokensDiff"] == 0,
          diff["outputTokensDiff"])
    check("按分の金額が請求側と一致する（丸めは表示のときだけ）",
          abs(diff["usdDiff"]) < 1e-9, diff["usdDiff"])
    check("モックの推定総額とも一致する",
          abs(round(report["total"]["estimatedUsd"], 6)
              - billing["estimatedUsdTotal"]) < 1e-5,
          (report["total"]["estimatedUsd"], billing["estimatedUsdTotal"]))

    by_department = {row["department"]: row for row in report["departments"]}
    check("按分率の合計が 100% になる（端数の範囲内）",
          abs(sum(row["sharePct"] for row in report["departments"]) - 100.0) < 0.05,
          [row["sharePct"] for row in report["departments"]])
    check("差し替えた履歴がモデル別の明細に残る",
          {r["modelId"] for r in by_department[IT]["perModel"]} == {NOVA_LITE, HAIKU},
          [r["modelId"] for r in by_department[IT]["perModel"]])
    check("経理部の明細は許可されたモデルだけ",
          {r["modelId"] for r in by_department[FINANCE]["perModel"]} == {NOVA_LITE},
          [r["modelId"] for r in by_department[FINANCE]["perModel"]])
    check("按分先（コストセンター）が全部門にそろっている",
          all(row["costCenter"] for row in report["departments"]))
    check("全部門に使用実績がある（拒否だけの部門が無い）",
          all(row["calls"] > 0 for row in report["departments"]),
          {k: v["calls"] for k, v in by_department.items()})

    # ------------------------------------------------------------------
    section("9. 監査ログ（誰が・どの版で・どのモデルを・何トークン）")
    entries = gateway.read_audit(logs, gw.stream)
    check("成功も拒否も1行ずつ残る",
          sorted((e["requestId"], e["decision"]) for e in entries)
          == sorted((c["requestId"], c["decision"]) for c in CALLS),
          (len(entries), len(CALLS)))
    required = tuple(prompt_audit.REQUIRED_FIELDS) + gateway.GATEWAY_FIELDS
    missing = [f for e in entries for f in required if f not in e]
    check("すべての行に必須項目がそろう（セッション6の契約を満たす）", missing == [],
          sorted(set(missing)))
    allow_entries = [e for e in entries if e["decision"] == "allow"]
    deny_entries = [e for e in entries if e["decision"] == "deny"]
    check("拒否の行も残っている（呼ばなかった記録はここにしか無い）",
          len(deny_entries) > 0, len(deny_entries))
    check("拒否の行はモデル ID とトークンが空",
          all(e["modelId"] is None and e["inputTokens"] == 0 for e in deny_entries))
    check("成功の行は誰が・どの版で・どのモデルを・何トークンが埋まっている",
          all(e["principal"] and e["department"] and e["modelId"]
              and e["promptVersion"] == approved_version
              and e["promptChecksum"] == approved_checksum
              and e["inputTokens"] > 0 and e["outputTokens"] > 0
              for e in allow_entries),
          [(e["requestId"], e["modelId"]) for e in allow_entries])
    check("すべての行に要求元のリージョンが残る",
          all(e["requestedRegion"] for e in entries))
    serialized = json.dumps(entries, ensure_ascii=False)
    check("プロンプト本文・質問・回答は残さない",
          gateway.QUESTION not in serialized
          and registry.GROUNDING_MARKER not in serialized
          and "あなたはサンプル商事" not in serialized)

    # ------------------------------------------------------------------
    section("10. パイプラインのゲート（CI に置くテストと走査）")
    check("プロンプト回帰のゲートが通る",
          pipeline_gates.gate_prompt_regression(s3, gateway.PROMPT_NAME) == [],
          pipeline_gates.gate_prompt_regression(s3, gateway.PROMPT_NAME))
    check("認可マトリクスのゲートが通る", pipeline_gates.gate_authz_matrix() == [],
          pipeline_gates.gate_authz_matrix())
    check("シークレット走査は正常な設定を誤検知しない",
          pipeline_gates.gate_secret_scan(
              [f"primary = {NOVA_LITE}", "promptName = helpdesk-answer"]) == [])
    check("シークレット走査は直書きの資格情報を捕まえる",
          pipeline_gates.gate_secret_scan(["api_key = DUMMY-NOT-A-REAL-KEY-0000"]) != [])
    check("監査ログの本文混入ゲートが通る",
          pipeline_gates.gate_audit_no_payload(
              entries, [gateway.QUESTION, registry.GROUNDING_MARKER]) == [])
    check("本文が混ざれば同じゲートが赤くなる",
          pipeline_gates.gate_audit_no_payload(
              [{"answer": f"{registry.GROUNDING_MARKER}20日です。"}],
              [registry.GROUNDING_MARKER]) != [])

    # 権限をうっかり広げたときにゲートが気づけるかを確かめる
    hr_statements = authz.POLICIES["helpdesk-hr"]["Statement"]
    hr_statements.append({
        "Sid": "OopsWidened",
        "Effect": "Allow",
        "Action": "bedrock:*",
        "Resource": authz.model_arn(NOVA_MICRO),
    })
    check("権限を広げるとゲートが赤くなる", pipeline_gates.gate_authz_matrix() != [])
    hr_statements.pop()
    check("元に戻すとゲートは緑に戻る", pipeline_gates.gate_authz_matrix() == [])

    # ------------------------------------------------------------------
    # 後片付け。設定ストアを既定に戻す（次の章の検証が既定値を前提にするため）
    model_router.put_config(model_router.DEFAULT_CONFIG)
    gateway.put_gateway_config(gateway.DEFAULT_GATEWAY_CONFIG)

    print()
    if FAILURES:
        print(f"NG: {len(FAILURES)} 件の検証に失敗しました -> {FAILURES}")
        return 1
    print("セッション11の検証に成功しました（課金は一切発生していません）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
