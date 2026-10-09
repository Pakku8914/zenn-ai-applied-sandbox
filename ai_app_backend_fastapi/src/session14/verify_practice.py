"""Session 14 の練習問題の解答（q1〜q6）の検証。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session14
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from ulid import ULID

from kondate.cache import make_redis
from kondate.verifykit import check, eq, finish

from src.session14 import q1_trace, q2_extra, q3_preview, q4_contextvar, q5_attempts, q6_audit
from src.session14.celery_context import CELERY_HEADER
from src.session14.harness import (QUESTION, REQ_ID, UPSTREAM_ID, VALID_ID, capture_json_logs, guard_mock_env,
                                   mock_config)
from src.session14.llm import make_client
from src.session14.logctx import request_id_var
from src.session14.middleware import choose_request_id
from src.session14.runner import create_job
from src.session14.tasks import plan_week

CAP = capture_json_logs()
OTHER = "req_01BX5ZZKBKACTAV9WEVGEMMVRZ"
JOB = "job_01ARZ3NDEKTSV4RRFFQ69G5FAW"
KD = "kd_" + "Zx9" * 14 + "Q"


def line(ts: str, logger: str, event: str, rid: str, **fields: object) -> str:
    return json.dumps({"ts": f"2026-10-02T18:00:00.{ts}+09:00", "level": "INFO", "logger": logger,
                       "event": event, "request_id": rid, **fields}, ensure_ascii=False)


SAMPLE = [
    line("120", "kondate.session14.jobs", "job_enqueued", VALID_ID, job_id=JOB, total=2),
    'INFO:     172.18.0.1:51234 - "POST /api/jobs/plan-week HTTP/1.1" 202 Accepted',
    line("125", "kondate.session14.access", "request_finished", VALID_ID, status=202),
    line("090", "kondate.session14.llm", "llm_call", OTHER, outcome="ok", upstream_request_id="req_mock_000041"),
    line("410", "kondate.session14.llm", "llm_call", VALID_ID, job_id=JOB, outcome="error", upstream_status=500,
         upstream_request_id="req_mock_000042"),
    line("300", "kondate.session14.runner", "job_started", VALID_ID, job_id=JOB, total=2),
    '{"ts": "2026-10-02T18:00:00.200+09:00", "event": ',
    line("415", "kondate.session14.runner", "job_finished", VALID_ID, job_id=JOB, status="failed"),
]


@check("P1 request_id で絞り込み、時刻順に並べる（JSON でない行・壊れた行は飛ばす）")
def _():
    recs = q1_trace.trace(SAMPLE, VALID_ID)
    eq([r["event"] for r in recs], ["job_enqueued", "request_finished", "job_started", "llm_call", "job_finished"],
       "並び")
    eq(q1_trace.upstream_request_ids(recs), ["req_mock_000042"], "上流の request-id")
    eq(len(q1_trace.parse_lines(SAMPLE)), 6, "読めた行")
    # 小問：before_task_publish が載せた ID で、worker 側の行もたどれる（apply で同じプロセスに動かす）
    guard_mock_env()
    headers = q1_trace.publish_headers(VALID_ID)
    eq((headers, q1_trace.publish_headers(None)), ({CELERY_HEADER: VALID_ID}, {}), "シグナルが足したヘッダ")
    job_id = f"job_{ULID()}"

    async def prepare() -> None:
        redis = make_redis()
        try:
            await create_job(redis, job_id, total=2, mock_headers={})
        finally:
            await redis.aclose()

    asyncio.run(prepare())
    CAP.clear()
    eq(plan_week.apply(args=[job_id], task_id=job_id, headers=headers).status, "SUCCESS", "apply の結果")
    worker = q1_trace.trace(CAP.lines, VALID_ID)
    eq([r["event"] for r in worker], ["job_started", "llm_call", "llm_call", "job_finished"], "worker 側の行")
    eq({r["job_id"] for r in worker}, {job_id}, "worker 側の行の job_id")
    return ("5行（job_enqueued → request_finished → job_started → llm_call → job_finished）・上流 req_mock_000042・読めた行 6/8"
            "／小問：ヘッダ kondate_request_id → worker 側の4行（job_started → llm_call×2 → job_finished）に同じ request_id")


@check("P2 extra の名前が LogRecord・基本キーと重なっても、落ちず・消えない")
def _():
    log = logging.getLogger("kondate.session14.q2")
    try:
        log.info("dish_saved", extra={"name": "親子丼"})
    except KeyError as e:
        error = str(e)
    else:
        raise AssertionError("KeyError にならなかった")
    CAP.clear()
    log.info("dish_saved", extra={"event": "消える値"})
    q2_extra.log_event(log, logging.INFO, "dish_saved", name="親子丼", event="x", minutes=15)
    lost, kept = CAP.records
    eq(lost["event"], "dish_saved", "extra の event は黙って消える")
    eq((kept["event"], kept["logger"], kept["field_name"], kept["field_event"], kept["minutes"]),
       ("dish_saved", "kondate.session14.q2", "親子丼", "x", 15), "log_event")
    return f"素の extra={{'name': …}} は KeyError（{error}）・log_event は field_name・field_event に付け替える"


@check("P3 伏せてから切る：切ってから伏せるとメールとキーの一部が残る")
def _():
    mail = "taro@example.com に献立を送って"
    key = f"キーは {KD} です"
    eq((q3_preview.preview_bad(mail, 10), q3_preview.preview(mail, 10)), ("taro@examp…", "[EMAIL] に献…"), "メール")
    eq((q3_preview.preview_bad(key, 15), q3_preview.preview(key, 15)),
       ("キーは kd_Zx9Zx9Zx…", "キーは kd_Zx9Zx… で…"), "キー")
    eq(q3_preview.preview("献立", 10), "献立", "短い文は … を付けない")
    return "Bad は \"taro@examp…\" と kd_ の後8文字が残る・Good は [EMAIL] と kd_ の後5文字まで"


@check("P4 グローバル変数は混ざり、ContextVar は混ざらない（スレッドは to_thread なら引き継ぐ）")
async def _():
    eq(await q4_contextvar.run(q4_contextvar.handle_global), [("req_A", "req_B"), ("req_B", "req_B")], "グローバル変数")
    eq(await q4_contextvar.run(q4_contextvar.handle_contextvar), [("req_A", "req_A"), ("req_B", "req_B")],
       "ContextVar")
    eq(await q4_contextvar.in_threads("req_C"), ("req_C", None), "to_thread と run_in_executor")
    values = [None, VALID_ID, VALID_ID.lower(), "taro@example.com"]
    eq(q4_contextvar.id_sources(values),
       [("generated", False), ("received", True), ("rejected", False), ("rejected", False)], "choose_request_id")
    assert all(REQ_ID.fullmatch(choose_request_id(v)[0]) for v in values)
    return ("グローバル：req_A が req_B を見る・ContextVar：自分の ID・to_thread は req_C、run_in_executor は None"
            "／小問：なし → generated・正しい形式 → received（そのまま）・小文字とメール → rejected（採番し直し）")


@check("P5 再試行した2回の上流 request-id を、同じ request_id の行にまとめて残す")
async def _():
    cfg = mock_config()
    llm = make_client(cfg)
    rid = f"req_{ULID()}"
    token = request_id_var.set(rid)
    CAP.clear()
    try:
        headers = {"x-mock-fault": "500", "x-mock-fault-times": "1", "x-mock-fault-key": f"q5-{ULID()}"}

        async def no_sleep(_: float) -> None:
            pass

        _text, ids = await q5_attempts.ask_with_attempts(llm, cfg, QUESTION, extra_headers=headers, sleep=no_sleep)
    finally:
        request_id_var.reset(token)
        await llm.close()
    lines = CAP.for_request(rid)
    eq([(x["event"], x["outcome"]) for x in lines],
       [("llm_attempt", "error"), ("llm_attempt", "ok"), ("llm_call", "ok")], "行")
    eq((lines[0]["attempt"], lines[0]["upstream_status"], lines[1]["attempt"], lines[2]["attempts"]), (1, 500, 2, 2),
       "試行の番号")
    eq(lines[2]["upstream_request_ids"], ids, "まとめの行")
    eq((len(set(ids)), all(UPSTREAM_ID.fullmatch(i) for i in ids)), (2, True), "上流の ID は試行ごとに別")
    return "llm_attempt（1回目 500）→ llm_attempt（2回目 ok）→ llm_call（attempts=2・上流の ID 2つ）がすべて同じ request_id"


@check("P6 ログの監査：伏せ忘れを場所と種類つきで見つけ、見つかれば終了コード 1")
def _():
    clean = list(CAP.lines)
    dirty = [
        json.dumps({"ts": "2026-10-02T18:00:00.000+09:00", "event": "signup", "request_id": VALID_ID,
                    "email": "taro@example.com"}),
        json.dumps({"event": "debug", "headers": {"authorization": "Bearer abc.def"}}),
        json.dumps({"event": "x", "note": ["連絡は09012345678"]}, ensure_ascii=False),
        "not json",
        json.dumps({"event": "ok", "key_prefix": "kd_Zx9Zx", "masked": "sk-ant-[REDACTED]",
                    "authorization": "[REDACTED]"}),
    ]
    eq(q6_audit.audit(clean), [], "JsonFormatter が出した行")
    eq([(f.line, f.path, f.kind) for f in q6_audit.audit(dirty)],
       [(1, "email", "email"), (2, "headers.authorization", "secret_key"), (2, "headers.authorization", "bearer"),
        (3, "note[0]", "phone"), (4, "", "not_json")], "見つけたもの")
    with tempfile.TemporaryDirectory() as d:
        good, bad = Path(d, "good.log"), Path(d, "bad.log")
        good.write_text("\n".join(clean), encoding="utf-8")
        bad.write_text("\n".join(dirty), encoding="utf-8")
        printed = io.StringIO()
        with redirect_stdout(printed):  # 一時ファイルのパスは毎回変わるので、画面には出さない
            codes = (q6_audit.main([str(good)]), q6_audit.main([str(bad)]))
    eq(codes, (0, 1), "終了コード")
    eq(len(printed.getvalue().splitlines()), 5, "表示した行")
    return f"伏せ字済みの {len(clean)} 行は0件（終了コード 0）・手で作った5行から5件（終了コード 1）"


finish("session14 practice")
