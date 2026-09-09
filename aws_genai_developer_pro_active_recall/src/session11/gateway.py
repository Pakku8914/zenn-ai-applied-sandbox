#!/usr/bin/env python3
"""セッション11: GenAI ゲートウェイ（生成AI呼び出しの中央集約層）。

    docker compose exec app python src/session11/gateway.py

**この1本を通らないと基盤モデル（FM）を呼べない**という状態を作ります。
ゲートウェイが引き受ける仕事は4つです。

    1. 誰が呼んでいるか（ID フェデレーション → ロール → 部門）
    2. その部門はそのモデルを呼べるか（最小権限。`authz.py`）
    3. その部門はまだ枠が残っているか（部門別トークン上限。超えたら 429）
    4. 誰が・どの版のプロンプトで・どのモデルを・何トークン使ったか（監査と按分）

**実務ではこの層を HTTP で公開します。** 入口は Amazon API Gateway、
実体は AWS Lambda（低頻度・突発トラフィック）か Amazon ECS / AWS Fargate
（常時トラフィック・長い接続・ストリーミング）に載せます。このサンドボックスには
API Gateway も Lambda もないため、**同じ責務を Python のクラスとして**書きます。
呼び出し側から見た形（1つの入口・拒否は例外ではなく応答）は同じです。

前のセッションの成果物はそのまま使います。

    セッション2 `model_router` … 設定レイヤ（SSM）・FATAL_CODES・CircuitBreaker
    セッション6 `prompt_registry` … 承認済みの版だけを読む（load_approved）
    セッション6 `prompt_audit`   … 監査記録の必須項目（REQUIRED_FIELDS）
"""

from __future__ import annotations

import json
import math
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session01")
sys.path.insert(0, "/workspace/src/session02")
sys.path.insert(0, "/workspace/src/session06")
sys.path.insert(0, "/workspace/src/session11")

from botocore.exceptions import ClientError  # noqa: E402

from awskit import clients  # noqa: E402
from bedrock_mock import catalog  # noqa: E402

import authz  # noqa: E402
import model_router  # noqa: E402  セッション2
import prompt_audit  # noqa: E402  セッション6
import prompt_registry as registry  # noqa: E402  セッション6

# 設定の置き場。実務では AWS AppConfig（版管理・段階デプロイ・即時ロールバック付き）。
# LocalStack Community は AppConfig 非対応なので SSM パラメータストアで代替する
GATEWAY_CONFIG_PARAM = "/sample-shoji/helpdesk/gateway-config"

# 監査ログ。**拒否した要求もここに残る**（呼ばなかった記録が要るのはここだけ）
AUDIT_GROUP = "/sample-shoji/helpdesk/gateway-audit"

# 計上の原簿。部門 × モデルのトークンを原子的に積み上げる
LEDGER_TABLE = "aip_c01_usage_ledger"

# 二重処理を防ぐ番号札を同じ表に置く（単一テーブル設計）
DEDUP_PARTITION = "#dedup"

PROMPT_NAME = "helpdesk-answer"
MAX_SENTENCES = 3
DEFAULT_MAX_TOKENS = 300

# セッション6の必須項目に、ゲートウェイ層だけが答えられる欄を足す
GATEWAY_FIELDS = (
    "requestId",
    "principal",
    "department",
    "decision",
    "reason",
    "httpStatus",
    "requestedRegion",
    "estimatedUsd",
    "estimatedInputTokens",
)

DEFAULT_GATEWAY_CONFIG: dict = {
    "promptName": PROMPT_NAME,
    "maxTokens": DEFAULT_MAX_TOKENS,
    "departments": {
        "情報システム部": {
            "role": "helpdesk-it",
            "tokenLimit": 1_000_000,
            "costCenter": "CC-1001",
        },
        "経理部": {
            "role": "helpdesk-finance",
            "tokenLimit": 1_000_000,
            "costCenter": "CC-2002",
        },
        "人事部": {
            "role": "helpdesk-hr",
            "tokenLimit": 1_000_000,
            "costCenter": "CC-3003",
        },
    },
}

# ゲートウェイが使うモデルの並び。**アプリのコードにモデル ID を書かない**
DEFAULT_MODEL_CONFIG: dict = {
    **model_router.DEFAULT_CONFIG,
    "primary": "amazon.nova-lite-v1:0",
    "fallbacks": ["amazon.nova-micro-v1:0"],
}

_SSM = None
_LOGS = None
_DDB = None


# ---------------------------------------------------------------------------
# 小道具
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def current_window() -> str:
    """課金の窓（請求月）。上限も按分もこの単位で数える。"""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def estimate_tokens(text: str) -> int:
    """**呼ぶ前に**入力トークン数を見積もる。

    モックのトークン規則（ASCII は4文字＝1トークン、非ASCII は1文字＝1トークン）と
    同じ計算をします。実 AWS ではモデルごとのトークナイザが違うため完全一致はしませんが、
    上限判定は「見積もり ＋ 出力の上限」で予約する設計にしておけば、
    見積もりが多少ずれても枠を突破されません。
    """
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    wide_chars = len(text) - ascii_chars
    return wide_chars + math.ceil(ascii_chars / 4)


def ssm():
    global _SSM
    if _SSM is None:
        _SSM = clients.aws("ssm")
    return _SSM


def logs():
    global _LOGS
    if _LOGS is None:
        _LOGS = clients.aws("logs")
    return _LOGS


def ddb():
    global _DDB
    if _DDB is None:
        _DDB = clients.aws("dynamodb")
    return _DDB


def _ignore_exists(func, **kwargs) -> None:
    try:
        func(**kwargs)
    except ClientError as error:
        code = error.response["Error"]["Code"]
        if code not in ("ResourceAlreadyExistsException", "ResourceInUseException"):
            raise


# ---------------------------------------------------------------------------
# 設定（部門・上限・按分先）
# ---------------------------------------------------------------------------


def validate_gateway_config(config: dict) -> dict:
    """配布する前に検査する。**壊れた設定を配ると全部門が止まります。**"""
    departments = config.get("departments")
    if not isinstance(departments, dict) or not departments:
        raise ValueError("departments が空です")
    for name, tenant in departments.items():
        role = tenant.get("role")
        if role not in authz.POLICIES:
            raise ValueError(f"{name}: ポリシーの無いロールです: {role!r}")
        limit = tenant.get("tokenLimit")
        if not isinstance(limit, int) or limit <= 0:
            raise ValueError(f"{name}: tokenLimit が正の整数ではありません: {limit!r}")
        if not tenant.get("costCenter"):
            raise ValueError(f"{name}: costCenter がありません（按分先が決まりません）")
    if int(config.get("maxTokens", 0)) <= 0:
        raise ValueError("maxTokens が正の整数ではありません")
    if not config.get("promptName"):
        raise ValueError("promptName がありません")
    return config


def put_gateway_config(config: dict, *, validate: bool = True) -> None:
    if validate:
        validate_gateway_config(config)
    ssm().put_parameter(
        Name=GATEWAY_CONFIG_PARAM,
        Value=json.dumps(config, ensure_ascii=False),
        Type="String",
        Overwrite=True,
    )


def load_gateway_config() -> dict:
    """設定を読む。

    ここではキャッシュを持たず、読むたびに取りに行きます（差し替えが効く瞬間を
    観察したいため）。実運用ではセッション2の `load_config` と同じく
    **TTL キャッシュ ＋ 直前の正しい設定（last known good）** を付けます。
    設定ストアの障害がアプリ全体の障害になってはいけません。
    """
    raw = ssm().get_parameter(Name=GATEWAY_CONFIG_PARAM)["Parameter"]["Value"]
    return validate_gateway_config(json.loads(raw))


# ---------------------------------------------------------------------------
# 原簿（部門別の使用量）
# ---------------------------------------------------------------------------


def ensure_ledger(client=None):
    client = client or ddb()
    _ignore_exists(
        client.create_table,
        TableName=LEDGER_TABLE,
        KeySchema=[
            {"AttributeName": "department", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "department", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return client


def total_key(window: str) -> str:
    return f"{window}#TOTAL"


def model_key(window: str, model_id: str) -> str:
    return f"{window}#model#{model_id}"


# DynamoDB の予約語を避けるため、属性名は必ず別名で書く
_LEDGER_NAMES = {
    "#calls": "calls",
    "#in": "inputTokens",
    "#out": "outputTokens",
    "#tot": "totalTokens",
}


def used_tokens(client, department: str, window: str) -> int:
    """上限判定に使う合計。**1件の読み取りで済むよう合計行を別に持つ。**

    部門ごとの明細を毎回 Query して足すと、モデルが増えるほど1リクエストの
    コストが上がります。合計は書くときに作っておきます。
    """
    res = client.get_item(
        TableName=LEDGER_TABLE,
        Key={"department": {"S": department}, "sk": {"S": total_key(window)}},
        ConsistentRead=True,
    )
    item = res.get("Item")
    return int(item["totalTokens"]["N"]) if item else 0


def meter(
    client,
    *,
    department: str,
    window: str,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """計上する。`ADD` は原子的な加算なので、同時実行でも数え落ちません。"""
    total = input_tokens + output_tokens
    values = {
        ":one": {"N": "1"},
        ":i": {"N": str(input_tokens)},
        ":o": {"N": str(output_tokens)},
        ":t": {"N": str(total)},
    }
    for sk in (total_key(window), model_key(window, model_id)):
        client.update_item(
            TableName=LEDGER_TABLE,
            Key={"department": {"S": department}, "sk": {"S": sk}},
            UpdateExpression="ADD #calls :one, #in :i, #out :o, #tot :t",
            ExpressionAttributeNames=_LEDGER_NAMES,
            ExpressionAttributeValues=values,
        )


def claim_request(client, request_id: str, window: str) -> bool:
    """この要求を初めて処理するなら True。

    イベント駆動の統合では**同じイベントが2回届きます**（SQS は at-least-once）。
    番号札を条件付き書き込みで取り、取れなかったら呼ばずに返します。
    """
    try:
        client.put_item(
            TableName=LEDGER_TABLE,
            Item={
                "department": {"S": DEDUP_PARTITION},
                "sk": {"S": f"{window}#{request_id}"},
                "at": {"S": _now_iso()},
            },
            ConditionExpression="attribute_not_exists(sk)",
        )
        return True
    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


# ---------------------------------------------------------------------------
# 監査
# ---------------------------------------------------------------------------


def ensure_audit_stream(stream: str, client=None):
    client = client or logs()
    _ignore_exists(client.create_log_group, logGroupName=AUDIT_GROUP)
    _ignore_exists(
        client.create_log_stream, logGroupName=AUDIT_GROUP, logStreamName=stream
    )
    return client


def put_audit(client, stream: str, entry: dict) -> None:
    client.put_log_events(
        logGroupName=AUDIT_GROUP,
        logStreamName=stream,
        logEvents=[
            {
                "timestamp": int(time.time() * 1000),
                "message": json.dumps(entry, ensure_ascii=False),
            }
        ],
    )


def read_audit(client, stream: str) -> list[dict]:
    res = client.get_log_events(
        logGroupName=AUDIT_GROUP, logStreamName=stream, startFromHead=True
    )
    return [json.loads(event["message"]) for event in res["events"]]


def _blank_entry(request_id: str, region: str, conversation_id: str) -> dict:
    """すべての結末で同じ欄がそろう形にしておく。

    欄が結末ごとに違うと、後から「拒否だけ集計する」「部門別に足す」ができません。
    """
    return {
        "at": _now_iso(),
        "requestId": request_id,
        "principal": None,
        "department": None,
        "decision": "deny",
        "reason": "unknown",
        "httpStatus": 500,
        "requestedRegion": region,
        "policySid": None,
        "promptName": None,
        "promptVersion": None,
        "promptChecksum": None,
        "modelId": None,
        "conversationId": conversation_id,
        "inputTokens": 0,
        "outputTokens": 0,
        "cacheReadInputTokens": 0,
        "stopReason": None,
        "latencyMs": 0,
        "estimatedUsd": 0.0,
        "estimatedInputTokens": 0,
        "attempts": [],
    }


# ---------------------------------------------------------------------------
# ゲートウェイ本体
# ---------------------------------------------------------------------------


class GenAIGateway:
    """生成AI呼び出しの単一の入口。

    比喩でいえば会社の代表電話です。社員が取引先の携帯番号を個別に持っていると、
    誰が何を話したか分からず、担当替えのたびに全員の電話帳を直すことになります。
    番号を1つに集約すると、記録・取次・切り替えを1か所で変えられます。
    """

    def __init__(
        self,
        *,
        window: str | None = None,
        stream: str | None = None,
        s3=None,
        runtime=None,
        gateway_config: dict | None = None,
        model_config: dict | None = None,
    ) -> None:
        self.window = window or current_window()
        self.stream = stream or f"gateway/{self.window}"
        self._s3 = s3 if s3 is not None else registry.ensure_bucket()
        # 候補を順に試すのはゲートウェイ側の仕事なので、boto3 側の再試行は切る
        self._runtime = (
            runtime if runtime is not None else clients.bedrock_runtime(max_attempts=1)
        )
        self._ddb = ensure_ledger()
        self._logs = ensure_audit_stream(self.stream)
        self._breakers: dict[str, model_router.CircuitBreaker] = {}
        self._gateway_config = gateway_config
        self._model_config = model_config
        if gateway_config is None or model_config is None:
            self.reload()

    # -- 設定 --------------------------------------------------------------

    def reload(self) -> dict:
        """設定を読み直す。実務では AppConfig のポーリングで自動的に起きる。"""
        self._gateway_config = load_gateway_config()
        self._model_config = model_router.load_config(force=True)
        return {"gateway": self._gateway_config, "model": self._model_config}

    def model_chain(self) -> list[str]:
        cfg = self._model_config
        return [cfg["primary"], *(cfg.get("fallbacks") or [])]

    def _breaker(self, model_id: str) -> model_router.CircuitBreaker:
        if model_id not in self._breakers:
            settings = self._model_config.get("breaker") or {}
            self._breakers[model_id] = model_router.CircuitBreaker(
                failure_threshold=int(settings.get("failureThreshold", 2)),
                cooldown_seconds=float(settings.get("cooldownSeconds", 30)),
            )
        return self._breakers[model_id]

    # -- 呼び出し ----------------------------------------------------------

    def handle(self, request: dict) -> dict:
        """1件の要求を処理する。**呼び出し側が知るのはこのメソッドだけ。**"""
        request_id = request.get("requestId") or f"req-{uuid.uuid4().hex[:12]}"
        region = request.get("region") or authz.REGION
        entry = _blank_entry(
            request_id, region, request.get("conversationId") or request_id
        )

        # --- 1. 誰か（ID フェデレーション） ------------------------------
        try:
            principal = authz.resolve_identity(request.get("claims") or {})
        except authz.FederationError as exc:
            entry.update(reason=f"federation_error: {exc}", httpStatus=401)
            return self._emit(entry)
        entry.update(principal=principal.arn, department=principal.department)

        tenant = (self._gateway_config["departments"] or {}).get(principal.department)
        if tenant is None:
            entry.update(reason="department_not_onboarded", httpStatus=403)
            return self._emit(entry)
        if tenant["role"] != principal.role:
            # 設定とポリシーがずれた状態。黙って通すと按分先が壊れる
            entry.update(reason="role_mismatch", httpStatus=403)
            return self._emit(entry)

        # --- 2. 何を呼べるか（最小権限） ----------------------------------
        # **候補すべてを認可にかける。** 代替先だけ権限が抜けていると、
        # 障害が起きた瞬間に初めて 403 が出るという最悪の壊れ方をする
        allowed: list[tuple[str, authz.Decision]] = []
        for model_id in self.model_chain():
            decision = authz.can_invoke(principal, model_id, region=region)
            entry["attempts"].append(
                {
                    "modelId": model_id,
                    "outcome": "authorized" if decision.allowed else decision.reason,
                    "policySid": decision.sid,
                }
            )
            if decision.allowed:
                allowed.append((model_id, decision))
        if not allowed:
            entry.update(reason="no_authorized_model", httpStatus=403)
            return self._emit(entry)

        # --- 3. どの版のプロンプトか --------------------------------------
        prompt_name = self._gateway_config["promptName"]
        version, template, checksum = registry.load_approved(self._s3, prompt_name)
        entry.update(
            promptName=prompt_name, promptVersion=version, promptChecksum=checksum
        )
        params = {"department": principal.department, "max_sentences": MAX_SENTENCES}
        system_text = registry.render_system(template, params)[0]["text"]
        user_blocks = registry.render_user(
            request["question"], context_text=request.get("context")
        )
        max_tokens = int(self._gateway_config.get("maxTokens", DEFAULT_MAX_TOKENS))
        estimated_input = estimate_tokens(system_text + user_blocks[0]["text"])
        entry["estimatedInputTokens"] = estimated_input

        # --- 4. 枠が残っているか（予約 → 判定） ---------------------------
        limit = int(tenant["tokenLimit"])
        used = used_tokens(self._ddb, principal.department, self.window)
        reserved = estimated_input + max_tokens
        if used + reserved > limit:
            entry.update(
                reason="quota_exceeded",
                httpStatus=429,
                usedTokens=used,
                reservedTokens=reserved,
                tokenLimit=limit,
            )
            return self._emit(entry)

        # --- 5. 二重処理を防ぐ（冪等） ------------------------------------
        if not claim_request(self._ddb, request_id, self.window):
            entry.update(decision="duplicate", reason="duplicate_request", httpStatus=200)
            return self._emit(entry)

        # --- 6. 呼ぶ ------------------------------------------------------
        model_id, response = self._invoke(
            allowed, template, params, user_blocks, max_tokens, entry
        )
        if response is None:
            entry.update(decision="degraded", reason="all_models_failed", httpStatus=503)
            return self._emit(entry, text=self._model_config["degradedMessage"])

        usage = response["usage"]
        entry.update(
            decision="allow",
            reason="allow",
            httpStatus=200,
            modelId=model_id,
            inputTokens=usage["inputTokens"],
            outputTokens=usage["outputTokens"],
            cacheReadInputTokens=usage.get("cacheReadInputTokens", 0),
            stopReason=response["stopReason"],
            latencyMs=response["metrics"]["latencyMs"],
            estimatedUsd=catalog.cost_usd(
                model_id, usage["inputTokens"], usage["outputTokens"]
            ),
        )

        # --- 7. 計上（按分の原簿） ----------------------------------------
        meter(
            self._ddb,
            department=principal.department,
            window=self.window,
            model_id=model_id,
            input_tokens=usage["inputTokens"],
            output_tokens=usage["outputTokens"],
        )
        return self._emit(entry, text=registry.text_of(response))

    def _invoke(self, allowed, template, params, user_blocks, max_tokens, entry):
        """認可を通ったモデルを順に試す。切り替えの作法はセッション2と同じ。"""
        for model_id, decision in allowed:
            breaker = self._breaker(model_id)
            if not breaker.allow():
                entry["attempts"].append(
                    {"modelId": model_id, "outcome": "skipped_open"}
                )
                continue
            try:
                response = registry.call(
                    self._runtime,
                    template,
                    model_id=model_id,
                    messages=[{"role": "user", "content": user_blocks}],
                    params=params,
                    max_tokens=max_tokens,
                )
            except ClientError as exc:
                code = exc.response["Error"]["Code"]
                entry["attempts"].append({"modelId": model_id, "outcome": code})
                if code in model_router.FATAL_CODES:
                    raise
                breaker.on_failure()
                continue
            breaker.on_success()
            entry["policySid"] = decision.sid
            entry["attempts"].append({"modelId": model_id, "outcome": "ok"})
            return model_id, response
        return None, None

    def _emit(self, entry: dict, *, text: str | None = None) -> dict:
        """監査に1行残してから返す。**本文は監査に書かない。**

        質問と回答をログに書くと、機密や個人情報を別の場所へ増やすことになります。
        本文が必要なときは Model Invocation Logging（Bedrock 側の設定で
        Amazon S3 / Amazon CloudWatch Logs へ配信）を使います。
        """
        put_audit(self._logs, self.stream, entry)
        return {**entry, "text": text}


# ---------------------------------------------------------------------------
# 初期化と演習の本体
# ---------------------------------------------------------------------------


def bootstrap(*, gateway_config: dict | None = None, model_config: dict | None = None):
    """演習を何度実行しても同じ状態から始まるようにする。"""
    s3 = registry.ensure_bucket()
    for version in (1, 2):
        registry.publish(s3, PROMPT_NAME, version)
    registry.approve(s3, PROMPT_NAME, 2, approver="helpdesk-owner")
    ensure_ledger()
    put_gateway_config(gateway_config or DEFAULT_GATEWAY_CONFIG)
    model_router.put_config(model_config or DEFAULT_MODEL_CONFIG)
    return s3


CLAIMS = {
    # 自己申告の department をわざと食い違わせてある。ゲートウェイはこれを見ない
    "it": {"sub": "u-1043", "groups": ["helpdesk-it-users"], "department": "経理部"},
    "finance": {"sub": "u-2071", "groups": ["helpdesk-finance-users"]},
    "hr": {"sub": "u-2210", "groups": ["helpdesk-hr-users"]},
}

QUESTION = "有給休暇の繰越上限は何日ですか。"
CONTEXT = "年次有給休暇の未消化分は翌年度に限り繰り越せますが、繰越上限は20日です。"


def line(result: dict) -> str:
    return (
        f"decision={result['decision']:<9} status={result['httpStatus']}"
        f" dept={result['department'] or '-':<8} model={result['modelId'] or '-':<45}"
        f" reason={result['reason']}"
    )


def main() -> None:
    window = f"demo-{uuid.uuid4().hex[:8]}"
    bootstrap()
    gw = GenAIGateway(window=window)

    print("=== 1. 部門ごとに同じ入口を通す ===")
    for key in ("it", "finance", "hr"):
        result = gw.handle(
            {"claims": CLAIMS[key], "question": QUESTION, "context": CONTEXT}
        )
        print(" ", line(result))
        if result["decision"] == "allow":
            print(
                f"    見積り入力 {result['estimatedInputTokens']} tok"
                f" / 実測入力 {result['inputTokens']} tok"
                f" / 出力 {result['outputTokens']} tok"
                f" / prompt v{result['promptVersion']}"
            )

    print()
    print("=== 2. モデルを差し替える（呼び出し側のコードは1文字も変えない） ===")
    model_router.put_config(
        {
            **DEFAULT_MODEL_CONFIG,
            "primary": "anthropic.claude-3-5-haiku-20241022-v1:0",
            "fallbacks": ["amazon.nova-lite-v1:0"],
        }
    )
    gw.reload()
    for key in ("it", "finance"):
        result = gw.handle(
            {"claims": CLAIMS[key], "question": QUESTION, "context": CONTEXT}
        )
        print(" ", line(result))
    print("  経理部は Haiku を明示的な Deny で禁止しているため、候補から外れました")

    print()
    print("=== 3. 権限の無いモデルを既定にしてみる ===")
    model_router.put_config(
        {
            **DEFAULT_MODEL_CONFIG,
            "primary": "anthropic.claude-sonnet-4-5-20250929-v1:0",
            "fallbacks": [],
        }
    )
    gw.reload()
    result = gw.handle({"claims": CLAIMS["it"], "question": QUESTION, "context": CONTEXT})
    print(" ", line(result))
    print("  基盤モデルへの HTTP リクエストは1回も出していません")

    model_router.put_config(model_router.DEFAULT_CONFIG)
    print()
    print(f"監査ログ: {AUDIT_GROUP} / ストリーム {gw.stream}")
    print(f"原簿    : {LEDGER_TABLE} / 窓 {window}")
    print(f"監査の必須項目（セッション6と共通）: {len(prompt_audit.REQUIRED_FIELDS)} 欄")


if __name__ == "__main__":
    main()
