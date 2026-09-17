"""観測対象のサンプルアプリ（架空のチェックアウトAPI）。

本書では「壊れ方が決まっている」ことを重視する。遅延・失敗はすべて呼び出し回数から
決定的に決まるので、負荷試験の結果もダッシュボードの形も毎回同じになる。
乱数を使わないのは、読者が本文の数値と自分の画面を突き合わせられるようにするため。
"""

import logging
import os
import time
from itertools import count

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from opentelemetry import metrics, trace

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("checkout-api")

app = FastAPI(title="checkout-api", version="1.0.0")

tracer = trace.get_tracer("checkout-api")
meter = metrics.get_meter("checkout-api")

# 業務的に意味のあるカウンタ（技術メトリクスと対比させるために置いている）
checkout_total = meter.create_counter(
    "checkout.attempts",
    description="チェックアウトの試行回数",
    unit="1",
)

_calls = count(1)

PRODUCTS = [
    {"id": 1, "name": "ノート", "price": 480},
    {"id": 2, "name": "ボールペン", "price": 150},
    {"id": 3, "name": "付箋", "price": 320},
]


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """依存先を見ない liveness 用の応答。常に速い。"""
    return {"status": "ok"}


@app.get("/api/products")
def list_products() -> dict[str, object]:
    """速い正常系。SLI のベースラインとして使う。"""
    return {"products": PRODUCTS}


@app.post("/api/checkout")
def checkout() -> JSONResponse:
    """5回に1回だけ 500 を返し、10回に1回だけ 1.2 秒かかる決定的なエンドポイント。

    - n % 10 == 0 → 1.2 秒の遅延（レイテンシSLOを踏む）
    - n % 5  == 0 → 500 エラー（可用性SLOを踏む）
    """
    n = next(_calls)
    checkout_total.add(1, {"endpoint": "/api/checkout"})

    with tracer.start_as_current_span("checkout.process") as span:
        span.set_attribute("checkout.sequence", n)

        if n % 10 == 0:
            with tracer.start_as_current_span("inventory.lookup.slow"):
                time.sleep(1.2)
            logger.warning("slow checkout detected sequence=%s", n)
            return JSONResponse({"ok": True, "sequence": n, "slow": True})

        if n % 5 == 0:
            span.set_attribute("error.kind", "payment_declined")
            logger.error("checkout failed sequence=%s reason=payment_declined", n)
            raise HTTPException(status_code=500, detail="payment declined")

        with tracer.start_as_current_span("inventory.lookup"):
            time.sleep(0.02)
        logger.info("checkout succeeded sequence=%s", n)
        return JSONResponse({"ok": True, "sequence": n, "slow": False})


@app.get("/api/slow")
def slow() -> dict[str, float]:
    """常に 0.8 秒かかる。ボトルネック調査の題材。"""
    started = time.perf_counter()
    with tracer.start_as_current_span("report.aggregate"):
        time.sleep(0.8)
    return {"elapsed_seconds": round(time.perf_counter() - started, 3)}


@app.get("/api/version")
def version() -> dict[str, str]:
    return {
        "service": os.environ.get("OTEL_SERVICE_NAME", "unknown"),
        "version": app.version,
    }
