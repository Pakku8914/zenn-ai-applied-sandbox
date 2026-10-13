"""抽出結果と正解データの照合と、適合率・再現率・項目一致率・完全一致率（セッション12）。

照合の規則（本書で固定する値）：
- 名前：normalize_relaxed（NFKC・句読点と空白の除去・カタカナ→ひらがな・表記ゆれ）でそろえてから比べる
- 1対1：予測を上から順に見て、まだ組になっていない同じ名前の正解と組にする。同じ名前の2件目は「余計」
- 数量（amount）：正解との差が正解の 10% 以内なら一致（個数のような整数では実質ぴったり）
- 個数（quantity）・金額（price・total）：ぴったり一致。お金に許容誤差は置かない
- 購入日（purchased_at）：YYYY-MM-DD の文字列がぴったり一致（形が違えば誤り）
- 店名（store）：名前と同じ正規化で比べる
- 正解の値が None の項目は採点しない
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from src.session12.gold import Gold
from src.session12.textnorm import normalize_relaxed

AMOUNT_REL_TOL = 0.10


def norm_name(text: str) -> str:
    return normalize_relaxed(text)


def amount_ok(pred: float, gold: float) -> bool:
    return abs(pred - gold) <= AMOUNT_REL_TOL * gold


def same(pred: object, gold: object) -> bool:
    return pred == gold


FIELD_RULES: dict[str, Callable[[object, object], bool]] = {
    "amount": amount_ok,
    "quantity": same,
    "price": same,
    "total": same,
    "purchased_at": same,
    "store": lambda p, g: norm_name(p) == norm_name(g),
}


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    predicted: int        # 予測の件数
    gold: int             # 正解の件数
    matched: int          # 名前で組になった件数（TP）
    fields_checked: int   # 採点した項目の数（組になった品目の項目＋全体の項目）
    fields_correct: int   # そのうち一致した数
    errors: tuple[str, ...]

    @property
    def exact(self) -> bool:
        """余計も見逃しもなく、採点した項目がすべて一致した。"""
        return self.predicted == self.gold == self.matched and self.fields_checked == self.fields_correct


def fmt(value: object) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)


def score_case(case_id: str, gold: Gold, pred: dict, norm: Callable[[str], str] = norm_name) -> CaseScore:
    """pred は {"items": [{name, …}], "header": {…}}。誤りは「全体の項目 → 品目の項目 → 余計 → 見逃し」の順に並べる。"""
    errors: list[str] = []
    checked = correct = 0

    def judge(label: str, field: str, p: object, g: object) -> None:
        nonlocal checked, correct
        if g is None:
            return
        checked += 1
        if p is not None and FIELD_RULES[field](p, g):
            correct += 1
        else:
            errors.append(f"{label}{field}：{fmt(p)} ≠ {fmt(g)}")

    for field, g in gold.header.items():
        judge("", field, pred["header"].get(field), g)

    free = list(range(len(gold.items)))   # まだ組になっていない正解の位置
    extra: list[str] = []
    for p_item in pred["items"]:
        key = norm(p_item["name"])
        hit = next((i for i in free if norm(gold.items[i]["name"]) == key), None)
        if hit is None:
            extra.append(p_item["name"])
            continue
        free.remove(hit)
        g_item = gold.items[hit]
        for field, g in g_item.items():
            if field != "name":
                judge(f"{g_item['name']} の ", field, p_item.get(field), g)
    errors += [f"余計：{name}" for name in extra]
    errors += [f"見逃し：{gold.items[i]['name']}" for i in free]
    matched = len(gold.items) - len(free)
    return CaseScore(case_id, len(pred["items"]), len(gold.items), matched, checked, correct, tuple(errors))


def ratio(num: int, den: int) -> float:
    """分母が0なら 1.0（予測が0件なら「間違いも言っていない」。そのとき見逃しは再現率に出る）。"""
    return round(num / den, 4) if den else 1.0


def summarize(scores: Iterable[CaseScore]) -> dict:
    """全ケースの件数を足してから割る（ミクロ平均）。件数の多いケースほど重く数える。"""
    scores = list(scores)
    tp = sum(s.matched for s in scores)
    return {
        "cases": len(scores),
        "precision": ratio(tp, sum(s.predicted for s in scores)),
        "recall": ratio(tp, sum(s.gold for s in scores)),
        "field_accuracy": ratio(sum(s.fields_correct for s in scores), sum(s.fields_checked for s in scores)),
        "exact_match_rate": ratio(sum(s.exact for s in scores), len(scores)),
    }
