#!/usr/bin/env python3
"""セッション12: 入出力の安全制御 — 4層の防御。

    docker compose exec app python src/session12/safety.py

セッション11で作ったゲートウェイ（認可・上限・冪等・監査）の中に、次の4層を差し込みます。

    L1 前処理フィルタ   … 課金ゼロ。正規化・境界タグの無害化・明らかな異常の遮断
    L2 入力ガードレール … ApplyGuardrail(source="INPUT")。拒否トピック・攻撃・機密情報
    L3 後処理検証       … 出力側の評価（文脈的グラウンディング）と回答の契約検証
    L4 応答フィルタ     … 返す直前の最後の網。内部情報の露出と PII の残存を止める

**モックの制約**：`CreateGuardrail` が無いため、閾値を変えたガードレールを作れません。
そのため L3 は `bedrock_mock.guardrails` の評価器を直接呼び、閾値だけ自分で決めます
（モジュールは変更しません。import して使うだけです）。実 AWS では
`ApplyGuardrail(source="OUTPUT")` に `grounding_source` / `query` の qualifier を
付けて同じ形の判定を受け取ります。リクエストの形は本文に載せてあります。
"""

from __future__ import annotations

import math
import re
import sys
import unicodedata
from dataclasses import dataclass, field, replace

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session05")
sys.path.insert(0, "/workspace/src/session06")
sys.path.insert(0, "/workspace/src/session12")

from awskit import clients  # noqa: E402
from bedrock_mock import guardrails  # noqa: E402

import prompt_registry as registry  # noqa: E402  セッション6（プロンプトの版）
import retriever  # noqa: E402  セッション5（検索の共通入口）

# ---------------------------------------------------------------------------
# 設定（層ごとの「止める基準」はすべてここに集める）
# ---------------------------------------------------------------------------

MODEL_ID = "amazon.nova-lite-v1:0"
GUARDRAIL_ID = "demo-guardrail"
GUARDRAIL_VERSION = "1"

DEPARTMENT = "情報システム部"
MAX_SENTENCES = 3
TOP_K = 3

# L1: 入力の上限（見積りトークン）。長文でコンテキストを溢れさせる要求を安く落とす
MAX_INPUT_TOKENS = 800

# L3/L4: 回答の上限（文字数）。長すぎる回答は切り詰めてから返す
MAX_ANSWER_CHARS = 600

# L3: 文脈的グラウンディングの閾値。**高いほど安全ではありません**（本文の解説5を参照）
GROUNDING_THRESHOLD = 0.25

# 利用者に返す定型文。拒否の理由をそのまま見せない（内部の判定基準を教えないため）
SAFE_FALLBACK = "お答えを表示できませんでした。担当窓口にお問い合わせください。"

# プロンプトは章をまたいで同じものを使う。セッション6の承認済みの版（v2）に相当。
# S3 を使わずに済むよう、ここでは手元のテンプレート定義から読む
TEMPLATE = registry.local(registry.PROMPT_NAME, 2)
SYSTEM_BLOCKS = registry.render_system(
    TEMPLATE, {"department": DEPARTMENT, "max_sentences": MAX_SENTENCES}
)
SYSTEM_TEXT = SYSTEM_BLOCKS[0]["text"]

# system の先頭を「合言葉」として使う。これが回答に混ざっていたら指示文の漏えい
SYSTEM_FINGERPRINT = SYSTEM_TEXT[:24]

# L4: 出力に出てはいけない内部識別子
INTERNAL_MARKERS = (
    "amazon.nova",
    "anthropic.claude",
    "meta.llama",
    "arn:aws:bedrock",
    GUARDRAIL_ID,
)

# L1: プロンプトの構造を壊しにくる境界タグ。**消すのではなく無害化して通す**
BOUNDARY_TAG = re.compile(
    r"</?\s*(context|documents|system|instructions|資料)\s*>", re.IGNORECASE
)
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f�]")
SPACE_RUN = re.compile(r"[ \t　]{2,}")


# ---------------------------------------------------------------------------
# 層の結果
# ---------------------------------------------------------------------------


@dataclass
class LayerResult:
    """1つの層の判定。**遮断・修復・警報を別の欄にする**のがこの型の主旨。

    遮断（blocked）と修復（repairs）を1つの真偽値にまとめると、
    「止めたのか、直して通したのか」が後から数えられなくなります。
    """

    layer: str
    blocked: bool = False
    reason: str = ""
    text: str = ""
    repairs: tuple[str, ...] = ()
    alerts: tuple[str, ...] = ()
    detail: dict = field(default_factory=dict)

    def line(self) -> str:
        verdict = "block" if self.blocked else "pass"
        return (
            f"{self.layer} {verdict} reason={self.reason or '-'}"
            f" repairs={','.join(self.repairs) or '-'}"
        )


@dataclass
class Outcome:
    """1件の要求の結末。層ごとの記録を残したまま返す。"""

    layer: str  # "L1" / "L2" / "L3" / "L4" / "allow"
    decision: str  # "allow" / "block"
    reason: str
    text: str
    repairs: tuple[str, ...] = ()
    alerts: tuple[str, ...] = ()
    model_called: bool = False
    raw_answer: str = ""
    sources: list[str] = field(default_factory=list)
    trail: list[str] = field(default_factory=list)


def estimate_tokens(text: str) -> int:
    """呼ぶ前にトークン数を見積もる（セッション11の `estimate_tokens` と同じ規則）。

    ASCII は4文字＝1トークン、非 ASCII は1文字＝1トークン。ゲートウェイ本体を
    import せずに済むよう、この層だけで同じ計算を持ちます。
    """
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    return (len(text) - ascii_chars) + math.ceil(ascii_chars / 4)


def pick_text(verdict: dict, fallback: str) -> str:
    """判定結果から本文を取り出す。

    **`outputs` は空配列で返ることがあります。** 匿名化も介入も起きなかった場合、
    モックも実 API も「差し替える本文が無い」ので空にします。
    `verdict["outputs"][0]` と直接書くと、そこで `IndexError` になります。
    """
    outputs = verdict.get("outputs") or []
    return outputs[0]["text"] if outputs else fallback


def guardrail_reason(assessment: dict) -> str:
    """どのポリシーが反応したかを1語にする。監査で数えられる形にするため。"""
    topics = (assessment.get("topicPolicy") or {}).get("topics") or []
    if topics:
        return "denied_topic:" + ",".join(t["name"] for t in topics)
    filters = (assessment.get("contentPolicy") or {}).get("filters") or []
    for f in filters:
        if f.get("action") == "BLOCKED":
            return f["type"].lower()
    words = (assessment.get("wordPolicy") or {}).get("customWords") or []
    if words:
        return "blocked_word:" + ",".join(w["match"] for w in words)
    grounding = (assessment.get("contextualGroundingPolicy") or {}).get("filters") or []
    for f in grounding:
        if f.get("action") == "BLOCKED":
            return "grounding_below_threshold"
    pii = (assessment.get("sensitiveInformationPolicy") or {}).get("piiEntities") or []
    if any(e.get("action") == "BLOCKED" for e in pii):
        return "pii_blocked"
    return "guardrail_intervened"


# ---------------------------------------------------------------------------
# L1: 前処理フィルタ（課金ゼロ・ミリ秒）
# ---------------------------------------------------------------------------


def pre_filter(text: str) -> LayerResult:
    """一番外側の門。**安い検査を先に置く**という原則だけでこの層は決まります。

    ここでやることは3つです。

        1. 明らかな異常を落とす（空・長すぎ・制御文字）
        2. 正規化する（全角→半角。**後ろの層の検出力が上がる**）
        3. 境界タグを無害化する（プロンプトの構造を壊させない）

    2 と 3 は遮断ではなく修復です。修復した件数を数えておくと、
    「攻撃が増えたのか、入力の質が落ちたのか」を後から切り分けられます。
    """
    repairs: list[str] = []

    # 制御文字は正規化より前に見る（正規化で消えると混入に気づけない）
    if CONTROL_CHARS.search(text):
        return LayerResult("L1", blocked=True, reason="control_chars", text=text)

    normalized = unicodedata.normalize("NFKC", text)
    if normalized != text:
        repairs.append("nfkc")

    untagged = BOUNDARY_TAG.sub(" ", normalized)
    if untagged != normalized:
        repairs.append("boundary_tag")

    collapsed = SPACE_RUN.sub(" ", untagged).strip()
    if collapsed != untagged.strip():
        repairs.append("whitespace")

    if not collapsed:
        return LayerResult("L1", blocked=True, reason="empty", text="")

    tokens = estimate_tokens(collapsed)
    if tokens > MAX_INPUT_TOKENS:
        return LayerResult(
            "L1",
            blocked=True,
            reason="too_long",
            text=collapsed,
            detail={"tokens": tokens, "limit": MAX_INPUT_TOKENS},
        )

    return LayerResult("L1", text=collapsed, repairs=tuple(repairs))


# ---------------------------------------------------------------------------
# L2: 入力ガードレール（ApplyGuardrail）
# ---------------------------------------------------------------------------


def input_guardrail(runtime, text: str) -> LayerResult:
    """**利用者の入力だけ**にガードレールを当てる。

    検索で取ってきた社内資料を一緒に評価させてはいけません。自社の文書に
    「配当」「診断」の語が出てくるだけで業務が止まります（本文の解説3）。
    `Converse` の `guardrailConfig` に丸投げすると、この事故が起きます。
    """
    verdict = runtime.apply_guardrail(
        guardrailIdentifier=GUARDRAIL_ID,
        guardrailVersion=GUARDRAIL_VERSION,
        source="INPUT",
        content=[{"text": {"text": text}}],
    )
    assessment = (verdict.get("assessments") or [{}])[0]

    if verdict["action"] == "GUARDRAIL_INTERVENED":
        return LayerResult(
            "L2",
            blocked=True,
            reason=guardrail_reason(assessment),
            text=pick_text(verdict, SAFE_FALLBACK),
            detail=assessment,
        )

    # 介入されていなくても本文が変わることがある（PII の匿名化）
    entities = (assessment.get("sensitiveInformationPolicy") or {}).get(
        "piiEntities"
    ) or []
    alerts = tuple(f"pii_in_input:{e['type']}" for e in entities)
    return LayerResult(
        "L2",
        text=pick_text(verdict, text),
        repairs=("pii_anonymized",) if entities else (),
        alerts=alerts,
        detail=assessment,
    )


# ---------------------------------------------------------------------------
# L3: 後処理検証（出力側の評価＋回答の契約）
# ---------------------------------------------------------------------------

# 出力側に当てるポリシー。入力側と別に持つ理由は「面ごとに見るものが違う」から。
# プロンプト攻撃は入力側の話なので NONE、グラウンディングは出力側だけで意味を持つ
POST_POLICY = guardrails.GuardrailPolicy(
    guardrail_id="helpdesk-output-check",
    version="DRAFT",
    blocked_output_message="根拠のある回答を作れなかったため、表示を控えました。",
    denied_topics=guardrails.DEFAULT_POLICIES[GUARDRAIL_ID].denied_topics,
    blocked_words=guardrails.DEFAULT_POLICIES[GUARDRAIL_ID].blocked_words,
    pii_action="ANONYMIZE",
    prompt_attack_strength="NONE",
    grounding_threshold=GROUNDING_THRESHOLD,
)


def contract_problems(text: str) -> list[str]:
    """回答が契約どおりかを見る。**自由生成をそのまま外に出さないための最後の型。**"""
    problems: list[str] = []
    if registry.GROUNDING_MARKER not in text:
        problems.append("no_grounding_marker")
    if len(text) > MAX_ANSWER_CHARS:
        problems.append("answer_too_long")
    return problems


def post_check(
    answer: str,
    sources: list[str],
    *,
    question: str = "",
    threshold: float | None = None,
) -> LayerResult:
    """モデル自身の断り → 出力側のガードレール → 契約検証 の順に見る。

    順番に意味があります。

        1. **モデルが「資料の範囲外」と答えた**なら、根拠を採点する意味がありません。
           断りとして記録します（作り話とは別の事象なので理由も分けます）。
        2. ガードレールの判定（拒否トピック・機密情報・根拠）は「外に出してよいか」。
        3. 契約検証は「約束した形か」。2 で落ちたものを 3 の理由で上書きしません。
    """
    if registry.REFUSAL_MARKER in answer:
        return LayerResult(
            "L3",
            blocked=True,
            reason="no_grounded_answer",
            text=POST_POLICY.blocked_output_message,
            detail={"refusal": True},
        )

    policy = POST_POLICY if threshold is None else replace(
        POST_POLICY, grounding_threshold=threshold
    )
    verdict = guardrails.evaluate(
        policy=policy,
        text=answer,
        source="OUTPUT",
        grounding_sources=sources,
        query=question,
    )
    assessment = (verdict.get("assessments") or [{}])[0]

    if verdict["action"] == "GUARDRAIL_INTERVENED":
        return LayerResult(
            "L3",
            blocked=True,
            reason=guardrail_reason(assessment),
            text=pick_text(verdict, policy.blocked_output_message),
            detail=assessment,
        )

    text = pick_text(verdict, answer)
    problems = contract_problems(text)
    if problems:
        return LayerResult(
            "L3",
            blocked=True,
            reason=f"contract:{problems[0]}",
            text=SAFE_FALLBACK,
            detail={"problems": problems},
        )
    return LayerResult("L3", text=text, detail=assessment)


# ---------------------------------------------------------------------------
# L4: API 応答フィルタ（返す直前の最後の網）
# ---------------------------------------------------------------------------


def response_filter(answer: str, *, system_text: str = SYSTEM_TEXT) -> LayerResult:
    """返す直前に見る。**普段はここで1件も止まらないのが正常**な層です。

    ここで止まったら、上流のどこかが壊れた合図として扱います
    （＝この層の遮断件数は、そのまま「上流の異常」の指標になります）。
    """
    fingerprint = system_text[:24]
    if fingerprint and fingerprint in answer:
        return LayerResult(
            "L4", blocked=True, reason="system_prompt_echo", text=SAFE_FALLBACK
        )
    for marker in INTERNAL_MARKERS:
        if marker in answer:
            return LayerResult(
                "L4",
                blocked=True,
                reason=f"internal_identifier:{marker}",
                text=SAFE_FALLBACK,
            )

    text = answer
    repairs: list[str] = []
    alerts: list[str] = []
    for entity, pattern in guardrails.PII_PATTERNS.items():
        if pattern.search(text):
            text = pattern.sub("{" + entity + "}", text)
            repairs.append("pii_anonymized")
            alerts.append(f"pii_in_output:{entity}")
    if len(text) > MAX_ANSWER_CHARS:
        text = text[:MAX_ANSWER_CHARS]
        repairs.append("truncated")
    return LayerResult(
        "L4", text=text, repairs=tuple(repairs), alerts=tuple(alerts)
    )


# ---------------------------------------------------------------------------
# 自由生成を減らす道具（決定的変換）
# ---------------------------------------------------------------------------

# 質問 → 検索カテゴリ の対応表。基盤モデルに分類させず、**表引きで決める**。
# 決定的なので再現でき、誤った分類が「もっともらしい文章」で隠れることもない
CATEGORY_TERMS: dict[str, tuple[str, ...]] = {
    "人事": ("有給休暇", "在宅勤務", "資格", "休暇", "勤怠"),
    "経費": ("出張", "宿泊費", "旅費", "交際費", "備品", "精算", "経費"),
    "IT": ("パスワード", "VPN", "PC", "接続", "ポータル"),
    "セキュリティ": ("機密", "格付け", "インシデント", "漏えい", "生成AI"),
}


def to_category(question: str) -> str | None:
    """カテゴリを決定的に決める。決まらなければ `None`（絞り込まない）。"""
    for category, terms in CATEGORY_TERMS.items():
        if any(term in question for term in terms):
            return category
    return None


# ---------------------------------------------------------------------------
# パイプライン
# ---------------------------------------------------------------------------


class SafetyPipeline:
    """4層をこの順で通す。**層を外せる**ようにしてあるのは実験のためです。

    比喩でいえば空港の保安検査です。搭乗券の確認・手荷物の X 線・金属探知・
    搭乗口の照合は、どれも1つでは足りず、どれも同じものを見ていません。
    「金属探知があるから手荷物検査は要らない」とは誰も言いません。
    """

    def __init__(
        self,
        *,
        runtime=None,
        agent=None,
        use_pre_filter: bool = True,
        use_input_guardrail: bool = True,
        grounding_threshold: float | None = None,
    ) -> None:
        self.runtime = runtime if runtime is not None else clients.bedrock_runtime()
        self.agent = agent if agent is not None else clients.agent_runtime()
        self.use_pre_filter = use_pre_filter
        self.use_input_guardrail = use_input_guardrail
        self.grounding_threshold = grounding_threshold

    def handle(self, question: str) -> Outcome:
        trail: list[str] = []
        repairs: list[str] = []
        alerts: list[str] = []
        text = question

        def blocked(result: LayerResult, *, model_called: bool) -> Outcome:
            return Outcome(
                layer=result.layer,
                decision="block",
                reason=result.reason,
                text=result.text or SAFE_FALLBACK,
                repairs=tuple(repairs),
                alerts=tuple(alerts),
                model_called=model_called,
                trail=trail,
            )

        if self.use_pre_filter:
            l1 = pre_filter(text)
            trail.append(l1.line())
            repairs += list(l1.repairs)
            if l1.blocked:
                return blocked(l1, model_called=False)
            text = l1.text

        if self.use_input_guardrail:
            l2 = input_guardrail(self.runtime, text)
            trail.append(l2.line())
            repairs += list(l2.repairs)
            alerts += list(l2.alerts)
            if l2.blocked:
                return blocked(l2, model_called=False)
            text = l2.text

        # 検索 → プロンプト組み立て → 1回だけ呼ぶ（ここまで来て初めて課金が発生する）
        sources = self.retrieve(text)
        answer = self.call_model(text, sources)

        l3 = post_check(
            answer, sources, question=text, threshold=self.grounding_threshold
        )
        trail.append(l3.line())
        if l3.blocked:
            out = blocked(l3, model_called=True)
            out.raw_answer, out.sources = answer, sources
            return out

        l4 = response_filter(l3.text)
        trail.append(l4.line())
        repairs += list(l4.repairs)
        alerts += list(l4.alerts)
        if l4.blocked:
            out = blocked(l4, model_called=True)
            out.raw_answer, out.sources = answer, sources
            return out

        return Outcome(
            layer="allow",
            decision="allow",
            reason="ok",
            text=l4.text,
            repairs=tuple(repairs),
            alerts=tuple(alerts),
            model_called=True,
            raw_answer=answer,
            sources=sources,
            trail=trail,
        )

    def retrieve(self, question: str) -> list[str]:
        """セッション5の入口をそのまま使う。カテゴリは決定的変換で決める。"""
        query = retriever.to_keywords(question) or question
        hits = retriever.search(
            self.agent,
            query,
            mode="HYBRID",
            top_k=TOP_K,
            category=to_category(question),
        )
        return [hit["text"] for hit in hits]

    def call_model(self, question: str, sources: list[str]) -> str:
        """`guardrailConfig` は**あえて渡しません**（解説3の理由）。"""
        response = self.runtime.converse(
            modelId=MODEL_ID,
            system=SYSTEM_BLOCKS,
            messages=[
                {
                    "role": "user",
                    "content": registry.render_user(
                        question, context_text="\n".join(sources)
                    ),
                }
            ],
            inferenceConfig={"maxTokens": 400, "temperature": 0.0},
        )
        return registry.text_of(response)


# ---------------------------------------------------------------------------
# 演習の本体
# ---------------------------------------------------------------------------


def main() -> None:
    import attack_set

    pipe = SafetyPipeline()

    print("=== 1. 正常な質問は4層すべてを通る ===")
    out = pipe.handle(attack_set.by_id("P23").text)
    for line in out.trail:
        print(f"  {line}")
    print(f"  回答（1行目）: {out.text.splitlines()[0]}")

    print()
    print("=== 2. 層ごとに何を止めたか ===")
    for probe_id in ("P02", "P06", "P11", "P16", "P19", "P22"):
        probe = attack_set.by_id(probe_id)
        result = pipe.handle(probe.text)
        print(
            f"  {probe_id} {result.layer} {result.reason}"
            f" repairs={','.join(result.repairs) or '-'}"
        )

    print()
    print("=== 3. 前処理の正規化を外すと、ガードレールが取り逃す ===")
    probe = attack_set.by_id("P06")
    with_pre = pipe.handle(probe.text)
    without_pre = SafetyPipeline(use_pre_filter=False).handle(probe.text)
    print(f"  L1 あり: {with_pre.layer} {with_pre.reason}")
    print(f"  L1 なし: {without_pre.layer} {without_pre.reason}")


if __name__ == "__main__":
    main()
