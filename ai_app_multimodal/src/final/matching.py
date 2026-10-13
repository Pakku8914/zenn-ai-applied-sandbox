"""抽出結果と正解データの照合（セッション12の matching.py の写し）。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from src.final.gold import Gold
from src.final.textnorm import normalize_relaxed

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
    predicted: int
    gold: int
    matched: int
    fields_checked: int
    fields_correct: int
    errors: tuple[str, ...]

    @property
    def exact(self) -> bool:
        return self.predicted == self.gold == self.matched and self.fields_checked == self.fields_correct


def fmt(value: object) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)


def score_case(case_id: str, gold: Gold, pred: dict, norm: Callable[[str], str] = norm_name) -> CaseScore:
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

    free = list(range(len(gold.items)))
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
    return round(num / den, 4) if den else 1.0


def summarize(scores: Iterable[CaseScore]) -> dict:
    scores = list(scores)
    tp = sum(s.matched for s in scores)
    return {
        "cases": len(scores),
        "precision": ratio(tp, sum(s.predicted for s in scores)),
        "recall": ratio(tp, sum(s.gold for s in scores)),
        "field_accuracy": ratio(sum(s.fields_correct for s in scores), sum(s.fields_checked for s in scores)),
        "exact_match_rate": ratio(sum(s.exact for s in scores), len(scores)),
    }
