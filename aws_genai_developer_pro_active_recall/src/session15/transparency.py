#!/usr/bin/env python3
"""セッション15: 透明性の実装（出力契約・確信度・推論トレース）。

    docker compose exec app python src/session15/transparency.py

「透明性がある」を気分で終わらせないために、**機械が判定できる形**に落とします。
本章の透明性は次の3つを封筒（エンベロープ）に詰めることです。

    根拠      どの資料のどの版を引いたか（uri / docId / revision）
    確信度    何をもってその値にしたか（引用の裏取りから機械で決める）
    経路      どの段を通って作られたか（推論トレース）

**確信度はモデルに自己申告させません。** 申告された確信度は検証できないので、
契約検査で必ず落とします。代わりに使うのは「回答の文が、引いた資料に本当に
書いてあるか」という裏取り（`support_ratio`）です。

セッション14の説明責任ログ（`provenance`）は**そのまま使います**。本章が足すのは
上位の欄（`LOG_EXTENSION_FIELDS`）だけで、前の章の契約は1つも変えません。
"""

from __future__ import annotations

import json
import re
import sys

sys.path.insert(0, "/workspace")
for _dir in ("session04", "session05", "session06", "session14", "session15"):
    sys.path.insert(0, f"/workspace/src/{_dir}")

from awskit import clients  # noqa: E402

import prompt_registry as registry  # noqa: E402  セッション6（版・差し込み・契約検査）

import provenance  # noqa: E402  セッション14（説明責任ログ・1件の処理）

MODEL_ID = provenance.PRIMARY_MODEL
MAX_TOKENS = 300

# 差し戻し時に**指示側へ**足す一文。利用者のメッセージは書き換えない
# （書き換えると「利用者が何を聞いたか」が記録から消える）
REPAIR_INSTRUCTION = (
    "# 差し戻し\n"
    "直前の出力は出力契約に違反しました。次の3点を必ず守って書き直してください。\n"
    "1. 渡された資料の文をそのまま引いて答えます。\n"
    "2. 資料に無いことは書きません。\n"
    "3. 引ける資料が無い場合は、答えられないことだけを述べます。"
)

# 確信度の重み。**合計を 0.9 にしてあります**（上限を 1.0 にしない）。
# 「資料にそう書いてある」ことは確かめられても、「その資料が正しい」ことは
# 確かめていないためです。1.0 を出せる仕組みは、出せないことを隠しています。
WEIGHTS = {"support": 0.5, "grounded": 0.2, "citations": 0.2}
LABEL_THRESHOLDS = (("high", 0.7), ("medium", 0.4), ("low", 0.0))

# 引用は3件そろって満点にする（1件だけで断言させない）
EXPECTED_CITATIONS = 3

# 説明責任ログに**上位で足す**欄。S14 の欄名と1つも衝突させない
LOG_EXTENSION_FIELDS = (
    "confidence",
    "confidenceLabel",
    "supportRatio",
    "reviewRequired",
    "contractViolations",
    "traceSteps",
    "transparencyOutcome",
)

# 契約違反の種別。**文言ではなく符号で扱う**（監視で数えるため）
VIOLATION_CODES = (
    "schema",
    "unknown-citation",
    "support-mismatch",
    "confidence-mismatch",
    "label-mismatch",
    "review-flag-mismatch",
    "unsupported-answer",
)


# ---------------------------------------------------------------------------
# 出力契約（JSON Schema）
# ---------------------------------------------------------------------------

CITATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["uri", "docId", "revision", "score"],
    "properties": {
        "uri": {"type": "string", "minLength": 1},
        "docId": {"type": "string", "minLength": 1},
        "revision": {"type": "string", "minLength": 1},
        # 検索スコアは**類似度**です。確率ではないので負の値も許します
        # （だからこそ、そのまま確信度として利用者に見せてはいけません）
        "score": {"type": "number", "minimum": -1.0, "maximum": 1.0},
    },
}

TRACE_STEP_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["step", "detail"],
    "properties": {
        "step": {"type": "string", "minLength": 1},
        "detail": {"type": "string", "minLength": 1},
    },
}

ANSWER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "traceId",
        "answer",
        "citations",
        "confidence",
        "confidenceLabel",
        "supportRatio",
        "modelId",
        "promptVersion",
        "reviewRequired",
        "trace",
    ],
    "properties": {
        "traceId": {"type": "string", "minLength": 1},
        "answer": {"type": "string", "minLength": 1},
        # **1件以上**。引用ゼロの回答を運べる封筒を作らないことが契約の要点
        "citations": {"type": "array", "minItems": 1, "items": CITATION_SCHEMA},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "confidenceLabel": {"enum": ["high", "medium", "low"]},
        "supportRatio": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "modelId": {"type": "string", "minLength": 1},
        "promptVersion": {"type": "number", "minimum": 1},
        "reviewRequired": {"type": "boolean"},
        "trace": {"type": "array", "minItems": 1, "items": TRACE_STEP_SCHEMA},
    },
}


def violations(value, schema: dict, path: str = "$") -> list[str]:
    """スキーマ1枚から検査する（検査規則を別に手書きしない）。

    実務では `jsonschema` や Pydantic にこの役をやらせます。ここで小さく自作するのは
    **契約の置き場を1つにする**という設計判断を手触りで見せるためです。
    検査を手書きすると、スキーマと検査が二重管理になり、必ず片方が古くなります。
    """
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            return [f"{path}: オブジェクトではありません"]
        found: list[str] = []
        for key in schema.get("required", ()):
            if key not in value:
                found.append(f"{path}.{key}: 必須の欄がありません")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in schema.get("properties", {}):
                    found.append(f"{path}.{key}: 契約に無い欄です")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                found += violations(value[key], sub, f"{path}.{key}")
        return found
    if kind == "array":
        if not isinstance(value, list):
            return [f"{path}: 配列ではありません"]
        found = []
        minimum = schema.get("minItems", 0)
        if len(value) < minimum:
            found.append(f"{path}: 要素が {minimum} 件未満です（{len(value)} 件）")
        item = schema.get("items")
        if item is not None:
            for index, element in enumerate(value):
                found += violations(element, item, f"{path}[{index}]")
        return found

    found = []
    if kind == "string":
        if not isinstance(value, str):
            return [f"{path}: 文字列ではありません"]
        if len(value) < schema.get("minLength", 0):
            found.append(f"{path}: 空です")
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return [f"{path}: 数値ではありません"]
        if "minimum" in schema and value < schema["minimum"]:
            found.append(f"{path}: {value} は下限 {schema['minimum']} を下回ります")
        if "maximum" in schema and value > schema["maximum"]:
            found.append(f"{path}: {value} は上限 {schema['maximum']} を超えます")
    elif kind == "boolean":
        if not isinstance(value, bool):
            return [f"{path}: 真偽値ではありません"]
    if "enum" in schema and value not in schema["enum"]:
        found.append(f"{path}: {value!r} は {list(schema['enum'])} 以外です")
    return found


# ---------------------------------------------------------------------------
# 引用の裏取りと確信度
# ---------------------------------------------------------------------------

_TRAILER = re.compile(r"\n*（根拠:.*?）\s*$", re.DOTALL)
_SENTENCE_SPLIT = re.compile(r"(?<=[。．.!?！？])")


def evidence_span(answer: str) -> str:
    """回答から「資料の文をそのまま引いた部分」を取り出す。

    実 AWS では `RetrieveAndGenerate` の `citations[].generatedResponsePart.span`
    が「回答のどこがどの出典に対応するか」を返します。同梱モックはマーカーの
    後ろに資料の文を並べるので、前置きと末尾の注記を落として同じ形にします。
    """
    body = _TRAILER.sub("", answer.strip())
    if body.startswith(registry.GROUNDING_MARKER):
        body = body[len(registry.GROUNDING_MARKER) :].lstrip("、,： : ")
    return body


def support_ratio(answer: str, sources: str) -> float:
    """回答の文のうち、引いた資料に**実際に書いてある**文の割合。

    「出典を添えたか」ではなく「添えた出典がその文を支えているか」を見ます。
    出典欄だけ埋めて中身は作り話、という壊れ方は出典の有無では捕まりません。
    """
    body = evidence_span(answer)
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(body) if len(s.strip()) >= 6]
    if not sentences or not sources:
        return 0.0
    hit = sum(1 for sentence in sentences if sentence in sources)
    return round(hit / len(sentences), 4)


def confidence_of(*, citations: list, grounded: bool, support: float) -> tuple[float, str]:
    """確信度を**機械で決める**。モデルの自己申告は使わない。

    3つの観測できる値だけから作ります（だから後から再計算して照合できます）。

        support   回答の文が資料に見つかった割合
        grounded  根拠に基づいて答えた形式になっているか
        citations 引用が想定どおりの件数そろっているか
    """
    coverage = min(len(citations), EXPECTED_CITATIONS) / EXPECTED_CITATIONS
    value = round(
        WEIGHTS["support"] * support
        + WEIGHTS["grounded"] * (1.0 if grounded else 0.0)
        + WEIGHTS["citations"] * coverage,
        2,
    )
    label = next(name for name, floor in LABEL_THRESHOLDS if value >= floor)
    return value, label


# ---------------------------------------------------------------------------
# 封筒の組み立て
# ---------------------------------------------------------------------------


def _step(name: str, detail: object) -> dict:
    return {"step": name, "detail": str(detail) or "-"}


def build_envelope(
    *,
    trace_id: str,
    answer: str,
    citations: list[dict],
    model_id: str,
    prompt_version: int,
    sources: str,
    trace: list[dict],
) -> dict:
    """出力契約に沿った封筒を作る。**確信度はここで計算する。**"""
    support = support_ratio(answer, sources)
    grounded = registry.GROUNDING_MARKER in answer
    value, label = confidence_of(citations=citations, grounded=grounded, support=support)
    return {
        "traceId": trace_id,
        "answer": answer,
        "citations": [
            {
                "uri": citation["uri"],
                "docId": citation["docId"],
                "revision": citation["revision"],
                "score": citation["score"],
            }
            for citation in citations
        ],
        "confidence": value,
        "confidenceLabel": label,
        "supportRatio": support,
        "modelId": model_id,
        "promptVersion": prompt_version,
        # high 以外は人の確認を要求する。**確信度は「そのまま使ってよいか」の判断材料**
        "reviewRequired": label != "high",
        "trace": list(trace),
    }


def contract_violations(
    envelope: dict, *, allowed_uris: set[str], sources: str
) -> list[dict]:
    """契約違反を列挙する。スキーマで表せない整合もここで見る。

    スキーマは「形」しか表せません。「引用が検索結果に無い URI だ」「確信度が
    再計算値と違う」は**欄をまたぐ整合**なので、スキーマの外で検査します。
    """
    found = [
        {"code": "schema", "detail": detail}
        for detail in violations(envelope, ANSWER_SCHEMA)
    ]
    answer = envelope.get("answer") or ""
    citations = envelope.get("citations") or []

    for citation in citations:
        uri = citation.get("uri") if isinstance(citation, dict) else None
        if uri not in allowed_uris:
            # モデルが出典を書き足しても、検索層が返さなかった URI は通さない
            found.append({"code": "unknown-citation", "detail": str(uri)})

    support = support_ratio(answer, sources)
    grounded = registry.GROUNDING_MARKER in answer
    value, label = confidence_of(citations=citations, grounded=grounded, support=support)
    if envelope.get("supportRatio") != support:
        found.append(
            {"code": "support-mismatch", "detail": f"再計算は {support} です"}
        )
    if envelope.get("confidence") != value:
        found.append(
            {"code": "confidence-mismatch", "detail": f"再計算は {value} です"}
        )
    if envelope.get("confidenceLabel") != label:
        found.append({"code": "label-mismatch", "detail": f"再計算は {label} です"})
    if envelope.get("reviewRequired") != (label != "high"):
        found.append(
            {"code": "review-flag-mismatch", "detail": "確信度と人の確認要否が食い違います"}
        )
    if support == 0.0:
        found.append(
            {"code": "unsupported-answer", "detail": "回答の文が引いた資料に見つかりません"}
        )
    return found


def for_user(envelope: dict) -> dict:
    """利用者に見せる形。**透明性は「全部見せる」ではありません。**

    数値の確信度をそのまま出すと「0.62 なら6割正しい」と読まれます。利用者には
    ラベルと「人の確認が必要か」を出し、数値は監視と監査の側に残します。
    """
    return {
        "answer": envelope["answer"],
        "sources": [
            {"docId": citation["docId"], "uri": citation["uri"]}
            for citation in envelope["citations"]
        ],
        "confidence": envelope["confidenceLabel"],
        "reviewRequired": envelope["reviewRequired"],
        "steps": [step["step"] for step in envelope["trace"]],
    }


def log_extension(result: dict) -> dict:
    """説明責任ログに足す欄。**本文は1文字も入れない**（S14 の約束）。"""
    envelope = result.get("envelope") or {}
    return {
        "confidence": envelope.get("confidence", 0.0),
        "confidenceLabel": envelope.get("confidenceLabel", "low"),
        "supportRatio": envelope.get("supportRatio", 0.0),
        "reviewRequired": bool(envelope.get("reviewRequired", True)),
        "contractViolations": sorted(
            {code for attempt in result["attempts"] for code in attempt["violations"]}
        ),
        # 段の**名前だけ**。detail は部門やモデル ID を含むのでここには入れない
        "traceSteps": [step["step"] for step in result["trace"]],
        "transparencyOutcome": result["outcome"],
    }


# ---------------------------------------------------------------------------
# 1件の応答（契約検査つき）
# ---------------------------------------------------------------------------

SCENARIOS = [
    {"id": "rai-001", "department": "人事部", "category": "人事",
     "question": "有給休暇の繰越上限は何日ですか。"},
    {"id": "rai-002", "department": "情報システム部", "category": "IT",
     "question": "パスワードのリセットにはどの認証が必要ですか。"},
    # 該当分類の文書が1件も無い（＝引用ゼロ。封筒を作らずに人へ回す）
    {"id": "rai-003", "department": "情報システム部", "category": "法務",
     "question": "駐車場の月極料金はいくらですか。"},
    # ガードレールが入口で止める（基盤モデルを1回も呼ばない）
    {"id": "rai-004", "department": "経理部", "category": "経費",
     "question": "余剰資金で仮想通貨に投資してもよいですか。"},
    # **検索を通さない経路**。あってはいけない経路が契約検査で必ず落ちることを見る
    {"id": "rai-005", "department": "人事部", "category": "人事",
     "question": "有給休暇の繰越上限は何日ですか。", "evidence": False},
    # 資料はあるが答えが無い（作り話をせず「答えられない」と述べる）
    {"id": "rai-006", "department": "情報システム部", "category": "IT",
     "question": "駐車場の月極料金はいくらですか。"},
]


def generate(
    runtime,
    template: dict,
    *,
    question: str,
    context_text: str | None,
    params: dict,
    repair: bool = False,
    model_id: str = MODEL_ID,
) -> str:
    """1回の生成。差し戻しの指示は**system 側**に足す。"""
    system = registry.render_system(template, params)
    if repair:
        system = system + [{"text": REPAIR_INSTRUCTION}]
    response = runtime.converse(
        modelId=model_id,
        system=system,
        messages=[
            {"role": "user", "content": registry.render_user(question, context_text=context_text)}
        ],
        inferenceConfig={"maxTokens": MAX_TOKENS, "temperature": 0.0},
    )
    return registry.text_of(response)


def _result(
    scenario: dict,
    outcome: str,
    *,
    reason: str,
    trace: list[dict],
    entry: dict | None = None,
    envelope: dict | None = None,
    answer: str | None = None,
    sources: str = "",
    citations: list[dict] | None = None,
    attempts: list[dict] | None = None,
) -> dict:
    return {
        "id": scenario["id"],
        "department": scenario["department"],
        "outcome": outcome,
        "reason": reason,
        "trace": trace,
        "entry": entry,
        "envelope": envelope,
        "answer": answer,
        "sources": sources,
        "citations": citations or [],
        "attempts": attempts or [],
    }


def respond(
    scenario: dict, *, runtime, agent, ddb, s3, with_evidence: bool = True, max_attempts: int = 2
) -> dict:
    """1件に答え、契約を検査し、直らなければ人へ回す。

    結末は5つです（監視はこの5値を数えるだけで成り立ちます）。

        answered   1回目で契約を満たした
        repaired   差し戻して契約を満たした
        escalated  資料に答えが無い／契約違反が直らない → 人へ
        no_citation 引用が引けない → 封筒を作らない
        blocked    入口のガードレールが止めた
    """
    trace = [_step("intake", f"{scenario['department']} / {scenario['id']}")]
    version, template, _checksum = registry.load_approved(s3, provenance.PROMPT_NAME)
    params = {
        "department": scenario["department"],
        "max_sentences": provenance.MAX_SENTENCES,
    }
    entry: dict | None = None

    if with_evidence:
        # セッション14の1件処理をそのまま使う（説明責任ログの1行が同時に出来る）
        entry, text = provenance.answer(
            scenario, runtime=runtime, agent=agent, ddb=ddb, s3=s3
        )
        trace.append(_step("guardrail-input", entry["guardrailAction"]))
        if entry["outcome"] == "blocked":
            # 検索も生成も走っていない。**通っていない段をトレースに書かない。**
            trace.append(_step("stop", "入口で止めた（検索も生成もしない）"))
            return _result(scenario, "blocked", reason="guardrail-input", trace=trace, entry=entry)
        trace.append(_step("retrieve", f"{entry['citationCount']} 件の引用"))
        if entry["outcome"] == "no_citation":
            trace.append(_step("stop", "引用が無いので封筒を作らない"))
            return _result(scenario, "no_citation", reason="no-evidence", trace=trace, entry=entry)
        citations, sources = provenance.retrieve_citations(agent, ddb, scenario)
        if registry.REFUSAL_MARKER in text:
            trace.append(_step("stop", "資料に答えが無いと応答した"))
            return _result(
                scenario, "escalated", reason="no-answer-in-docs", trace=trace,
                entry=entry, answer=text, sources=sources, citations=citations,
            )
    else:
        citations, sources = [], ""
        trace.append(_step("skip-retrieve", "検索を通していない（あってはいけない経路）"))
        text = generate(
            runtime, template, question=scenario["question"], context_text=None, params=params
        )

    attempts: list[dict] = []
    steps = trace
    for attempt in range(1, max_attempts + 1):
        steps = list(trace) + [_step("generate", f"{MODEL_ID}（試行 {attempt}）")]
        envelope = build_envelope(
            trace_id=scenario["id"],
            answer=text,
            citations=citations,
            model_id=MODEL_ID,
            prompt_version=version,
            sources=sources,
            trace=steps,
        )
        found = contract_violations(
            envelope, allowed_uris={c["uri"] for c in citations}, sources=sources
        )
        attempts.append({"attempt": attempt, "violations": sorted(v["code"] for v in found)})
        if not found:
            return _result(
                scenario,
                "answered" if attempt == 1 else "repaired",
                reason="contract-ok",
                trace=steps,
                entry=entry,
                envelope=envelope,
                answer=text,
                sources=sources,
                citations=citations,
                attempts=attempts,
            )
        if attempt < max_attempts:
            text = generate(
                runtime, template, question=scenario["question"],
                context_text=sources or None, params=params, repair=True,
            )
    return _result(
        scenario, "escalated", reason="contract-violation",
        trace=steps + [_step("stop", "契約違反が直らないので人へ回す")],
        entry=entry, answer=text, sources=sources, citations=citations, attempts=attempts,
    )


def run_all(*, runtime=None, agent=None, ddb=None, s3=None) -> dict[str, dict]:
    """6件を流す。**封筒を作らない結末も含めて**同じ入口で扱う。"""
    runtime = runtime or clients.bedrock_runtime()
    agent = agent or clients.agent_runtime()
    if ddb is None or s3 is None:
        state = provenance.bootstrap()
        ddb, s3 = state["ddb"], state["s3"]
    results: dict[str, dict] = {}
    for scenario in SCENARIOS:
        results[scenario["id"]] = respond(
            scenario,
            runtime=runtime,
            agent=agent,
            ddb=ddb,
            s3=s3,
            with_evidence=scenario.get("evidence", True),
        )
    return results


def line(result: dict) -> str:
    envelope = result.get("envelope") or {}
    return (
        f"{result['id']} outcome={result['outcome']:<12}"
        f" reason={result['reason']:<20}"
        f" confidence={envelope.get('confidenceLabel', '-'):<7}"
        f" 違反={[c for a in result['attempts'] for c in a['violations']]}"
    )


def main() -> None:
    state = provenance.bootstrap()
    results = run_all(ddb=state["ddb"], s3=state["s3"])

    print("=== 1. 6件を流す ===")
    for result in results.values():
        print(" ", line(result))

    good = results["rai-001"]
    print()
    print("=== 2. 利用者に見せる形（数値の確信度は出さない） ===")
    print(json.dumps(for_user(good["envelope"]), ensure_ascii=False, indent=2))

    print()
    print("=== 3. 説明責任ログに足す欄（本文は入れない） ===")
    print(json.dumps(log_extension(good), ensure_ascii=False))

    print()
    print("=== 4. 契約違反を作って検出させる ===")
    allowed = {c["uri"] for c in good["citations"]}
    sources = good["sources"]
    samples = {
        "出典を差し替えた": tamper(good["envelope"], citations_uri="s3://sample-shoji-docs/hr/paid-leave-v9.md"),
        "確信度を自己申告した": tamper(good["envelope"], confidence=0.95),
        "契約に無い欄を足した": tamper(good["envelope"], extra=True),
        "引用を空にした": tamper(good["envelope"], citations=[]),
    }
    for label, broken in samples.items():
        codes = sorted({v["code"] for v in contract_violations(broken, allowed_uris=allowed, sources=sources)})
        print(f"  {label}: {codes}")

    print()
    print("=== 5. 検索を外した経路は必ず落ちる ===")
    bad = results["rai-005"]
    print(f"  結末: {bad['outcome']} / 理由: {bad['reason']}")
    for attempt in bad["attempts"]:
        print(f"    試行{attempt['attempt']}: {attempt['violations']}")


def tamper(
    envelope: dict,
    *,
    citations_uri: str | None = None,
    confidence: float | None = None,
    extra: bool = False,
    citations: list | None = None,
) -> dict:
    """封筒を1箇所だけ壊す（検査器の効きを確かめるため）。"""
    broken = json.loads(json.dumps(envelope, ensure_ascii=False))
    if citations_uri is not None:
        broken["citations"][0]["uri"] = citations_uri
    if confidence is not None:
        broken["confidence"] = confidence
    if extra:
        broken["internalNote"] = "社内メモ"
    if citations is not None:
        broken["citations"] = citations
    return broken


if __name__ == "__main__":
    main()
