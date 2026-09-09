#!/usr/bin/env python3
"""セッション13: 経路と権限で境界を引く（データ境界）。

VPC エンドポイント（AWS PrivateLink）は LocalStack Community にありません。
そこで **同じ判断を IAM の条件キーで表現** し、セッション11の評価器
（`src/session11/authz.py` の `evaluate`）でそのまま判定します。
ポリシー文書は実 AWS にそのまま貼れる形です。

実務での対応:

    ① サブネットにインターフェース VPC エンドポイント（bedrock-runtime）を置く
    ② この Deny を権限境界（Permissions Boundary）か SCP として付ける
    ③ エンドポイントポリシーで、その口から呼べる相手をさらに絞る

①だけでは足りません。**経路を用意しても、パブリックエンドポイントへ出る道が
残っていれば通れます。**「そこを通らないと呼べない」を作るのが②の Deny です。
"""

from __future__ import annotations

import copy
import sys

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session11")

import authz  # noqa: E402

REGION = authz.REGION
ACCOUNT = "000000000000"  # LocalStack の既定アカウント

# インターフェース VPC エンドポイントの ID。実環境では作成時に払い出される
VPCE_ID = "vpce-0a1b2c3d4e5f67890"

# 機密性の高い資料を渡す経路で使えるモデル（データ処理の条件を確認済みのもの）
APPROVED_MODELS = ("amazon.nova-lite-v1:0",)
# 同じ経路では使わせないモデル。**許可の削除ではなく明示的な Deny で締める**
UNAPPROVED_MODELS = (
    "amazon.nova-micro-v1:0",
    "anthropic.claude-3-5-haiku-20241022-v1:0",
)

GUARDRAIL_ARN = f"arn:aws:bedrock:{REGION}:{ACCOUNT}:guardrail/demo-guardrail"
OTHER_GUARDRAIL_ARN = f"arn:aws:bedrock:{REGION}:{ACCOUNT}:guardrail/sandbox-guardrail"
KB_ARN = f"arn:aws:bedrock:{REGION}:{ACCOUNT}:knowledge-base/SAMPLEKB01"
OTHER_KB_ARN = f"arn:aws:bedrock:{REGION}:{ACCOUNT}:knowledge-base/SAMPLEKB99"

# 部品単位の許可。モデル単位の許可はセッション11のポリシーが持っている
COMPONENT_STATEMENTS: list[dict] = [
    {
        "Sid": "AllowNamedGuardrailOnly",
        "Effect": "Allow",
        "Action": "bedrock:ApplyGuardrail",
        "Resource": GUARDRAIL_ARN,
    },
    {
        "Sid": "AllowNamedKnowledgeBaseOnly",
        "Effect": "Allow",
        "Action": ["bedrock:Retrieve", "bedrock:RetrieveAndGenerate"],
        "Resource": KB_ARN,
    },
]

# 境界。**Deny なので、どんな Allow があっても覆らない**
PERIMETER_STATEMENTS: list[dict] = [
    {
        "Sid": "DenyOutsidePrivateLink",
        "Effect": "Deny",
        "Action": "bedrock:*",
        "Resource": "*",
        # キーが無い（＝エンドポイントを通っていない）場合も StringNotEquals は
        # 成立する。だから「送ってこなければ素通り」にならない
        "Condition": {"StringNotEquals": {"aws:SourceVpce": VPCE_ID}},
    },
    {
        "Sid": "DenyUnapprovedModelsOnSensitivePath",
        "Effect": "Deny",
        "Action": "bedrock:*",
        "Resource": [authz.model_arn(model) for model in UNAPPROVED_MODELS],
    },
]


def with_perimeter(role: str) -> dict:
    """セッション11のロールポリシーに、部品単位の許可と境界を足す。"""
    policy = copy.deepcopy(authz.POLICIES[role])
    policy["Statement"] = (
        policy["Statement"] + COMPONENT_STATEMENTS + PERIMETER_STATEMENTS
    )
    return policy


def context(principal, *, vpce: str | None = VPCE_ID, region: str = REGION) -> dict:
    """条件キーの値。実 AWS では `aws:SourceVpce` も AWS 側が埋める。"""
    values = dict(authz.request_context(principal, region=region))
    if vpce:
        values["aws:SourceVpce"] = vpce
    return values


def decide(
    role: str,
    *,
    action: str,
    resource: str,
    vpce: str | None = VPCE_ID,
    region: str = REGION,
):
    principal = authz.principal_for_role(role)
    return authz.evaluate(
        with_perimeter(role),
        action=action,
        resource=resource,
        context=context(principal, vpce=vpce, region=region),
    )


def can_invoke(
    role: str, model_id: str, *, vpce: str | None = VPCE_ID, region: str = REGION
):
    """「この部門は、この経路で、このモデルを呼べるか」を1行で答える。"""
    return decide(
        role,
        action="bedrock:InvokeModel",
        resource=authz.model_arn(model_id),
        vpce=vpce,
        region=region,
    )


# 期待表。境界を足す前（セッション11）との差が、そのまま境界の効果になる
EXPECTED_PERIMETER: tuple[tuple[str, str, str | None, bool, str], ...] = (
    ("helpdesk-it", "amazon.nova-lite-v1:0", VPCE_ID, True, "allow"),
    ("helpdesk-it", "amazon.nova-lite-v1:0", None, False, "explicit_deny"),
    ("helpdesk-it", "amazon.nova-micro-v1:0", VPCE_ID, False, "explicit_deny"),
    (
        "helpdesk-it",
        "anthropic.claude-3-5-haiku-20241022-v1:0",
        VPCE_ID,
        False,
        "explicit_deny",
    ),
    ("helpdesk-finance", "amazon.nova-lite-v1:0", VPCE_ID, True, "allow"),
    ("helpdesk-finance", "amazon.nova-lite-v1:0", None, False, "explicit_deny"),
    ("helpdesk-hr", "amazon.nova-lite-v1:0", VPCE_ID, True, "allow"),
)

# 部品単位の期待表（ガードレール／ナレッジベース）
EXPECTED_COMPONENTS: tuple[tuple[str, str, str, bool], ...] = (
    ("指定したガードレール", "bedrock:ApplyGuardrail", GUARDRAIL_ARN, True),
    ("別のガードレール", "bedrock:ApplyGuardrail", OTHER_GUARDRAIL_ARN, False),
    ("指定したナレッジベース", "bedrock:Retrieve", KB_ARN, True),
    ("別のナレッジベース", "bedrock:Retrieve", OTHER_KB_ARN, False),
)


def gate() -> list[str]:
    """期待表と評価結果を突き合わせるゲート。失敗の一覧を返す（空なら合格）。"""
    failures: list[str] = []
    for role, model_id, vpce, expected, reason in EXPECTED_PERIMETER:
        decision = can_invoke(role, model_id, vpce=vpce)
        if decision.allowed != expected or decision.reason != reason:
            failures.append(f"{role}/{model_id}/vpce={vpce}: {decision.describe()}")
    for label, action, resource, expected in EXPECTED_COMPONENTS:
        decision = decide("helpdesk-it", action=action, resource=resource)
        if decision.allowed != expected:
            failures.append(f"{label}: {decision.describe()}")
    return failures


def main() -> None:
    print("=== 経路の境界（aws:SourceVpce） ===")
    for model_id in APPROVED_MODELS + UNAPPROVED_MODELS:
        via = can_invoke("helpdesk-it", model_id)
        direct = can_invoke("helpdesk-it", model_id, vpce=None)
        print(f"{model_id} | 経由 {via.describe()} | 直接 {direct.describe()}")

    print()
    print("=== 部品単位の許可（ガードレール／ナレッジベース） ===")
    for label, action, resource, _ in EXPECTED_COMPONENTS:
        print(f"{label} | {decide('helpdesk-it', action=action, resource=resource).describe()}")

    print()
    print(f"ゲートの失敗: {gate() or 'なし'}")


if __name__ == "__main__":
    main()
