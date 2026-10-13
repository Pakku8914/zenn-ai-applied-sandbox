"""セッション13の検証。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session13

音声認識・LLM・音声合成・VAD は決まった答えを返すものに差し替える（Whisper・VOICEVOX・mockllm を使わない）。
時刻は FixedClock で進める。生成物は out/s13/ に書く。出力に ID・時刻・ハッシュの値は出さない。
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import re
import shutil
import wave
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx2
from pypdf import PdfReader

from kondate.clock import FixedClock
from kondate.media import media_path
from kondate.settings import get_settings
from kondate.verifykit import check, eq, finish
from src.session13.app import app, sweep_forever
from src.session13.images import prepare_image
from src.session13.logmask import masked_handler, sha12
from src.session13.privacy import RETENTION, PersonalStore, image_findings, pdf_findings
from src.session13.testkit import REPLY, TEXT, Collect, count_files, sandboxed, voice_turn

OUT = Path("out/s13")
ZERO4 = {"uploads": 0, "documents": 0, "receipts": 0, "voice": 0}
COLLECT = Collect()
logging.getLogger("src.session13").handlers[:] = [masked_handler(COLLECT)]   # 画面ではなく、ここに集める


@check("V1 付帯情報の棚卸し：fridge.jpg の EXIF（GPS・機種・撮影日時）は前処理で消え、receipt.pdf はタイトルに店名を持つ")
def _():
    fridge = media_path("fridge.jpg").read_bytes()
    found = {"exif": True, "gps": True, "device": True, "taken_at": True}
    none = dict.fromkeys(found, False)
    eq(image_findings(fridge), found, "fridge.jpg")
    eq(image_findings(prepare_image(fridge).data), none, "fridge.jpg（前処理後）")
    eq(image_findings(media_path("receipt.png").read_bytes()), none, "receipt.png")
    pdf = media_path("receipt.pdf").read_bytes()
    eq(pdf_findings(pdf), {"title": True, "author": False, "creator": True}, "receipt.pdf")
    eq("こんだてマート" in (PdfReader(io.BytesIO(pdf)).metadata.title or ""), True, "PDF のタイトルの店名")
    return "fridge.jpg：EXIF・GPS・機種・撮影日時あり → 前処理後はすべてなし／receipt.png：付帯情報なし／receipt.pdf：タイトルに店名"


@check("V2 保持期限：期限ちょうどで get() から見えなくなり、sweep() がファイルごと消す（24時間・7日・30日）")
def _():
    clock = FixedClock()
    store = PersonalStore(clock)
    d = OUT / "v2"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    up, vc = d / "up_v2.jpg", d / "vc_v2.wav"
    up.write_bytes(b"x")
    vc.write_bytes(b"x")
    store.add("upload", "up_v2", "u001", path=up)
    store.add("document", "doc_v2", "u001", data=b"%PDF-")
    store.add("receipt", "rcp_v2", "u001", data={"store": "こんだてマート"})
    store.add("voice", "vc_v2", "u001", path=vc)

    clock.advance(RETENTION["upload"].total_seconds() - 1)
    eq((store.get("u001", "up_v2") is not None, store.get("u002", "up_v2")), (True, None), "24時間の1秒前（他人からは見えない）")
    eq(store.sweep(), ZERO4, "1秒前の掃除")
    clock.advance(1)
    eq((store.get("u001", "up_v2"), up.exists()), (None, True), "24時間ちょうど：掃除の前でも見えない（ファイルはまだある）")
    steps = [store.sweep()]
    clock.advance((RETENTION["voice"] - RETENTION["upload"]).total_seconds())
    steps.append(store.sweep())
    clock.advance((RETENTION["document"] - RETENTION["voice"]).total_seconds())
    steps.append(store.sweep())
    eq(steps, [{**ZERO4, "uploads": 1}, {**ZERO4, "voice": 1}, {**ZERO4, "documents": 1, "receipts": 1}],
       "24時間・7日・30日の掃除")
    eq((up.exists(), vc.exists(), store.count("u001")), (False, False, ZERO4), "ファイルと台帳")
    return "24時間の1秒前は見える／ちょうどで見えない → 掃除で upload 1件／7日で voice 1件／30日で document・receipt 各1件"


@check("V3 DELETE /api/me/data：自分の分だけを消し（ファイルも）、2回目は 0 件。x-user-id が無ければ 422")
async def _():
    fridge = media_path("fridge.jpg").read_bytes()
    receipt_pdf = media_path("receipt.pdf").read_bytes()
    book = media_path("recipe_book.pdf").read_bytes()
    model = get_settings().llm_model
    async with app.router.lifespan_context(app):
        with sandboxed(app, OUT / "v3") as state:
            COLLECT.lines.clear()
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
                for path, name, raw, user in [
                    ("/api/uploads", "山田家の冷蔵庫.jpg", fridge, "u001"),
                    ("/api/uploads", "レシート_山田.pdf", receipt_pdf, "u001"),
                    ("/api/uploads", "山田家の冷蔵庫.jpg", fridge, "u002"),
                    ("/api/documents", "recipe_book.pdf", book, "u001"),
                ]:
                    r = await client.post(path, files={"file": (name, raw)}, headers={"x-user-id": user})
                    eq(r.status_code, 201, f"{path}（{user}）")
                state.data.add("receipt", "rcp_v3", "u001", data={"store": "こんだてマート"})
                state.voice_dir.mkdir(parents=True, exist_ok=True)
                vc = state.voice_dir / "vc_v3.wav"
                vc.write_bytes(b"RIFF")
                state.data.add("voice", "vc_v3", "u001", path=vc)
                for user in ("u001", "u001", "u002"):
                    state.usage.add(user, "llm", model, input_tokens=10, output_tokens=5)
                missing = await client.delete("/api/me/data")
                first = await client.delete("/api/me/data", headers={"x-user-id": "u001"})
                second = await client.delete("/api/me/data", headers={"x-user-id": "u001"})
            remain = (state.data.count("u002"), [r.user_id for r in state.usage.records],
                      count_files(state.upload_dir), count_files(state.voice_dir))
    eq((missing.status_code, missing.json()["error"]["type"]), (422, "invalid_request"), "x-user-id なし")
    eq(first.json(), {"deleted": {**ZERO4, "uploads": 2, "documents": 1, "receipts": 1, "voice": 1, "usage": 2}},
       "1回目")
    eq(second.json(), {"deleted": {**ZERO4, "usage": 0}}, "2回目")
    eq(remain, ({**ZERO4, "uploads": 1}, ["u002"], 1, 0), "u002 の分は残る（台帳・利用記録・ファイル）")
    text = "\n".join(COLLECT.lines)
    eq(("山田" in text, text.count("upload_saved"), text.count("data_deleted")), (False, 3, 2), "ログ")
    return ("x-user-id なし 422／1回目 uploads 2・documents 1・receipts 1・voice 1・usage 2／2回目すべて 0／"
            "u002 のファイル 1 件は残る／ログにファイル名なし")


@check("V4 ログのマスク：文字起こし・ファイル名・バイト列・例外の文は、長さと SHA256 の先頭12桁か種類の名前だけになる")
def _():
    vlog = logging.getLogger("src.session13.verify")
    COLLECT.lines.clear()
    vlog.info("transcript", extra={"fields": {"user_id": "u001", "transcript": TEXT}})
    vlog.info("認識結果 %s", TEXT)
    vlog.info("upload_saved", extra={"fields": {"upload_id": "up_test", "filename": "山田家の冷蔵庫.jpg", "bytes": 89080}})
    vlog.info("voice_saved", extra={"fields": {"voice_id": "vc_test", "pcm": bytes(640)}})
    try:
        raise ValueError(f"形式が正しくありません：{TEXT}")
    except ValueError:
        vlog.exception("turn_failed", extra={"fields": {"request_id": "req_test"}})
    t, f, p = sha12(TEXT), sha12("山田家の冷蔵庫.jpg"), sha12(bytes(640))
    n = "src.session13.verify"
    eq(COLLECT.lines, [
        f"INFO {n} transcript user_id=u001 transcript=<text chars=21 sha={t}>",
        f"INFO {n} 認識結果 <text chars=21 sha={t}>",
        f"INFO {n} upload_saved upload_id=up_test filename=<text chars=11 sha={f}> bytes=89080",
        f"INFO {n} voice_saved voice_id=vc_test pcm=<bytes len=640 sha={p}>",
        f"ERROR {n} turn_failed request_id=req_test error=ValueError",
    ], "マスクしたログの行")
    return "5 行とも中身なし（文字起こし 21 文字・ファイル名 11 文字・PCM 640 バイト・例外は ValueError だけ）"


@check("V5 同意：store_audio が true のときだけ発話を WAV で保存し（7日）、ログと利用記録に文字起こしを残さない")
async def _():
    got, last = [], {}
    async with app.router.lifespan_context(app):
        for extra in ({}, {"store_audio": "yes"}, {"store_audio": True}):
            with sandboxed(app, OUT / "v5") as state:
                COLLECT.lines.clear()
                log, code = await voice_turn(app, {"type": "start", "sample_rate": 16000, **extra})
                wavs = sorted(state.voice_dir.glob("*.wav")) if state.voice_dir.is_dir() else []
                got.append((log[0]["type"], log[0]["store_audio"], len(wavs), code))
                if wavs:
                    with wave.open(str(wavs[0])) as wf:
                        last["wav"] = (wf.getframerate(), wf.getnchannels(), wf.getsampwidth(), wf.getnframes(),
                                       wavs[0].stat().st_size)
                    last["ttl"] = [h.expires_at - state.clock.now() for h in state.data.of_user("u001")]
                last["transcript"] = [m["text"] for m in log if isinstance(m, dict) and m["type"] == "transcript"]
                last["logs"] = "\n".join(COLLECT.lines)
                last["usage"] = [r.kind for r in state.usage.records]
                last["usage_json"] = json.dumps([asdict(r) for r in state.usage.records], ensure_ascii=False)
    eq(got, [("ready", False, 0, 1000), ("ready", False, 0, 1000), ("ready", True, 1, 1000)],
       "ready.store_audio・保存した WAV の数・close コード（なし／\"yes\"／true）")
    eq(last["wav"], (16000, 1, 2, 28800, 57644), "WAV（Hz・チャンネル・バイト幅・サンプル数・ファイルの大きさ）")
    eq(last["ttl"], [timedelta(days=7)], "保持期限")
    eq(last["transcript"], [TEXT], "画面へは文字起こしを返す")
    logs = last["logs"]
    eq((TEXT in logs, REPLY in logs, f"chars=21 sha12={sha12(TEXT)}" in logs,
        logs.count("bytes=57644 audio_seconds=1.8")), (False, False, True, 1), "ログ")
    eq((last["usage"], TEXT in last["usage_json"]), (["stt", "llm", "tts"], False), "利用記録")
    return ("store_audio なし・\"yes\" → 保存 0 件／true → WAV 1 件（16000Hz・モノラル・1.8 秒・57,644 バイト・期限 7日）／"
            "ログと利用記録に文字起こしなし")


@check("V6 掃除のタスクは、1回の失敗で止まらずに次の回へ進む（ログには例外の種類だけ）")
async def _():
    class FlakyStore:
        def __init__(self) -> None:
            self.calls = 0

        def sweep(self) -> dict[str, int]:
            self.calls += 1
            if self.calls == 1:
                raise PermissionError("out/uploads/up_test.jpg を消せません")
            return dict(ZERO4)

    state = SimpleNamespace(data=FlakyStore())
    COLLECT.lines.clear()
    task = asyncio.create_task(sweep_forever(state, interval=0))
    async with asyncio.timeout(5):
        while state.data.calls < 3:
            await asyncio.sleep(0)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    eq(COLLECT.lines, ["ERROR src.session13.app retention_sweep_failed error=PermissionError"], "記録")
    return "1回目の PermissionError のあとも掃除を続けた（3回以上）／記録は例外の種類だけ"


@check("V7 GET / の画面：マイクと保存の説明があり、保存の同意は既定でオフ。合成音声であることとクレジットを表示する")
async def _():
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
            page = await client.get("/")
            worklet = await client.get("/static/pcm-worklet.js")
    box = re.search(r'<input[^>]*id="store-audio"[^>]*>', page.text)
    eq((page.status_code, worklet.status_code, box is not None), (200, 200, True), "画面・worklet・チェックボックス")
    eq("checked" in box.group(0), False, "同意のチェックは既定でオフ")
    eq([s in page.text for s in ("store_audio", "/api/me/data", "合成音声", "7日", "msg.credit")], [True] * 5,
       "画面の文言と処理")
    return "GET / 200／チェックボックスは既定でオフ／store_audio・削除ボタン・合成音声の表示・クレジットあり"


finish("session13")
