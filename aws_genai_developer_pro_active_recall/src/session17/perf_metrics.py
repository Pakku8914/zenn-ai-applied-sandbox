#!/usr/bin/env python3
"""セッション17: 生成AI固有の指標を、見える形にする。

    docker compose exec app python src/session17/perf_metrics.py

CPU 使用率とエラー率だけでは、生成AIアプリの調子は分かりません。**壊れていないのに
役に立っていない**という状態があるためです。本章で数えるのは次の6系統です。

    トークン使用量    入力・出力の合計          → 費用と入力肥大の兆候
    レイテンシ        p50 と p95                → 体感（平均では見えない）
    プロンプト有効性  一次モデルで通った割合    → 指示・資料・モデルのどれかの劣化
    引用ゼロ率        根拠を引けなかった割合    → 検索側の劣化（ハルシネーションの代理指標）
    拒否率            入口で止めた割合          → 誤用の兆候・ポリシーの効き過ぎ
    キャッシュ命中率  事前計算で返せた割合      → 体感と費用の両方に効く

集計と通知の土台はセッション14の `continuous_monitoring` をそのまま使い、
**性能側の指標を足すだけ**にします（同じ集計を2つ持つと必ず食い違います）。
セッション14がガバナンスの証跡として数えたものを、本章は運用の計器として読みます。
"""

from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session04")
sys.path.insert(0, "/workspace/src/session06")
sys.path.insert(0, "/workspace/src/session14")
sys.path.insert(0, "/workspace/src/session16")
sys.path.insert(0, "/workspace/src/session17")

from awskit import clients  # noqa: E402

import continuous_monitoring as monitoring  # noqa: E402  セッション14
import provenance  # noqa: E402  セッション14（説明責任ログ）

import latency_lab  # noqa: E402

# 名前空間はガバナンス（セッション14）と分けています。**実運用では分けません。**
# 同じ数字を2つの名前空間へ書くと PutMetricData の費用が2倍になり、
# しかも片方だけ直したときに食い違います。1つの名前空間に出し、
# ダッシュボードを見る側で分けるのが作法です（本章は章の独立性のために分けています）
NAMESPACE = "SampleShoji/Performance"
COUNT_METRIC = "RequestCount"

# (メトリクス名, 集計値のキー, 単位, 割合か)
METRICS: tuple[tuple[str, str, str, bool], ...] = (
    (COUNT_METRIC, "total", "Count", False),
    ("GuardrailBlockRate", "blockedRate", "Percent", True),
    ("ZeroCitationRate", "zeroCitationRate", "Percent", True),
    ("ExhaustedRate", "exhaustedRate", "Percent", True),
    ("PromptEffectiveness", "promptEffectiveness", "Percent", True),
    ("CacheHitRate", "cacheHitRate", "Percent", True),
    ("InputTokens", "inputTokens", "Count", False),
    ("OutputTokens", "outputTokens", "Count", False),
    ("LatencyP50", "latencyP50Ms", "Milliseconds", False),
    ("LatencyP95", "latencyP95Ms", "Milliseconds", False),
)

# しきい値。**向きが指標ごとに違う**のが要点です（大きいと困る／小さいと困る）。
# 数字は初期値で、見直し前提。根拠を書けない数字は置かない
PERF_THRESHOLDS: tuple[dict, ...] = (
    {"key": "zeroCitationRate", "metricName": "ZeroCitationRate", "direction": "max",
     "threshold": 0.10, "action": "reindex-corpus"},
    {"key": "promptEffectiveness", "metricName": "PromptEffectiveness",
     "direction": "min", "threshold": 0.90, "action": "review-prompt-version"},
    {"key": "cacheHitRate", "metricName": "CacheHitRate", "direction": "min",
     "threshold": 0.60, "action": "warm-faq-cache"},
    {"key": "latencyP95Ms", "metricName": "LatencyP95", "direction": "max",
     "threshold": 1500, "action": "shorten-output-and-precompute"},
)


# ---------------------------------------------------------------------------
# 集計
# ---------------------------------------------------------------------------


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def percentile(values: list[int], q: float) -> int:
    """パーセンタイル（最近傍順位法）。**平均は使いません。**

    平均は、遅い数件を大量の速い件で薄めてしまいます。「10人に1人が5秒待って
    いる」状態を平均は隠しますが、p95 は隠せません。順位法にしているのは、
    件数が少なくても定義が揺れないようにするためです。
    """
    if not values:
        return 0
    ordered = sorted(values)
    index = max(math.ceil(q * len(ordered)) - 1, 0)
    return ordered[index]


def summarize(entries: list[dict], *, cache: dict) -> dict:
    """説明責任ログ（セッション14）に、性能側の指標を足す。

    プロンプト有効性の分母は「モデルを呼んだ件」です。入口で止めた件や
    引用ゼロで呼ばなかった件を分母に入れると、**止めるほど有効性が上がって見えます**。
    """
    base = monitoring.aggregate(entries)
    called = [entry for entry in entries if entry["attempts"]]
    first_ok = [
        entry for entry in called
        if entry["outcome"] == "answered" and len(entry["attempts"]) == 1
    ]
    latencies = [entry["latencyMs"] for entry in called]
    return {
        **base,
        "modelCalled": len(called),
        "firstAttemptOk": len(first_ok),
        "promptEffectiveness": _rate(len(first_ok), len(called)),
        "inputTokens": sum(entry["inputTokens"] for entry in entries),
        "outputTokens": sum(entry["outputTokens"] for entry in entries),
        "latencyP50Ms": percentile(latencies, 0.50),
        "latencyP95Ms": percentile(latencies, 0.95),
        "cacheLookups": cache["lookups"],
        "cacheHits": cache["hits"],
        "cacheHitRate": cache["hitRate"],
    }


def breaches(summary: dict, thresholds: tuple[dict, ...] = PERF_THRESHOLDS) -> list[dict]:
    """しきい値を割った項目だけを返す（向きを見て判定する）。"""
    found: list[dict] = []
    for rule in sorted(thresholds, key=lambda r: r["metricName"]):
        value = summary[rule["key"]]
        if rule["direction"] == "max":
            hit = value > rule["threshold"]
        else:
            hit = value < rule["threshold"]
        if hit:
            found.append(
                {
                    "metric": rule["key"],
                    "metricName": rule["metricName"],
                    "value": value,
                    "threshold": rule["threshold"],
                    "direction": rule["direction"],
                    "action": rule["action"],
                }
            )
    return found


def sign_of(direction: str) -> str:
    return ">" if direction == "max" else "<"


# ---------------------------------------------------------------------------
# CloudWatch のカスタムメトリクス
# ---------------------------------------------------------------------------


def publish_metrics(cw, summary: dict, *, run_id: str) -> list[str]:
    """10本を1回の `put_metric_data` で出す。

    ディメンションはセッション14と同じ（`Assistant` / `RunId`）です。実行ごとに
    分けておくと、演習を何度回しても値が混ざりません。
    """
    now = datetime.now(timezone.utc)
    data = []
    for name, key, unit, percent in METRICS:
        value = float(summary[key])
        data.append(
            {
                "MetricName": name,
                "Dimensions": monitoring.dimensions(run_id),
                "Timestamp": now,
                # Percent は 0〜100 で入れる（割合のまま入れると 1% に見える）
                "Value": round(value * 100, 4) if percent else value,
                "Unit": unit,
            }
        )
    cw.put_metric_data(Namespace=NAMESPACE, MetricData=data)
    return [item["MetricName"] for item in data]


def listed_metrics(cw, *, run_id: str) -> list[str]:
    """登録されたメトリクスを読み戻す（この実行ぶんだけ抜き出す）。"""
    names: set[str] = set()
    token: str | None = None
    while True:
        kwargs: dict = {"Namespace": NAMESPACE}
        if token:
            kwargs["NextToken"] = token
        res = cw.list_metrics(**kwargs)
        for metric in res.get("Metrics", []):
            values = {d["Name"]: d["Value"] for d in metric.get("Dimensions", [])}
            if values.get("RunId") == run_id:
                names.add(metric["MetricName"])
        token = res.get("NextToken")
        if not token:
            return sorted(names)


def read_sum(cw, metric_name: str, *, run_id: str, attempts: int = 20, wait: float = 0.5):
    """メトリクスを合計で読み戻す。**書けたことを値で確かめる。**"""
    for _ in range(attempts):
        res = cw.get_metric_statistics(
            Namespace=NAMESPACE,
            MetricName=metric_name,
            Dimensions=monitoring.dimensions(run_id),
            StartTime=datetime.now(timezone.utc) - timedelta(minutes=10),
            EndTime=datetime.now(timezone.utc) + timedelta(minutes=10),
            Period=60,
            Statistics=["Sum"],
        )
        points = res.get("Datapoints") or []
        if points:
            return sum(point["Sum"] for point in points)
        time.sleep(wait)
    return None


# ---------------------------------------------------------------------------
# 通知（経路はセッション14のものを再利用する）
# ---------------------------------------------------------------------------


def notify_perf(found: list[dict], summary: dict, *, channels: dict, run_id: str,
                sns=None) -> int:
    """超過ぶんだけ人へ通知する。**本文（質問・回答）は載せない。**

    載せる内容の作り方はセッション14の `alert_payload` を使います。通知は転送
    されるので、載せてよいのは「どの指標が」「どれだけ」「母数は」「次に何を
    起動するか」だけです。
    """
    if not found:
        return 0
    sns = sns or clients.aws("sns")
    for breach in found:
        payload = monitoring.alert_payload(breach, summary, run_id=run_id)
        sns.publish(
            TopicArn=channels["topicArn"],
            # SNS の Subject は ASCII のみ
            Subject="perf-threshold-breached",
            Message=json.dumps(payload, ensure_ascii=False),
        )
    return len(found)


# ---------------------------------------------------------------------------
# 観測窓を1つ作る
# ---------------------------------------------------------------------------


def run_window(*, runtime=None, ddb=None) -> dict:
    """1つの観測窓ぶんのデータを作る（説明責任ログ10件 ＋ 事前計算6件）。

    セッション14の10件をそのまま流します。同じ母集団を使うので、
    ガバナンス側の集計値（拒否率・引用ゼロ率・exhausted率）と突き合わせられます。
    """
    runtime = runtime or clients.bedrock_runtime()
    state = provenance.bootstrap()
    logs = clients.aws("logs")
    run_id = provenance.new_run_id()
    entries = provenance.run_all(
        run_id=run_id, s3=state["s3"], ddb=state["ddb"], logs=logs
    )
    cache_records = latency_lab.run_cache_stream(runtime, ddb=ddb)
    return {
        "runId": run_id,
        "entries": entries,
        "cacheRecords": cache_records,
        "cache": latency_lab.cache_stats(cache_records),
    }


# ---------------------------------------------------------------------------
# 演習の本体
# ---------------------------------------------------------------------------


def main() -> None:
    window = run_window()
    summary = summarize(window["entries"], cache=window["cache"])

    print("=== 1. 1件ずつの記録を、傾向に変える ===")
    print(
        f"  全件 {summary['total']} / 入口を通った件 {summary['attempted']}"
        f" / モデルを呼んだ件 {summary['modelCalled']}"
    )
    print(f"  拒否率            {summary['blockedRate']}")
    print(f"  引用ゼロ率        {summary['zeroCitationRate']}")
    print(f"  exhausted率       {summary['exhaustedRate']}")
    print(f"  根拠提示率        {summary['groundedRate']}")
    print(
        f"  プロンプト有効性  {summary['promptEffectiveness']}"
        f"（一次モデルで通った件 {summary['firstAttemptOk']}"
        f" / モデルを呼んだ件 {summary['modelCalled']}）"
    )
    print(
        f"  キャッシュ命中率  {summary['cacheHitRate']}"
        f"（命中 {summary['cacheHits']} / 引き {summary['cacheLookups']}）"
    )
    print(
        f"  入力トークン合計 > 0: {summary['inputTokens'] > 0}"
        f" / 出力トークン合計 > 0: {summary['outputTokens'] > 0}"
    )
    print(
        f"  レイテンシ p95 ≧ p50: {summary['latencyP95Ms'] >= summary['latencyP50Ms']}"
        "（絶対値は資料の長さで決まるため判定には使いません）"
    )

    print()
    print("=== 2. CloudWatch のカスタムメトリクスに出して読み戻す ===")
    cw = clients.aws("cloudwatch")
    published = publish_metrics(cw, summary, run_id=window["runId"])
    listed = listed_metrics(cw, run_id=window["runId"])
    print(f"  名前空間: {NAMESPACE}")
    print(f"  書いたメトリクス {len(published)}本: {sorted(published)}")
    print(f"  読み戻して一致: {listed == sorted(published)}")
    print(f"  母数（{COUNT_METRIC}）の合計: {read_sum(cw, COUNT_METRIC, run_id=window['runId'])}")

    print()
    print("=== 3. しきい値を割った項目だけ通知する ===")
    channels = monitoring.ensure_channels()
    monitoring.drain(channels["inboxUrl"])
    found = breaches(summary)
    for breach in found:
        print(
            f"  逸脱: {breach['metricName']} {breach['value']}"
            f" {sign_of(breach['direction'])} {breach['threshold']}"
            f" -> {breach['action']}"
        )
    within = [
        rule["metricName"] for rule in PERF_THRESHOLDS
        if rule["metricName"] not in {b["metricName"] for b in found}
    ]
    print(f"  しきい値の内側: {sorted(within)}")
    sent = notify_perf(found, summary, channels=channels, run_id=window["runId"])
    print(f"  通知: {sent} 件（人向け SNS。経路はセッション14のものを再利用）")

    print()
    print("=== 4. 届いたことを確かめる ===")
    inbox = monitoring.receive(channels["inboxUrl"], expected=sent)
    payloads = sorted(
        (json.loads(message["Body"]) for message in inbox),
        key=lambda p: p["metric"],
    )
    print(f"  届いた通知: {len(payloads)} 件")
    for payload in payloads:
        print(
            f"    {payload['metric']} value={payload['value']}"
            f" action={payload['action']}"
        )
    print("  ※ 通知に質問と回答は入っていません（転送されても本文は漏れません）")
    monitoring.drain(channels["inboxUrl"])


if __name__ == "__main__":
    main()
