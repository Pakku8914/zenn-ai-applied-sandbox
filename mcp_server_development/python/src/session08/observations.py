"""気象観測データの生成とページネーション用ヘルパー（Python 版）

TypeScript 版（node/src/session08/observations.ts）と同じ疑似乱数を使うため、
生成されるレコードも集計結果も 2 言語で一致します。
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

TOTAL_OBSERVATIONS = 100_000
#: 集計を何チャンクに分けるか（= 進捗通知の回数）
TOTAL_STEPS = 20

STATION_IDS = [
    "st-01", "st-02", "st-03", "st-04", "st-05",
    "st-06", "st-07", "st-08", "st-09", "st-10",
]
_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
_SEED = 20_260_805


@dataclass(frozen=True, slots=True)
class Observation:
    """観測レコード（内部表現）。気温と降水量は 0.1 単位の整数で保持します"""

    id: str
    station_id: str
    observed_at: str
    temperature_tenths: int
    humidity_pct: int
    precipitation_tenths: int


_cache: list[Observation] | None = None


def get_observations() -> list[Observation]:
    """10 万件を生成して返す（初回だけ生成し、以降はキャッシュを返す）"""
    global _cache
    if _cache is not None:
        return _cache

    state = _SEED % 2_147_483_647

    def next_random() -> int:
        nonlocal state
        state = (state * 48_271) % 2_147_483_647
        return state

    rows: list[Observation] = []
    for i in range(TOTAL_OBSERVATIONS):
        temperature_tenths = -50 + next_random() % 451  # -5.0℃ 〜 40.0℃
        humidity_pct = 20 + next_random() % 81  # 20% 〜 100%
        precipitation_tenths = next_random() % 61  # 0.0mm 〜 6.0mm
        rows.append(
            Observation(
                id=f"obs-{i + 1:06d}",
                station_id=STATION_IDS[i % len(STATION_IDS)],
                observed_at=(_START + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                temperature_tenths=temperature_tenths,
                humidity_pct=humidity_pct,
                precipitation_tenths=precipitation_tenths,
            )
        )
    _cache = rows
    return rows


def to_public(row: Observation) -> dict[str, Any]:
    """外部に見せる形。プロトコルに出るキーは TypeScript 版と同じ camelCase に揃えます

    Python の慣習は snake_case ですが、ここでは「クライアントから見た互換性」を優先します。
    """
    return {
        "id": row.id,
        "stationId": row.station_id,
        "observedAt": row.observed_at,
        "temperatureC": row.temperature_tenths / 10,
        "humidityPct": row.humidity_pct,
        "precipitationMm": row.precipitation_tenths / 10,
    }


def find_start_index(rows: list[Observation], after_id: str) -> int:
    """after_id より大きい最初の位置。その ID の行が削除されていても正しく動きます"""
    low, high = 0, len(rows)
    while low < high:
        mid = (low + high) // 2
        if rows[mid].id <= after_id:
            low = mid + 1
        else:
            high = mid
    return low


def encode_cursor(after_id: str) -> str:
    """カーソルを不透明な文字列にする（パディングを外して TypeScript 版と同じ形式にする）"""
    payload = json.dumps({"v": 1, "afterId": after_id}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_cursor(cursor: str) -> str:
    """カーソルを復号する。壊れていれば ValueError を投げる"""
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        parsed = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except Exception as exc:  # 不正な base64 / 不正な JSON
        raise ValueError(
            "cursor が不正です。前回のレスポンスの nextCursor をそのまま渡してください"
        ) from exc
    if (
        not isinstance(parsed, dict)
        or parsed.get("v") != 1
        or not isinstance(parsed.get("afterId"), str)
    ):
        raise ValueError("cursor の形式が不正です")
    return parsed["afterId"]


def accumulate(acc: dict[str, dict[str, int]], rows: list[Observation]) -> None:
    """チャンク 1 つ分を観測所ごとに足し込む"""
    for row in rows:
        current = acc.setdefault(
            row.station_id,
            {"count": 0, "sum_tenths": 0, "max_tenths": -10_000, "precip_tenths": 0},
        )
        current["count"] += 1
        current["sum_tenths"] += row.temperature_tenths
        current["max_tenths"] = max(current["max_tenths"], row.temperature_tenths)
        current["precip_tenths"] += row.precipitation_tenths


def summarize(acc: dict[str, dict[str, int]]) -> list[dict[str, Any]]:
    return [
        {
            "stationId": station_id,
            "count": value["count"],
            # 切り捨て除算だけで平均を出すと、丸め規則の違いを避けられます
            "avgTemperatureC": (value["sum_tenths"] * 10) // value["count"] / 100,
            "maxTemperatureC": value["max_tenths"] / 10,
            "totalPrecipitationMm": value["precip_tenths"] / 10,
        }
        for station_id, value in sorted(acc.items())
    ]
