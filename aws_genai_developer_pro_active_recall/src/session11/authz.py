#!/usr/bin/env python3
"""セッション11: ID フェデレーションと最小権限の認可層。

**なぜ自作の評価器なのか。** 試験で問われるのは「ポリシー文書を読んで、
この主体はこの API を呼べるかを判定できるか」です。LocalStack Community の
`iam:SimulatePrincipalPolicy` は評価結果を忠実に再現しないため、
本書では **本物と同じ形の IAM ポリシー JSON** を置き、その JSON を解釈する
評価器をここに書きます。判定ロジックは実 IAM の順序に合わせています。

    明示的な Deny > 一致する Allow > 暗黙的な Deny（既定は拒否）

実務ではこの層をアプリで実装しません。ゲートウェイ（API Gateway ＋ Lambda / ECS）が
**利用部門ごとに別の IAM ロールを引き受け**、Bedrock の呼び出しは
そのロールの権限で行います。ここで書く評価器は「そのとき AWS 側で何が起きるか」を
手元で観察するための模型です。
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass

# 認可の対象になるリージョン。データ所在の制約を条件キーで表現するために使う
REGION = "us-east-1"

# 基盤モデル（FM）の ARN。`bedrock:InvokeModel` のリソース指定はこの形になる
MODEL_ARN_PREFIX = f"arn:aws:bedrock:{REGION}::foundation-model/"


def model_arn(model_id: str) -> str:
    """モデル ID から ARN を作る。ワイルドカード（`amazon.nova-*`）も渡せる。"""
    return f"{MODEL_ARN_PREFIX}{model_id}"


# 会話系の呼び出しで書くアクション。推論を認可するのは InvokeModel 系で、
# 同期（InvokeModel）だけ許して streaming 版を忘れると
# 「同期は通るがストリーミングだけ 403」という分かりにくい障害になる
CONVERSE_ACTIONS = (
    "bedrock:InvokeModel",
    "bedrock:InvokeModelWithResponseStream",
    "bedrock:Converse",
    "bedrock:ConverseStream",
)

# ---------------------------------------------------------------------------
# ポリシー文書（実 AWS にそのまま貼れる形にしてある）
# ---------------------------------------------------------------------------

POLICIES: dict[str, dict] = {
    # 情報システム部: 使うモデルを列挙し、高額モデルだけ明示的に締める
    "helpdesk-it": {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowStandardHelpdeskModels",
                "Effect": "Allow",
                "Action": list(CONVERSE_ACTIONS),
                "Resource": [
                    model_arn("amazon.nova-lite-v1:0"),
                    model_arn("amazon.nova-micro-v1:0"),
                    model_arn("anthropic.claude-3-5-haiku-20241022-v1:0"),
                ],
                "Condition": {
                    # ABAC。ロールに付けたタグと一致しなければ許可しない
                    "StringEquals": {"aws:PrincipalTag/department": "情報システム部"},
                    "Bool": {"aws:SecureTransport": "true"},
                },
            },
            {
                "Sid": "DenyExpensiveModels",
                "Effect": "Deny",
                "Action": "bedrock:*",
                "Resource": model_arn("anthropic.claude-sonnet-4-5-20250929-v1:0"),
            },
        ],
    },
    # 経理部: ワイルドカードで許し、予算外を明示的な Deny で締める形
    "helpdesk-finance": {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowNovaFamily",
                "Effect": "Allow",
                "Action": list(CONVERSE_ACTIONS),
                "Resource": model_arn("amazon.nova-*"),
            },
            {
                "Sid": "DenyOutsideBudget",
                "Effect": "Deny",
                "Action": "bedrock:*",
                "Resource": [
                    model_arn("amazon.nova-pro-v1:0"),
                    model_arn("anthropic.claude-3-5-haiku-20241022-v1:0"),
                    model_arn("anthropic.claude-sonnet-4-5-20250929-v1:0"),
                ],
            },
        ],
    },
    # 人事部: データ所在の要件があるため、呼び出し先リージョンを条件で固定する
    "helpdesk-hr": {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowInRegionOnly",
                "Effect": "Allow",
                "Action": list(CONVERSE_ACTIONS),
                "Resource": model_arn("amazon.nova-lite-v1:0"),
                "Condition": {"StringEquals": {"aws:RequestedRegion": REGION}},
            }
        ],
    },
}

# IdP のグループ → 引き受けるロール。この表に無いグループは誰も引き受けられない
GROUP_TO_ROLE = {
    "helpdesk-it-users": "helpdesk-it",
    "helpdesk-finance-users": "helpdesk-finance",
    "helpdesk-hr-users": "helpdesk-hr",
}

# ロールに付いているタグ。**部門は利用者の自己申告ではなくここから決める**
ROLE_TAGS = {
    "helpdesk-it": {"department": "情報システム部", "costCenter": "CC-1001"},
    "helpdesk-finance": {"department": "経理部", "costCenter": "CC-2002"},
    "helpdesk-hr": {"department": "人事部", "costCenter": "CC-3003"},
}

# 認可の「期待表」。CI のゲートでこの表と評価結果を突き合わせる。
# ポリシーを1文字直したときに、意図しない部門の権限が動いたことに気づける
EXPECTED_MATRIX: tuple[tuple[str, str, bool], ...] = (
    ("helpdesk-it", "amazon.nova-lite-v1:0", True),
    ("helpdesk-it", "amazon.nova-micro-v1:0", True),
    ("helpdesk-it", "anthropic.claude-3-5-haiku-20241022-v1:0", True),
    ("helpdesk-it", "amazon.nova-pro-v1:0", False),
    ("helpdesk-it", "anthropic.claude-sonnet-4-5-20250929-v1:0", False),
    ("helpdesk-finance", "amazon.nova-lite-v1:0", True),
    ("helpdesk-finance", "amazon.nova-micro-v1:0", True),
    ("helpdesk-finance", "amazon.nova-pro-v1:0", False),
    ("helpdesk-finance", "anthropic.claude-3-5-haiku-20241022-v1:0", False),
    ("helpdesk-hr", "amazon.nova-lite-v1:0", True),
    ("helpdesk-hr", "amazon.nova-micro-v1:0", False),
)


# ---------------------------------------------------------------------------
# 主体（プリンシパル）と ID フェデレーション
# ---------------------------------------------------------------------------


class FederationError(Exception):
    """誰の要求か特定できない。呼び出しの前に落とす（401 相当）。"""


@dataclass(frozen=True)
class Principal:
    subject: str
    role: str
    tags: dict

    @property
    def department(self) -> str:
        return self.tags["department"]

    @property
    def arn(self) -> str:
        """引き受けたロールの ARN。監査に残すのは利用者名ではなくこれ。"""
        return f"arn:aws:sts::000000000000:assumed-role/{self.role}/{self.subject}"


def resolve_identity(claims: dict) -> Principal:
    """IdP のクレームからロールを決める（AssumeRoleWithWebIdentity 相当）。

    **`claims["department"]` は見ません。** 部門は課金と権限の境界なので、
    利用者が送ってきた値ではなく、ロールに付いたタグから決めます。
    """
    subject = claims.get("sub")
    if not subject:
        raise FederationError("sub クレームがありません（誰の要求か特定できません）")
    groups = [g for g in (claims.get("groups") or []) if g in GROUP_TO_ROLE]
    if not groups:
        raise FederationError(
            f"引き受けられるロールがありません: {claims.get('groups')!r}"
        )
    if len(groups) > 1:
        # 複数のロールを引き受けられる状態は、権限の広いほうへ寄る事故を生む
        raise FederationError(f"ロールが一意に決まりません: {groups!r}")
    role = GROUP_TO_ROLE[groups[0]]
    return Principal(subject=subject, role=role, tags=dict(ROLE_TAGS[role]))


def request_context(
    principal: Principal, *, region: str = REGION, secure_transport: bool = True
) -> dict:
    """条件キーの値を組み立てる。実 AWS では AWS 側が自動で埋める欄。"""
    context = {
        "aws:PrincipalArn": principal.arn,
        "aws:RequestedRegion": region,
        "aws:SecureTransport": "true" if secure_transport else "false",
    }
    for key, value in principal.tags.items():
        context[f"aws:PrincipalTag/{key}"] = value
    return context


# ---------------------------------------------------------------------------
# ポリシー評価
# ---------------------------------------------------------------------------

CONDITION_OPERATORS = ("StringEquals", "StringNotEquals", "StringLike", "Bool")


def _as_list(value) -> list:
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _matches(patterns, value: str, *, ignore_case: bool = False) -> bool:
    """ワイルドカード（`*`）付きの照合。アクション名は大文字小文字を区別しない。"""
    for pattern in _as_list(patterns):
        left, right = (value, str(pattern))
        if ignore_case:
            left, right = left.lower(), right.lower()
        if fnmatch.fnmatchcase(left, right):
            return True
    return False


def _condition_holds(condition: dict | None, context: dict) -> bool:
    """`Condition` を評価する。**キーが無ければ StringEquals は成立しない。**"""
    for operator, entries in (condition or {}).items():
        if operator not in CONDITION_OPERATORS:
            raise ValueError(f"この教材の評価器が未対応の条件演算子です: {operator}")
        for key, expected in entries.items():
            actual = context.get(key)
            values = [str(v) for v in _as_list(expected)]
            if operator == "StringEquals":
                if actual is None or str(actual) not in values:
                    return False
            elif operator == "StringNotEquals":
                # 実 IAM と同じく、キーが無い場合は「等しくない」として成立する
                if actual is not None and str(actual) in values:
                    return False
            elif operator == "StringLike":
                if actual is None or not any(
                    fnmatch.fnmatchcase(str(actual), v) for v in values
                ):
                    return False
            else:  # Bool
                if str(actual).lower() not in [v.lower() for v in values]:
                    return False
    return True


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    sid: str | None = None

    def describe(self) -> str:
        return f"{'ALLOW' if self.allowed else 'DENY'}({self.reason}/{self.sid or '-'})"


def evaluate(policy: dict, *, action: str, resource: str, context: dict | None = None) -> Decision:
    """1つのポリシー文書を評価する。順序は実 IAM と同じ。

    1. 一致する **Deny** が1つでもあれば拒否（Allow が何個あっても覆らない）
    2. 一致する **Allow** があれば許可
    3. どちらも無ければ拒否（暗黙的な Deny。既定は「何もできない」）
    """
    context = context or {}
    allow_sid: str | None = None
    matched_allow = False
    for statement in policy.get("Statement", []):
        if not _matches(statement.get("Action", []), action, ignore_case=True):
            continue
        if not _matches(statement.get("Resource", []), resource):
            continue
        if not _condition_holds(statement.get("Condition"), context):
            continue
        if statement.get("Effect") == "Deny":
            return Decision(False, "explicit_deny", statement.get("Sid"))
        if not matched_allow:
            matched_allow = True
            allow_sid = statement.get("Sid")
    if matched_allow:
        return Decision(True, "allow", allow_sid)
    return Decision(False, "implicit_deny", None)


def can_invoke(
    principal: Principal,
    model_id: str,
    *,
    region: str = REGION,
    action: str = "bedrock:InvokeModel",
) -> Decision:
    """「この部門はこのモデルを呼べるか」を1行で答える。"""
    policy = POLICIES.get(principal.role)
    if policy is None:
        return Decision(False, "no_policy", None)
    return evaluate(
        policy,
        action=action,
        resource=model_arn(model_id),
        context=request_context(principal, region=region),
    )


def principal_for_role(role: str, *, subject: str = "pipeline") -> Principal:
    """CI のゲートやテストで使う、ロールだけ指定した主体。"""
    return Principal(subject=subject, role=role, tags=dict(ROLE_TAGS[role]))


def main() -> None:
    print("=== 認可マトリクス（部門 × モデル） ===")
    for role, model_id, expected in EXPECTED_MATRIX:
        decision = can_invoke(principal_for_role(role), model_id)
        mark = "○" if decision.allowed else "×"
        agree = "一致" if decision.allowed == expected else "不一致"
        print(f"  {mark} {ROLE_TAGS[role]['department']:<8} {model_id:<45} "
              f"{decision.describe():<34} 期待表と{agree}")

    print()
    print("=== 条件キーが効く例（人事部はリージョンで縛っている） ===")
    hr = principal_for_role("helpdesk-hr", subject="u-2210")
    for region in (REGION, "ap-northeast-1"):
        decision = can_invoke(hr, "amazon.nova-lite-v1:0", region=region)
        print(f"  aws:RequestedRegion={region:<16} -> {decision.describe()}")


if __name__ == "__main__":
    main()
