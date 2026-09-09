#!/usr/bin/env python3
"""セッション11: 部門別のコスト按分（チャージバック）。

    docker compose exec app python src/session11/chargeback.py

ゲートウェイが積み上げた原簿（`aip_c01_usage_ledger`）を読み、
**部門 × モデル**の使用量から金額を出します。本章の狙いは削減ではなく
「誰がいくら使ったかを、請求と突き合わせられる形で見せる」ことです
（削減の手法はコスト最適化のセッションで扱います）。

按分が信用されるための条件は1つだけです。
**部門ごとの合計が、請求側の総額とぴったり一致すること。**
ここでは請求側の代わりにモックの `GET /_mock/usage` を使い、差分が
0 でなければ検証を落とします。
"""

from __future__ import annotations

import json
import sys
import urllib.request

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session11")

from awskit import clients  # noqa: E402
from bedrock_mock import catalog  # noqa: E402

import gateway  # noqa: E402

# 金額の丸めは「表示のとき」だけ行う。
# 明細を1件ずつ丸めて足すと、部門合計と総額が合わなくなる
DISPLAY_DIGITS = 6


def exact_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """丸めない金額。突き合わせに使うのはこちら。"""
    spec, _ = catalog.resolve(model_id)
    return (
        input_tokens * spec.input_usd_per_1m + output_tokens * spec.output_usd_per_1m
    ) / 1_000_000


def department_rows(client, department: str, window: str) -> list[dict]:
    """1部門の明細（モデル別）を取る。Scan ではなく Query を使う。

    Scan は表全体を読むため、部門とモデルが増えるほど遅く高くなります。
    パーティションキーを部門にしておけば、必要な範囲だけを読めます。
    """
    res = client.query(
        TableName=gateway.LEDGER_TABLE,
        KeyConditionExpression="#d = :d AND begins_with(#sk, :p)",
        ExpressionAttributeNames={"#d": "department", "#sk": "sk"},
        ExpressionAttributeValues={
            ":d": {"S": department},
            ":p": {"S": f"{window}#model#"},
        },
    )
    rows = []
    for item in res.get("Items", []):
        rows.append(
            {
                "modelId": item["sk"]["S"].split("#model#", 1)[1],
                "calls": int(item["calls"]["N"]),
                "inputTokens": int(item["inputTokens"]["N"]),
                "outputTokens": int(item["outputTokens"]["N"]),
            }
        )
    return sorted(rows, key=lambda r: r["modelId"])


def report(client, config: dict, window: str) -> dict:
    """按分レポートを作る。金額は丸めずに保持する。"""
    departments = []
    total = {"calls": 0, "inputTokens": 0, "outputTokens": 0, "estimatedUsd": 0.0}

    for name, tenant in config["departments"].items():
        rows = department_rows(client, name, window)
        usd = sum(
            exact_cost(r["modelId"], r["inputTokens"], r["outputTokens"]) for r in rows
        )
        summary = {
            "department": name,
            "costCenter": tenant["costCenter"],
            "tokenLimit": int(tenant["tokenLimit"]),
            "calls": sum(r["calls"] for r in rows),
            "inputTokens": sum(r["inputTokens"] for r in rows),
            "outputTokens": sum(r["outputTokens"] for r in rows),
            "estimatedUsd": usd,
            "perModel": rows,
        }
        summary["totalTokens"] = summary["inputTokens"] + summary["outputTokens"]
        departments.append(summary)
        for key in ("calls", "inputTokens", "outputTokens", "estimatedUsd"):
            total[key] += summary[key]

    total["totalTokens"] = total["inputTokens"] + total["outputTokens"]
    for summary in departments:
        summary["sharePct"] = (
            round(summary["estimatedUsd"] / total["estimatedUsd"] * 100, 2)
            if total["estimatedUsd"] > 0
            else 0.0
        )
    return {"window": window, "total": total, "departments": departments}


def mock_usage() -> dict:
    """請求側の代わり。実務では AWS Cost Explorer / CUR をここに置く。"""
    with urllib.request.urlopen(
        f"{clients.mock_base_url()}/_mock/usage", timeout=10
    ) as res:
        return json.loads(res.read())


def reconcile(rep: dict, usage: dict) -> dict:
    """按分の合計と請求側の総額を突き合わせる。差分が 0 でなければ按分は嘘。"""
    billed_usd = sum(
        exact_cost(model_id, slot["inputTokens"], slot["outputTokens"])
        for model_id, slot in usage["perModel"].items()
    )
    return {
        "callsDiff": rep["total"]["calls"] - usage["calls"],
        "inputTokensDiff": rep["total"]["inputTokens"] - usage["inputTokens"],
        "outputTokensDiff": rep["total"]["outputTokens"] - usage["outputTokens"],
        "usdDiff": rep["total"]["estimatedUsd"] - billed_usd,
        "billedUsd": billed_usd,
        "mockEstimatedUsdTotal": usage["estimatedUsdTotal"],
    }


def render(rep: dict) -> str:
    """本文に貼れる形の表を作る（数値は実行環境で決まる実測値）。"""
    lines = [
        f"按分レポート（窓 {rep['window']}）",
        f"{'部門':<10}{'コストセンター':<14}{'呼出':>5}{'入力tok':>9}{'出力tok':>9}"
        f"{'推定USD':>12}{'按分率':>9}",
    ]
    for row in rep["departments"]:
        lines.append(
            f"{row['department']:<10}{row['costCenter']:<14}{row['calls']:>5}"
            f"{row['inputTokens']:>9}{row['outputTokens']:>9}"
            f"{row['estimatedUsd']:>12.{DISPLAY_DIGITS}f}{row['sharePct']:>8.2f}%"
        )
    total = rep["total"]
    lines.append(
        f"{'合計':<10}{'':<14}{total['calls']:>5}{total['inputTokens']:>9}"
        f"{total['outputTokens']:>9}{total['estimatedUsd']:>12.{DISPLAY_DIGITS}f}"
    )
    return "\n".join(lines)


def main() -> None:
    config = gateway.load_gateway_config()
    window = gateway.current_window()
    client = gateway.ensure_ledger()
    rep = report(client, config, window)
    print(render(rep))

    diff = reconcile(rep, mock_usage())
    print()
    print("=== 請求側との突き合わせ ===")
    print(f"  呼び出し数の差分 : {diff['callsDiff']}")
    print(f"  入力トークンの差分: {diff['inputTokensDiff']}")
    print(f"  出力トークンの差分: {diff['outputTokensDiff']}")
    print(f"  金額の差分        : {diff['usdDiff']:.12f}")
    print("  ※ 差分が 0 でなければ、按分の根拠が壊れています")


if __name__ == "__main__":
    main()
