"""1週間の献立を決める関数（こんだてAI のツール plan_week。入出力は {days: [{date, recipe_ids}]}）。

同じ利用者・同じ日の番号・同じ開始日なら、必ず同じ献立を返す（乱数も現在時刻も使わない）。
そのため、worker が途中で落ちて同じジョブをやり直しても、日ごとの結果は変わらない。
"""

from __future__ import annotations

from datetime import date, timedelta

from kondate.data import load_recipes, load_users


class UnknownUser(Exception):
    """ジョブの利用者が見つからない。何度やり直しても直らない（恒久的な失敗）。"""


def find_user(user_id: str) -> dict:
    for user in load_users():
        if user["id"] == user_id:
            return user
    raise UnknownUser(user_id)


def ranked(user: dict, kinds: set[str]) -> list[dict]:
    """kinds の区分のうち、アレルギーの原材料を含まないレシピ。好みのタグが多い順 → 調理時間 → id の順。"""
    allergies, prefs = set(user["allergies"]), set(user["preferences"])
    ok = [r for r in load_recipes() if kinds & set(r["tags"]) and not allergies & set(r["allergens"])]
    return sorted(ok, key=lambda r: (-len(prefs & set(r["tags"])), r["minutes"], r["id"]))


def plan_day(user: dict, index: int, start: date) -> dict:
    """index 日目（0 始まり）の献立：主菜1品と、副菜か汁物1品。"""
    mains, sides = ranked(user, {"主菜"}), ranked(user, {"副菜", "汁物"})
    return {"date": (start + timedelta(days=index)).isoformat(),
            "recipe_ids": [mains[index % len(mains)]["id"], sides[index % len(sides)]["id"]]}


def build_plan(user: dict, days: int, start: date) -> dict:
    """ジョブを使わずに一度に作った場合の結果（検証で worker の結果と比べる）。"""
    return {"days": [plan_day(user, i, start) for i in range(days)]}
