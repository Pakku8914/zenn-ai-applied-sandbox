"""s14.plan_week の本体（worker の中で動く）。session12 のジョブを、伝播を示す最小限まで縮めたもの。

キャンセル・再試行・冪等の工夫は session12 で扱ったので省く。ここで見せたいのは次の2点だけ：
- request_id は引数でもジョブの記録でもなく、Celery のヘッダから contextvars に届く（celery_context.py）
- そのおかげで、ジョブのログにも失敗の本文にも、ジョブを登録したリクエストの ID が付く

キー（接頭辞 s14:）  s14:job:{job_id}  ハッシュ：status・done・total・result・error・mock_headers
"""

from __future__ import annotations

import json
import logging

import anthropic
from anthropic import AsyncAnthropic
from redis.asyncio import Redis

from kondate.cache import make_redis

from .errors import MESSAGES, translate
from .llm import LLMConfig, LogSettings, ask, make_client
from .logctx import request_id_var

logger = logging.getLogger("kondate.session14.runner")

PREFIX = "s14:"
JOB_TTL = 3600  # 登録から1時間で消える（session12 の保存期限を簡略化）


def job_key(job_id: str) -> str:
    return f"{PREFIX}job:{job_id}"


async def create_job(redis: Redis, job_id: str, *, total: int, mock_headers: dict[str, str]) -> None:
    key = job_key(job_id)
    async with redis.pipeline(transaction=True) as pipe:
        await pipe.hset(key, mapping={"status": "queued", "done": "0", "total": str(total),
                                      "mock_headers": json.dumps(mock_headers)}).expire(key, JOB_TTL).execute()


async def delete_job(redis: Redis, job_id: str) -> None:
    await redis.delete(job_key(job_id))


async def load_job(redis: Redis, job_id: str) -> dict | None:
    h = await redis.hgetall(job_key(job_id))
    if not h:
        return None
    return {"job_id": job_id, "status": h["status"], "done": int(h["done"]), "total": int(h["total"]),
            "result": json.loads(h["result"]) if "result" in h else None,
            "error": json.loads(h["error"]) if "error" in h else None}


async def run_job(redis: Redis, llm: AsyncAnthropic, cfg: LLMConfig, log: LogSettings, job_id: str) -> str | None:
    key = job_key(job_id)
    h = await redis.hgetall(key)
    if not h:
        logger.warning("job_missing")
        return None
    if h["status"] != "queued":
        return h["status"]  # 再配送されたジョブには触れない（本格的な冪等は session12）
    total = int(h["total"])
    headers = json.loads(h.get("mock_headers") or "{}")
    await redis.hset(key, "status", "running")
    logger.info("job_started", extra={"total": total})
    days: list[dict] = []
    try:
        for day in range(1, total + 1):
            answer = await ask(llm, cfg, log, f"{day}日目の夕飯の献立を1つ提案してください。", extra_headers=headers)
            days.append({"day": day, "text": answer.text})
            await redis.hincrby(key, "done", 1)
    except Exception as exc:
        type_ = translate(exc).type if isinstance(exc, anthropic.APIError) else "internal_error"
        # 失敗の本文の request_id は、ヘッダで届いた「ジョブを登録したリクエストの ID」
        error = {"type": type_, "message": MESSAGES[type_], "request_id": request_id_var.get()}
        await redis.hset(key, mapping={"status": "failed", "error": json.dumps(error, ensure_ascii=False)})
        logger.warning("job_finished", extra={"status": "failed", "done": len(days), "total": total,
                                              "error": type(exc).__name__},
                       exc_info=not isinstance(exc, anthropic.APIError))  # 想定外の例外だけ traceback も残す
        return "failed"
    await redis.hset(key, mapping={"status": "succeeded", "result": json.dumps({"days": days}, ensure_ascii=False)})
    logger.info("job_finished", extra={"status": "succeeded", "done": total, "total": total})
    return "succeeded"


async def execute(job_id: str) -> str | None:
    """worker の1回の実行。接続は毎回作って閉じる（asyncio.run ごとにイベントループが変わるため）。"""
    cfg, log = LLMConfig(), LogSettings()
    redis, llm = make_redis(), make_client(cfg)
    try:
        return await run_job(redis, llm, cfg, log, job_id)
    finally:
        await llm.close()
        await redis.aclose()
