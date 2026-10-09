"""Session 14（構造化ログとリクエストID・PII マスク）の検証。api コンテナの中で実行する：

    docker compose restart worker          # tasks.py を読み込ませる（変更したら毎回）
    docker compose exec api bash verify-all.sh src/session14

ログは画面に出さず、本物の JsonFormatter で整形した行を集めて JSON として解析し、中身を比べる。
時刻・request_id・job_id のように毎回変わる値は、出力に出さない。
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from celery.signals import after_task_publish
from ulid import ULID

from kondate.cache import make_redis
from kondate.verifykit import check, eq, finish, sse_events
from kondate.worker import app as celery_app

from src.session14.app import create_app  # import 時に app = create_app() が JSON の出力先を付ける
from src.session14.celery_context import CELERY_HEADER
from src.session14.errors import MESSAGES
from src.session14.harness import (ANSWER_HEAD, QUESTION, REQ_ID, TS, UPSTREAM_ID, VALID_ID, assert_error,
                                   capture_json_logs, clear_redis, guard_mock_env, mock_config, running, wait_job)
from src.session14.llm import LogSettings
from src.session14.logctx import job_id_var, request_id_var
from src.session14.mask import mask_fields, mask_text
from src.session14.middleware import new_request_id
from src.session14.runner import create_job
from src.session14.tasks import plan_week

CAP = capture_json_logs()  # 上の出力先を外し、集める先に付け替える
MOCK = mock_config()
KD = "kd_" + "Zx9" * 14 + "Q"  # kd_ + 43文字（session09 のキーと同じ形。値は検証用）
SK = "sk-ant-api03-" + "AbC12_-x" * 5
PUBLISHED: list[dict] = []


def _record_published(headers: dict | None = None, **_: object) -> None:
    PUBLISHED.append(dict(headers or {}))


after_task_publish.connect(_record_published, weak=False)
asyncio.run(clear_redis())


def new_app(**kwargs: object):
    return create_app(MOCK, kwargs.pop("log", None), configure_logging=False, **kwargs)


@check("V1 JSON 1行：基本キー → 文脈（request_id・job_id）→ extra → 例外の順に出る")
def _():
    log = logging.getLogger("kondate.session14.verify")
    CAP.clear()
    log.info("dish_saved", extra={"dish": "親子丼", "price": Decimal("1.50"), "note": "1行目\n2行目"})
    t1, t2 = request_id_var.set(VALID_ID), job_id_var.set("job_01ARZ3NDEKTSV4RRFFQ69G5FAV")
    try:
        log.info("in_context", extra={"minutes": 15})
    finally:
        request_id_var.reset(t1)
        job_id_var.reset(t2)
    try:
        raise ValueError("taro@example.com の献立が見つかりません")
    except ValueError:
        log.exception("lookup_failed")
    plain, ctx, failed = CAP.records
    eq(list(plain), ["ts", "level", "logger", "event", "dish", "price", "note"], "キーの順（文脈なし）")
    eq((plain["level"], plain["logger"], plain["price"], plain["note"]),
       ("INFO", "kondate.session14.verify", "1.50", "1行目\n2行目"), "値")
    assert TS.fullmatch(plain["ts"]), plain["ts"]
    eq(all("\n" not in line for line in CAP.lines), True, "改行を含む値も1行に収まる")
    eq(list(ctx), ["ts", "level", "logger", "event", "request_id", "job_id", "minutes"], "キーの順（文脈あり）")
    eq((failed["level"], failed["exc_type"]), ("ERROR", "ValueError"), "例外")
    assert failed["exc"].startswith("Traceback") and "[EMAIL]" in failed["exc"], failed["exc"]
    assert "taro@example.com" not in "\n".join(CAP.lines)
    return "ts・level・logger・event → request_id・job_id → extra・改行も1行に・Decimal は \"1.50\"・例外は exc_type と exc（伏せ字済み）"


@check("V2 マスク：メール・電話・キー・Bearer を伏せ、日付や ID は伏せない")
def _():
    sample = ("連絡先は taro.yamada+kondate@example.co.jp、電話は090-1234-5678 か 03-1234-5678（+81 90 1234 5678）。"
              f"キー {KD} と {SK}、ヘッダ Authorization: Bearer abc.def-123")
    eq(mask_text(sample),
       "連絡先は [EMAIL]、電話は[PHONE] か [PHONE]（[PHONE]）。"
       "キー kd_Zx9Zx… と sk-ant-[REDACTED]、ヘッダ Authorization: Bearer [REDACTED]", "伏せた結果")
    keep = ["2026-10-02T18:00:00.000+09:00", VALID_ID, "job_01ARZ3NDEKTSV4RRFFQ69G5FAV", "R001 を 20分で",
            "input_tokens=34 output_tokens=181", "kd_Zx9Zx（先頭8文字）",
            "/api/conversations/0199a3b2-1234-7abc-8def-0123456789ab"]
    eq([mask_text(s) for s in keep], keep, "伏せてはいけないもの")
    eq(mask_fields({"authorization": "Bearer x", "API_KEY": KD, "to": ["a@b.co", 3], "n": 1}),
       {"authorization": "[REDACTED]", "API_KEY": "[REDACTED]", "to": ["[EMAIL]", 3], "n": 1}, "項目名で伏せる")
    return "メール・電話3形式・kd_ と sk-ant- のキー・Bearer を伏せる／日付・req_・job_・R001・UUID は残す／authorization・api_key は値ごと [REDACTED]"


@check("V3 x-request-id：無ければ採番・正しい形式なら使う・不正なら採番し直す（不正な値はログに出さない）")
async def _():
    CAP.clear()
    url = "/api/jobs/job_none"
    bad = ["abc-123-xyz", VALID_ID.lower(), "taro@example.com", "req_" + "A" * 200]
    async with running(new_app()) as client:
        none = await client.get(url)
        given = await client.get(url, headers={"x-request-id": VALID_ID})
        rejected = [await client.get(url, headers={"x-request-id": b}) for b in bad]
    async with running(new_app(trust_incoming=False)) as client:
        ignored = await client.get(url, headers={"x-request-id": VALID_ID})
    responses = [none, given, *rejected, ignored]
    eq([r.status_code for r in responses], [404] * 7, "status")
    assert all(REQ_ID.fullmatch(r.headers["x-request-id"]) for r in responses)
    eq(given.headers["x-request-id"], VALID_ID, "正しい形式はそのまま使う")
    eq(given.json()["error"]["request_id"], VALID_ID, "エラー本文の request_id")
    eq([r.headers["x-request-id"] in bad for r in rejected], [False] * 4, "不正な値は使わない")
    assert ignored.headers["x-request-id"] != VALID_ID
    finished = [r for r in CAP.records if r["event"] == "request_finished"]
    eq([r["request_id"] for r in finished], [r.headers["x-request-id"] for r in responses], "ログと応答ヘッダ")
    eq([r["request_id_source"] for r in finished],
       ["generated", "received", "rejected", "rejected", "rejected", "rejected", "generated"], "出どころ")
    dumped = "\n".join(CAP.lines)
    eq([b in dumped for b in bad], [False] * 4, "不正な値がログに出ていない")
    return "なし → generated・正しい形式 → received・不正な4種 → rejected（採番し直し）・trust_incoming=False は常に採番・不正な値はログに出ない"


@check("V4 POST /api/ask：同じ request_id の2行（llm_call → request_finished）、本文は残さない")
async def _():
    CAP.clear()
    async with running(new_app()) as client:
        r = await client.post("/api/ask", json={"question": QUESTION})
    eq(r.status_code, 200, "status")
    rid = r.headers["x-request-id"]
    eq(r.json()["request_id"], rid, "本文の request_id")
    lines = CAP.for_request(rid)
    eq([x["event"] for x in lines], ["llm_call", "request_finished"], "この request_id の行")
    call, fin = lines
    eq((call["level"], call["outcome"], call["mode"], call["prompt_chars"], call["input_tokens"],
        call["output_tokens"], call["stop_reason"]), ("INFO", "ok", "complete", 28, 34, 181, "end_turn"), "llm_call")
    assert UPSTREAM_ID.fullmatch(call["upstream_request_id"]), call
    eq("prompt" in call, False, "既定ではプロンプト本文を残さない")
    eq((fin["method"], fin["path"], fin["status"], fin["request_id_source"]),
       ("POST", "/api/ask", 200, "generated"), "request_finished")
    dumped = "\n".join(CAP.lines)
    eq((QUESTION in dumped, ANSWER_HEAD in dumped), (False, False), "質問文・応答文がログにあるか")
    return "llm_call（ok・prompt_chars=28・input 34・output 181・end_turn・上流 req_mock_…）→ request_finished（POST /api/ask 200）・質問文と応答文は残らない"


@check("V5 上流が 500：503 の本文の request_id から、上流の request-id とステータスまで辿れる")
async def _():
    CAP.clear()
    async with running(new_app()) as client:
        r = await client.post("/api/ask", json={"question": QUESTION}, headers={"x-mock-fault": "500"})
    rid = assert_error(r, 503, "upstream_unavailable")
    lines = CAP.for_request(rid)
    eq([x["event"] for x in lines], ["llm_call", "request_finished"], "この request_id の行")
    call, fin = lines
    eq((call["level"], call["outcome"], call["upstream_status"], call["error"]),
       ("WARNING", "error", 500, "InternalServerError"), "llm_call")
    assert UPSTREAM_ID.fullmatch(call["upstream_request_id"]), call
    eq(fin["status"], 503, "request_finished")
    return "本文 503 upstream_unavailable（上流の ID は返さない）→ ログ：llm_call（WARNING・error・上流 500・InternalServerError・上流 req_mock_…）→ request_finished 503"


@check("V6 プロンプトは既定で残さない・S14_LOG_PROMPTS=true でも伏せてから先頭だけ")
async def _():
    question = "taro@example.com に1週間の献立を送ってください。電話は090-1234-5678です"
    CAP.clear()
    log = LogSettings(log_prompts=True, prompt_preview_chars=20)
    async with running(new_app(log=log)) as client:
        r = await client.post("/api/ask", json={"question": question})
    call = CAP.for_request(r.headers["x-request-id"])[0]
    eq((call["prompt_chars"], call["prompt"]), (51, "[EMAIL] に1週間の献立を送ってく"), "prompt")
    eq(("taro@" in "\n".join(CAP.lines), "090-1234" in "\n".join(CAP.lines)), (False, False), "PII が残っていない")
    eq(mask_text(question[:10]), "taro@examp", "逆順（切ってから伏せる）だとメールの一部が残る")
    return "prompt_chars=51・prompt=\"[EMAIL] に1週間の献立を送ってく\"（20文字）・切ってから伏せると \"taro@examp\" が残る"


@check("V7 SSE：ストリームの中で出したログにも request_id が付く（途中の error も同じ ID）")
async def _():
    CAP.clear()
    async with running(new_app()) as client:
        ok = await client.post("/api/ask/stream", json={"question": QUESTION})
        ng = await client.post("/api/ask/stream", json={"question": QUESTION}, headers={"x-mock-fault": "sse-error"})
    events = [e for e in sse_events([*ok.text.splitlines(), ""]) if e["event"]]
    names = [e["event"] for e in events]
    eq((names[0], names[-2:]), ("start", ["usage", "done"]), "イベントの並び")
    assert "".join(e["data"]["text"] for e in events if e["event"] == "delta").startswith(ANSWER_HEAD)
    eq(events[-2]["data"], {"input_tokens": 34, "output_tokens": 181}, "usage")
    lines = CAP.for_request(ok.headers["x-request-id"])
    eq([x["event"] for x in lines], ["llm_call", "request_finished"], "この request_id の行")
    eq((lines[0]["mode"], lines[0]["outcome"], lines[0]["output_tokens"], lines[1]["status"]),
       ("stream", "ok", 181, 200), "llm_call と request_finished")
    assert UPSTREAM_ID.fullmatch(lines[0]["upstream_request_id"]), lines[0]
    bad = [e for e in sse_events([*ng.text.splitlines(), ""]) if e["event"]]
    eq([e["event"] for e in bad], ["start", "delta", "delta", "error"], "途中で error")
    rid = ng.headers["x-request-id"]
    eq((bad[-1]["data"]["type"], bad[-1]["data"]["request_id"]), ("upstream_error", rid), "error イベント")
    call = CAP.for_request(rid)[0]
    eq((call["event"], call["outcome"], call["error"]), ("llm_call", "error", "APIStatusError"), "途中失敗のログ")
    return "start → delta… → usage（34/181）→ done・llm_call（stream・ok）→ request_finished 200／途中の error イベントとログ（outcome=error）も同じ request_id"


@check("V8 想定外の例外：500 の本文と、traceback を含むログが同じ request_id（例外の文も伏せる）")
async def _():
    app = new_app()

    async def boom() -> dict:
        raise RuntimeError("taro@example.com の献立を保存できません")

    app.add_api_route("/_verify/boom", boom, methods=["GET"])
    CAP.clear()
    async with running(app) as client:
        r = await client.get("/_verify/boom")
    eq(r.status_code, 500, "status")
    rid = r.headers["x-request-id"]
    eq(r.json(), {"error": {"type": "internal_error", "message": "サーバー内部でエラーが発生しました",
                            "request_id": rid}}, "本文")
    lines = CAP.for_request(rid)
    eq([x["event"] for x in lines], ["unhandled_error", "request_finished"], "この request_id の行")
    eq((lines[0]["level"], lines[0]["exc_type"], lines[1]["status"]), ("ERROR", "RuntimeError", 500), "値")
    assert "[EMAIL]" in lines[0]["exc"] and "taro@example.com" not in "\n".join(CAP.lines)
    return "本文 500 internal_error（固定文）・ログ unhandled_error（ERROR・RuntimeError・traceback は伏せ字済み）→ request_finished 500"


@check("V9 同時に5件：各リクエストのログの request_id は、自分の応答ヘッダと一致する")
async def _():
    CAP.clear()
    rids = [new_request_id() for _ in range(5)]
    async with running(new_app()) as client:
        rs = await asyncio.gather(*(client.post("/api/ask", json={"question": QUESTION},
                                                headers={"x-request-id": rid, "x-mock-ttft-ms": "50"})
                                    for rid in rids))
    eq([r.headers["x-request-id"] for r in rs], rids, "応答ヘッダ")
    eq(sorted(x["request_id"] for x in CAP.records if x["event"] == "llm_call"), sorted(rids), "llm_call の request_id")
    eq([[x["event"] for x in CAP.for_request(rid)] for rid in rids], [["llm_call", "request_finished"]] * 5, "行の数")
    eq(request_id_var.get(), None, "呼び出し側の文脈には残らない")
    return "5件とも llm_call → request_finished の2行・ID は自分の応答ヘッダと一致・呼び出し側の文脈は空のまま"


@check("V10 worker が s14.plan_week を読み込んでいる")
def _():
    replies = celery_app.control.inspect(timeout=3, limit=1).registered() or {}
    names = {n.split()[0] for tasks in replies.values() for n in tasks}
    assert "s14.plan_week" in names, "worker が s14.plan_week を知りません。docker compose restart worker を実行してください"
    return "s14.plan_week"


@check("V11 本物の worker：ヘッダで request_id が届き、上流が 500 のジョブの error.request_id が POST の x-request-id と一致")
async def _():
    guard_mock_env()
    PUBLISHED.clear()
    CAP.clear()
    async with running(new_app()) as client:
        ok = await client.post("/api/jobs/plan-week", json={"days": 2})
        ng = await client.post("/api/jobs/plan-week", json={"days": 2}, headers={"x-mock-fault": "500"})
        eq((ok.status_code, ng.status_code), (202, 202), "status")
        ok_job = await wait_job(client, ok.json()["job_id"])
        ng_job = await wait_job(client, ng.json()["job_id"])
    ok_rid, ng_rid = ok.headers["x-request-id"], ng.headers["x-request-id"]
    eq({h["id"]: h.get(CELERY_HEADER) for h in PUBLISHED},
       {ok_job["job_id"]: ok_rid, ng_job["job_id"]: ng_rid}, "メッセージのヘッダ kondate_request_id")
    eq((ok_job["status"], ok_job["done"], len(ok_job["result"]["days"]), ok_job["error"]),
       ("succeeded", 2, 2, None), "成功したジョブ")
    eq((ng_job["status"], ng_job["done"], ng_job["result"]), ("failed", 0, None), "失敗したジョブ")
    eq(ng_job["error"], {"type": "upstream_unavailable", "message": MESSAGES["upstream_unavailable"],
                         "request_id": ng_rid}, "失敗の本文")
    enq = [(x["request_id"], x["job_id"]) for x in CAP.records if x["event"] == "job_enqueued"]
    eq(enq, [(ok_rid, ok_job["job_id"]), (ng_rid, ng_job["job_id"])], "job_enqueued の request_id と job_id")
    return "ヘッダ kondate_request_id＝POST の x-request-id・成功 2/2・失敗は failed（upstream_unavailable・request_id は POST のもの）・job_enqueued に両方の ID"


@check("V12 worker 側の文脈：task_prerun が request_id と job_id を入れ、ジョブの全行に付く（apply で同じプロセスに）")
def _():
    guard_mock_env()
    rid, job_id = new_request_id(), f"job_{ULID()}"

    async def prepare() -> None:
        redis = make_redis()
        try:
            await create_job(redis, job_id, total=2, mock_headers={})
        finally:
            await redis.aclose()

    asyncio.run(prepare())
    CAP.clear()
    result = plan_week.apply(args=[job_id], task_id=job_id, headers={CELERY_HEADER: rid})
    eq(result.status, "SUCCESS", "apply の結果")
    lines = [x for x in CAP.records if x.get("job_id") == job_id]
    eq([x["event"] for x in lines], ["job_started", "llm_call", "llm_call", "job_finished"], "ジョブのログ")
    eq({x.get("request_id") for x in lines}, {rid}, "すべての行に同じ request_id")
    assert all(UPSTREAM_ID.fullmatch(x["upstream_request_id"]) for x in lines if x["event"] == "llm_call"), lines
    eq((request_id_var.get(), job_id_var.get()), (None, None), "終わったら消える（task_postrun）")
    return "job_started → llm_call×2 → job_finished の4行すべてに request_id と job_id・llm_call には上流の request-id・終了後は文脈が空"


finish("session14")
