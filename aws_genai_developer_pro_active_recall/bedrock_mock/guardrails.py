"""Amazon Bedrock Guardrails の擬似実装。

実 Guardrails は機械学習ベースの分類器を使いますが、モックでは
「キーワードと正規表現」で同じ *レスポンス形状* と *判定の考え方* を再現します。
学習の目的は分類器の精度ではなく、

- 入力側（INPUT）と出力側（OUTPUT）の両方に評価が走ること
- 介入されたときに `action = GUARDRAIL_INTERVENED` となり、本文が差し替わること
- どのポリシーが反応したかが `assessments` に出ること
- グラウンディング（根拠）スコアが閾値を下回ると止まること

を手で確かめることです。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .generation import _keywords  # noqa: PLC2701  教材内部での再利用は許容する


@dataclass
class DeniedTopic:
    name: str
    definition: str
    keywords: tuple[str, ...]


@dataclass
class GuardrailPolicy:
    guardrail_id: str
    version: str = "DRAFT"
    blocked_input_message: str = "この質問にはお答えできません。"
    blocked_output_message: str = "回答を表示できません。"
    denied_topics: tuple[DeniedTopic, ...] = ()
    blocked_words: tuple[str, ...] = ()
    pii_action: str = "ANONYMIZE"  # ANONYMIZE | BLOCK | NONE
    prompt_attack_strength: str = "HIGH"  # NONE | LOW | MEDIUM | HIGH
    grounding_threshold: float = 0.0  # 0 なら無効
    relevance_threshold: float = 0.0


# PII の検出パターン。実 Guardrails のエンティティ名に合わせている。
PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "EMAIL": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "PHONE": re.compile(r"\b0\d{1,4}-\d{1,4}-\d{4}\b"),
    "CREDIT_DEBIT_CARD_NUMBER": re.compile(r"\b(?:\d{4}[- ]?){3}\d{4}\b"),
    "IP_ADDRESS": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
}

# プロンプトインジェクション／ジェイルブレイクの兆候。
PROMPT_ATTACK_PATTERNS = (
    re.compile(r"これまでの指示|上記の指示|前の指示", re.IGNORECASE),
    re.compile(r"ignore (all )?(previous|prior|above)", re.IGNORECASE),
    re.compile(r"system prompt|システムプロンプト", re.IGNORECASE),
    re.compile(r"jailbreak|制限を解除|開発者モード", re.IGNORECASE),
)

DEFAULT_POLICIES: dict[str, GuardrailPolicy] = {
    "demo-guardrail": GuardrailPolicy(
        guardrail_id="demo-guardrail",
        version="1",
        blocked_input_message="そのご質問は本サービスの対象外です。",
        blocked_output_message="根拠のない回答になるため表示を控えました。",
        denied_topics=(
            DeniedTopic(
                name="InvestmentAdvice",
                definition="個別銘柄の売買や利回りに関する助言",
                keywords=("投資", "銘柄", "株価", "利回り", "配当", "仮想通貨"),
            ),
            DeniedTopic(
                name="MedicalDiagnosis",
                definition="症状に対する診断や処方の提示",
                keywords=("診断", "処方", "服用", "投薬"),
            ),
        ),
        blocked_words=("裏技", "抜け道"),
        pii_action="ANONYMIZE",
        prompt_attack_strength="HIGH",
        grounding_threshold=0.0,
    )
}


@dataclass
class Assessment:
    topics: list[dict] = field(default_factory=list)
    filters: list[dict] = field(default_factory=list)
    pii: list[dict] = field(default_factory=list)
    words: list[dict] = field(default_factory=list)
    grounding: list[dict] = field(default_factory=list)

    def to_api(self) -> dict:
        out: dict[str, object] = {}
        if self.topics:
            out["topicPolicy"] = {"topics": self.topics}
        if self.filters:
            out["contentPolicy"] = {"filters": self.filters}
        if self.pii:
            out["sensitiveInformationPolicy"] = {"piiEntities": self.pii}
        if self.words:
            out["wordPolicy"] = {"customWords": self.words}
        if self.grounding:
            out["contextualGroundingPolicy"] = {"filters": self.grounding}
        return out


def _grounding_score(text: str, sources: list[str]) -> float:
    """出力が根拠資料にどれだけ支えられているかの擬似スコア（0.0〜1.0）。"""
    if not sources:
        return 0.0
    out_kw = _keywords(text)
    if not out_kw:
        return 1.0
    src_kw: set[str] = set()
    for s in sources:
        src_kw |= _keywords(s)
    return round(len(out_kw & src_kw) / len(out_kw), 4)


def evaluate(
    *,
    policy: GuardrailPolicy,
    text: str,
    source: str = "INPUT",
    grounding_sources: list[str] | None = None,
    query: str = "",
) -> dict:
    """ApplyGuardrail と同じ形の判定結果を返す。"""
    assessment = Assessment()
    intervened = False
    masked = text

    for topic in policy.denied_topics:
        if any(k in text for k in topic.keywords):
            assessment.topics.append(
                {"name": topic.name, "type": "DENY", "action": "BLOCKED"}
            )
            intervened = True

    if policy.prompt_attack_strength != "NONE" and source == "INPUT":
        if any(p.search(text) for p in PROMPT_ATTACK_PATTERNS):
            assessment.filters.append(
                {
                    "type": "PROMPT_ATTACK",
                    "confidence": "HIGH",
                    "filterStrength": policy.prompt_attack_strength,
                    "action": "BLOCKED",
                }
            )
            intervened = True

    for word in policy.blocked_words:
        if word and word in text:
            assessment.words.append({"match": word, "action": "BLOCKED"})
            intervened = True

    if policy.pii_action != "NONE":
        for entity, pattern in PII_PATTERNS.items():
            for match in pattern.finditer(text):
                action = "ANONYMIZED" if policy.pii_action == "ANONYMIZE" else "BLOCKED"
                assessment.pii.append(
                    {"match": match.group(0), "type": entity, "action": action}
                )
                if policy.pii_action == "ANONYMIZE":
                    masked = masked.replace(match.group(0), f"{{{entity}}}")
                else:
                    intervened = True

    if source == "OUTPUT" and policy.grounding_threshold > 0:
        score = _grounding_score(text, grounding_sources or [])
        action = "BLOCKED" if score < policy.grounding_threshold else "NONE"
        assessment.grounding.append(
            {
                "type": "GROUNDING",
                "threshold": policy.grounding_threshold,
                "score": score,
                "action": action,
            }
        )
        if action == "BLOCKED":
            intervened = True

    if intervened:
        output_text = (
            policy.blocked_input_message
            if source == "INPUT"
            else policy.blocked_output_message
        )
    else:
        output_text = masked

    return {
        "action": "GUARDRAIL_INTERVENED" if intervened else "NONE",
        "actionReason": "ポリシー違反を検出しました。" if intervened else "",
        "outputs": [{"text": output_text}] if intervened or masked != text else [],
        "assessments": [assessment.to_api()],
        "usage": {
            "topicPolicyUnits": 1 if policy.denied_topics else 0,
            "contentPolicyUnits": 1,
            "wordPolicyUnits": 1 if policy.blocked_words else 0,
            "sensitiveInformationPolicyUnits": 1,
            "sensitiveInformationPolicyFreeUnits": 0,
            "contextualGroundingPolicyUnits": 1 if policy.grounding_threshold else 0,
        },
    }
