"""Session 5 練習問題の解答の動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session05
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import sys
from pathlib import Path

import httpx2

from kondate.verifykit import check, eq, finish, sse_events
from src.session05 import q5_fix
from src.session05.app import app, get_provider
from src.session05.harness import (PROMPT, CountingProvider, asgi_client, mock_provider, quiet_logs, read_stream,
                                   serve, wait_until)
from src.session05.q1_wire import encode_comment, encode_sse
from src.session05.q2_escape import PAYLOAD, data_bytes
from src.session05.q2_escape import app as q2_app
from src.session05.q4_measure import measure
from src.session05.q6_heartbeat import with_heartbeat

ROOT = Path(__file__).resolve().parents[2]
LOGS = quiet_logs()


def run_pytest(path: str) -> int:
    r = subprocess.run([sys.executable, "-m", "pytest", path, "-p", "no:cacheprovider"],
                       cwd=ROOT, capture_output=True, text=True)
    lines = r.stdout.strip().splitlines()
    eq(r.returncode, 0, f"pytest の終了コード\n{r.stdout[-3000:]}{r.stderr[-2000:]}")
    m = re.search(r"(\d+) passed", lines[-1] if lines else "")
    assert m, lines[-1:]
    return int(m.group(1))


@check("P1 encode_sse / encode_comment が SSE の行形式どおりに組み立てる")
def _():
    eq(encode_sse('{"text": "鶏むね肉と"}', event="delta", id="2"),
       'id: 2\nevent: delta\ndata: {"text": "鶏むね肉と"}\n\n', "id と event と data")
    eq(encode_sse("1行目\n2行目", event="note"), "event: note\ndata: 1行目\ndata: 2行目\n\n", "複数行の data")
    eq(encode_sse(retry=3000), "retry: 3000\n\n", "retry だけ")
    eq(encode_comment("ping"), ": ping\n\n", "コメント")
    for bad in [{"event": "delta\nevent: done"}, {"id": "1\n2"}, {"retry": -1}]:
        try:
            encode_sse("x", **bad)
        except ValueError:
            continue
        raise AssertionError(f"ValueError にならない: {bad}")
    evil = "塩炒め\n\nevent: done\ndata: {}"
    parsed = sse_events(encode_sse(evil, event="delta").split("\n"))
    eq([(e["event"], e["data"]) for e in parsed], [("delta", evil)], "改行を含む data")
    return "4 つの形が一致・改行入りの event / id と負の retry は ValueError・改行入りの data は1個のイベントのまま"


@check("P2 ensure_ascii の違いはバイト数に出る／raw_data で送ると日本語のまま届く")
async def _():
    eq(data_bytes(PAYLOAD), {False: 39, True: 66}, "JSON のバイト数")
    async with asgi_client(q2_app) as c:
        r = await c.get("/q2/delta")
    lines = [line for line in r.text.split("\n") if line]
    eq(lines, ["event: delta", 'data: {"text": "鶏むね肉とキャベツ"}'], "届いた行")
    return "ensure_ascii=False は 39 バイト・True は 66 バイト・/q2/delta は「鶏むね肉とキャベツ」のまま届く"


@check("P3 FakeProvider で中継のイベント列を固定する（pytest）")
def _():
    passed = run_pytest("src/session05/test_q3_relay.py")
    eq(passed, 3, "passed の数")
    return f"{passed} passed"


@check("P4 measure()：遅延ヘッダで TTFT が変わり、delta の数は変わらない")
async def _():
    got = {}
    for label, headers in [("400ms", {"x-mock-ttft-ms": "400", "x-mock-tps": "200"}), ("なし", None)]:
        async with mock_provider(headers=headers) as p:
            app.dependency_overrides[get_provider] = lambda: p
            try:
                async with serve(app, 18715) as url, httpx2.AsyncClient(timeout=60) as c:
                    got[label] = await measure(c, f"{url}/api/chat/stream", {"message": PROMPT})
            finally:
                app.dependency_overrides.clear()
    slow, fast = got["400ms"], got["なし"]
    assert slow.start_s < 0.3 and fast.start_s < 0.3, (slow, fast)
    assert slow.ttft_s is not None and slow.ttft_s >= 0.4 and slow.total_s >= 1.28, slow
    assert fast.ttft_s is not None and fast.ttft_s < 0.3, fast
    eq((slow.deltas, fast.deltas), (32, 32), "delta の数")
    return "400ms：TTFT 0.4 秒以上・全体 1.28 秒以上／遅延なし：TTFT 0.3 秒未満・どちらも start は 0.3 秒未満・delta 32 個"


@check("P5 bad は切断後も上流を最後まで読み、good はすぐに上流を閉じる")
async def _():
    result = {}
    for path in ["bad", "good"]:
        async with mock_provider(headers={"x-mock-tps": "60"}) as p:  # 1個あたり約 0.1 秒。最後まで約 3 秒
            counting = CountingProvider(p)
            q5_fix.app.dependency_overrides[q5_fix.get_provider] = lambda: counting
            try:
                async with serve(q5_fix.app, 18716) as url, httpx2.AsyncClient(timeout=60) as c:
                    await read_stream(c, f"{url}/q5/{path}", {"message": PROMPT}, stop_after_deltas=3)
                    if path == "bad":
                        await wait_until(lambda: counting.finished, 8.0, "bad の上流が最後まで読まれない")
                    else:
                        await wait_until(lambda: counting.closed, 3.0, "good の上流が閉じない")
            finally:
                q5_fix.app.dependency_overrides.clear()
        result[path] = counting
    bad, good = result["bad"], result["good"]
    eq((bad.pulled, bad.finished), (32, True), "bad：上流から読んだ数・最後まで読んだか")
    eq((good.closed, good.finished), (True, False), "good：閉じたか・最後まで読んだか")
    assert good.pulled < 32, good.pulled
    return "bad：切断後も上流を最後まで読んだ（32 個・Done まで）／good：切断後すぐに上流を閉じた（32 個未満・Done なし）"


@check("P6 with_heartbeat：黙っている間だけ ping を挟み、閉じたら元の列も閉じる")
async def _():
    def label(x: object) -> str:
        return x if isinstance(x, str) else f": {x.comment}"  # type: ignore[attr-defined]

    async def slow():
        yield "a"
        await asyncio.sleep(0.5)
        yield "b"

    async def fast():
        for x in ["a", "b", "c"]:
            yield x

    eq([label(x) async for x in with_heartbeat(slow(), 0.2)], ["a", ": ping", ": ping", "b"], "0.5 秒の沈黙")
    eq([label(x) async for x in with_heartbeat(fast(), 0.2)], ["a", "b", "c"], "すぐ届く列")

    state = {"closed": False}

    async def endless():
        try:
            n = 0
            while True:
                yield str(n)
                n += 1
                await asyncio.sleep(0.5)
        finally:
            state["closed"] = True

    hb = with_heartbeat(endless(), 0.1)
    got = [label(await anext(hb)), label(await anext(hb))]
    await hb.aclose()
    eq(got, ["0", ": ping"], "閉じる前に受け取ったもの")
    eq(state["closed"], True, "元の列が閉じたか")
    others = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    eq(others, [], "残っているタスク")
    return "0.5 秒の沈黙に interval 0.2 → a → : ping → : ping → b・すぐ届く列には ping なし・ping の直後に閉じても元の列は閉じ、タスクも残らない"


finish("session05 practice")
