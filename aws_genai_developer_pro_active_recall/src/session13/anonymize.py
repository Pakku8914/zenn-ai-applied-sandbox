#!/usr/bin/env python3
"""セッション13: 保存の前に匿名化し、そして「検出の限界」を見えるようにする。

`ApplyGuardrail` を、生成そのものとは切り離して単体で呼びます。
保存経路には基盤モデル（FM）の呼び出しが1回もありません。

**このモジュールで最も大事なのは、伏せられたものの一覧ではなく
「伏せられなかったものの一覧」です。** 検出器は必ず取りこぼすため、
匿名化だけを頼りにした設計は成立しません。
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field

sys.path.insert(0, "/workspace")

from awskit import clients  # noqa: E402

GUARDRAIL_ID = "demo-guardrail"
GUARDRAIL_VERSION = "1"

# このガードレールが検出できるエンティティ（サンドボックスでは4種）。
# **氏名・住所・社員番号はここに無い＝検出されない。**
DETECTABLE = ("EMAIL", "PHONE", "CREDIT_DEBIT_CARD_NUMBER", "IP_ADDRESS")

# 自社の固定書式は自分で足す。検出器のカタログに無いものは自分で書くしかない
LOCAL_PATTERNS: dict[str, re.Pattern[str]] = {
    "EMPLOYEE_ID": re.compile(r"\b[A-Z]-\d{6}\b"),
    "CUSTOMER_CODE": re.compile(r"\bCUST-\d{5}\b"),
}

# 章を通して使う検証用の1ターン。PII を4種＋自社書式2種＋検出できない2種で作ってある
SAMPLE_TURN = (
    "格付け: 社内限定\n"
    "山田太郎（社員番号 A-100234）から連絡がありました。"
    "折り返し先は taro.yamada@example.co.jp、電話は 090-1234-5678 です。"
    "決済に使ったカードは 4111-1111-1111-1111、"
    "端末の IP アドレスは 192.168.10.24 でした。"
    "住所は東京都千代田区1-1-1、顧客コードは CUST-40217 です。"
)

# ガードレールで伏せられる断片（保存後にこれが残っていたら設計の失敗）
GUARDRAIL_NEEDLES = (
    "taro.yamada@example.co.jp",
    "090-1234-5678",
    "4111-1111-1111-1111",
    "192.168.10.24",
)

# 自社ルールを足して初めて伏せられる断片
LOCAL_NEEDLES = ("A-100234", "CUST-40217")

# どちらの機械的な検出でも伏せられない断片。**入力させない設計でしか守れない**
UNDETECTED_NEEDLES = ("山田太郎", "東京都千代田区1-1-1")


@dataclass
class Masked:
    """匿名化の結果。`entities` には原文の断片（`match`）が入っている点に注意。"""

    text: str
    entities: list[dict] = field(default_factory=list)
    intervened: bool = False

    def types(self) -> list[str]:
        return sorted({entity["type"] for entity in self.entities})

    def summary(self) -> dict:
        """記録に残してよい形。**`match`（原文の断片）を落とす。**

        検知の記録に原文を貼ると、匿名化した意味がなくなります
        （セッション3の「隔離には検知内容だけを残す」と同じ考え方）。
        """
        counts: dict[str, int] = {}
        for entity in self.entities:
            counts[entity["type"]] = counts.get(entity["type"], 0) + 1
        return {
            "piiTypes": sorted(counts),
            "piiCounts": counts,
            "piiTotal": len(self.entities),
        }


def anonymize(runtime, text: str) -> Masked:
    """ApplyGuardrail で PII を `{EMAIL}` のようなプレースホルダへ置き換える。"""
    response = runtime.apply_guardrail(
        guardrailIdentifier=GUARDRAIL_ID,
        guardrailVersion=GUARDRAIL_VERSION,
        source="INPUT",
        content=[{"text": {"text": text}}],
    )
    entities = [
        entity
        for assessment in response.get("assessments", [])
        for entity in assessment.get("sensitiveInformationPolicy", {}).get(
            "piiEntities", []
        )
    ]
    outputs = response.get("outputs") or []
    if response.get("action") == "GUARDRAIL_INTERVENED":
        # PII 以外のポリシー（拒否トピックなど）が反応した場合。本文は差し替わっている
        return Masked(outputs[0]["text"], entities, intervened=True)
    # 伏せる対象が無ければ `outputs` は空。そのときは元の本文が答え
    return Masked(outputs[0]["text"] if outputs else text, entities)


def mask_local(text: str) -> tuple[str, list[dict]]:
    """自社書式の識別子を自前で伏せる（ガードレールでは検出されない分）。"""
    masked = text
    found: list[dict] = []
    for name, pattern in LOCAL_PATTERNS.items():
        for match in pattern.finditer(text):
            found.append({"type": name, "match": match.group(0), "action": "ANONYMIZED"})
            masked = masked.replace(match.group(0), f"{{{name}}}")
    return masked, found


def mask_known(text: str, known: dict[str, str] | None) -> tuple[str, list[dict]]:
    """アプリが把握している値（フォームの氏名欄・住所欄など）をそのまま伏せる。

    検出器に当てるより確実です。**知っている値は、探さずに消せます。**
    """
    masked = text
    found: list[dict] = []
    for name, value in (known or {}).items():
        if value and value in masked:
            found.append({"type": name, "match": value, "action": "ANONYMIZED"})
            masked = masked.replace(value, f"{{{name}}}")
    return masked, found


def scrub(runtime, text: str, *, known: dict[str, str] | None = None) -> Masked:
    """三段で伏せる: ガードレール → 自社書式 → アプリが知っている値。"""
    result = anonymize(runtime, text)
    if result.intervened:
        # 本文が差し替わっているので、これ以上伏せるものはない
        return result
    text_after_local, local_found = mask_local(result.text)
    text_after_known, known_found = mask_known(text_after_local, known)
    return Masked(text_after_known, result.entities + local_found + known_found)


def residue(masked: str, needles) -> list[str]:
    """伏せたはずの断片が残っていないか。**残っていれば設計の失敗。**"""
    return [needle for needle in needles if needle in masked]


def main() -> None:
    runtime = clients.bedrock_runtime()

    guardrail_only = anonymize(runtime, SAMPLE_TURN)
    both = scrub(runtime, SAMPLE_TURN)

    print("=== 検出できたもの / できなかったもの ===")
    print(f"ガードレールが検出: {guardrail_only.types()}")
    print(f"ガードレールだけでは残る: {residue(guardrail_only.text, LOCAL_NEEDLES)}")
    print(f"自社ルールを足すと残らない: {residue(both.text, LOCAL_NEEDLES)}")
    print(f"どちらでも残る: {residue(both.text, UNDETECTED_NEEDLES)}")
    print(f"記録に残す形（原文の断片を含まない）: {both.summary()}")
    print()
    print("=== 三段目（アプリが知っている値）まで伏せた本文 ===")
    print(scrub(runtime, SAMPLE_TURN, known={"NAME": "山田太郎"}).text)


if __name__ == "__main__":
    main()
