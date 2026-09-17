"""LLM-as-a-judge（LLM に採点させる自動評価）。

judge も 1 つの LLM アプリであり、バイアスを持ち、壊れる。だからここでも
呼び出し口は LLMClient に固定し、スタブや記録再生に差し替えられるように
しておく（judge のテストを judge 抜きで書けるようにする、が要点）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from evalkit.client import LLMClient

DEFAULT_RUBRIC = """\
1. 質問に直接答えているか（答えていない場合は 2 点以下）
2. 事実と異なる内容を含まないか（含む場合は 2 点以下）
3. 指定された形式・長さを守っているか
4. 不要な前置きや繰り返しがないか"""

JUDGE_SYSTEM = """\
あなたは LLM アプリの出力を採点する厳格な評価者です。
採点基準にのみ従い、回答の長さや流暢さに引きずられないでください。
出力は必ず指定された JSON だけを返してください。"""

JUDGE_TEMPLATE = """\
<採点基準>
{rubric}
</採点基準>

<質問>
{question}
</質問>

<回答>
{answer}
</回答>

上の回答を 1〜5 点で採点してください。
5 = 基準をすべて満たす / 3 = 一部満たさない / 1 = 基準を満たさない

次の JSON のみを出力してください。
{{"score": <1-5 の整数>, "reason": "<50 文字以内の根拠>"}}"""


@dataclass(frozen=True)
class JudgeVerdict:
    """judge の判定結果。パースできなかった場合も情報を落とさず残す。"""

    score: int
    reason: str
    parsed: bool = True
    raw: str = ""


def _extract_json(text: str) -> dict | None:
    """本文に混ざった JSON を取り出す（judge は前置きを付けてくることがある）。"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def judge_pointwise(
    client: LLMClient,
    question: str,
    answer: str,
    rubric: str | None = None,
) -> JudgeVerdict:
    """1 件の回答をルーブリックに従って 1〜5 点で採点する。"""
    prompt = JUDGE_TEMPLATE.format(
        rubric=rubric or DEFAULT_RUBRIC,
        question=question,
        answer=answer,
    )
    response = client.complete(prompt, system=JUDGE_SYSTEM)
    payload = _extract_json(response.text)

    if payload is None or "score" not in payload:
        # judge が壊れたことを「最低点」で隠してはいけない。パース失敗として扱う
        return JudgeVerdict(score=0, reason="judge 出力のパースに失敗", parsed=False, raw=response.text)

    try:
        score = int(payload["score"])
    except (TypeError, ValueError):
        return JudgeVerdict(score=0, reason="score が整数でない", parsed=False, raw=response.text)

    score = max(1, min(5, score))
    return JudgeVerdict(
        score=score,
        reason=str(payload.get("reason", ""))[:100],
        parsed=True,
        raw=response.text,
    )


def judge_pairwise_debiased(
    client: LLMClient,
    question: str,
    answer_a: str,
    answer_b: str,
) -> str:
    """A/B 比較を順序を入れ替えて 2 回行い、位置バイアスを打ち消す。

    戻り値は "A" / "B" / "tie"。2 回の判定が食い違ったら "tie" とする
    （= その比較は judge にとって判別できていない、という情報になる）。
    """
    first = _pairwise_once(client, question, answer_a, answer_b)
    second = _pairwise_once(client, question, answer_b, answer_a)
    # 2 回目は順序が逆なので、勝者ラベルを元の並びに読み替える
    second_mapped = {"1": "B", "2": "A"}.get(second, "tie")
    first_mapped = {"1": "A", "2": "B"}.get(first, "tie")
    return first_mapped if first_mapped == second_mapped else "tie"


def _pairwise_once(client: LLMClient, question: str, first: str, second: str) -> str:
    prompt = (
        f"<質問>\n{question}\n</質問>\n\n"
        f"<回答1>\n{first}\n</回答1>\n\n"
        f"<回答2>\n{second}\n</回答2>\n\n"
        '優れている方を選び {"winner": "1" または "2"} の JSON のみを出力してください。'
    )
    payload = _extract_json(client.complete(prompt, system=JUDGE_SYSTEM).text)
    if payload is None:
        return "tie"
    return str(payload.get("winner", "tie"))
