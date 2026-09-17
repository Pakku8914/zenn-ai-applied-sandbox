"""サンドボックス全体の自己検証。

テレメトリが app → Collector → Prometheus / Tempo / Loki の3経路すべてに
届いていることを確認する。期待どおりでなければ非 0 で終了する。
"""

from __future__ import annotations

import sys
import time

import httpx

PROM = "http://prometheus:9090"
TEMPO = "http://tempo:3200"
LOKI = "http://loki:3100"
APP = "http://localhost:8000"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    mark = "OK  " if ok else "NG  "
    print(f"{mark}{name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def main() -> int:
    # 1. アプリ自身が応答する
    try:
        r = httpx.get(f"{APP}/healthz", timeout=5)
        check("app /healthz", r.status_code == 200 and r.json()["status"] == "ok", r.text.strip())
    except Exception as exc:  # noqa: BLE001
        check("app /healthz", False, str(exc))
        return finish()

    # 2. トラフィックを流してテレメトリを発生させる（成功・遅延・失敗を必ず1回ずつ通す）
    codes: list[int] = []
    for _ in range(20):
        try:
            codes.append(httpx.post(f"{APP}/api/checkout", timeout=10).status_code)
        except Exception:  # noqa: BLE001
            codes.append(0)
    # 20 回流すと n=5,15 が 500、n=10,20 が 1.2 秒の遅延になる（%10 の判定が先）
    check(
        "checkout の決定的な挙動（20回中 500 が2回）",
        codes.count(500) == 2 and codes.count(200) == 18,
        f"500={codes.count(500)} 200={codes.count(200)}",
    )

    # Collector の batch(1s) → 各バックエンドへの書き込みを待つ
    time.sleep(8)

    # 3. メトリクスが Prometheus に届いている
    try:
        r = httpx.get(f"{PROM}/api/v1/query", params={"query": "checkout_attempts_total"}, timeout=10)
        result = r.json().get("data", {}).get("result", [])
        check("Prometheus に checkout_attempts_total がある", len(result) > 0, f"series={len(result)}")
    except Exception as exc:  # noqa: BLE001
        check("Prometheus に checkout_attempts_total がある", False, str(exc))

    # 4. トレースが Tempo に届いている
    try:
        r = httpx.get(f"{TEMPO}/api/search", params={"tags": "service.name=checkout-api", "limit": "5"}, timeout=10)
        traces = r.json().get("traces", [])
        check("Tempo に checkout-api のトレースがある", len(traces) > 0, f"traces={len(traces)}")
    except Exception as exc:  # noqa: BLE001
        check("Tempo に checkout-api のトレースがある", False, str(exc))

    # 5. ログが Loki に届いている
    try:
        end = int(time.time() * 1e9)
        start = end - int(600 * 1e9)
        r = httpx.get(
            f"{LOKI}/loki/api/v1/query_range",
            params={"query": '{service_name="checkout-api"}', "start": str(start), "end": str(end), "limit": "10"},
            timeout=10,
        )
        streams = r.json().get("data", {}).get("result", [])
        check("Loki に checkout-api のログがある", len(streams) > 0, f"streams={len(streams)}")
    except Exception as exc:  # noqa: BLE001
        check("Loki に checkout-api のログがある", False, str(exc))

    return finish()


def finish() -> int:
    print()
    if failures:
        print(f"検証に失敗しました（{len(failures)}件）: {', '.join(failures)}")
        return 1
    print("サンドボックスの自己検証に成功しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
