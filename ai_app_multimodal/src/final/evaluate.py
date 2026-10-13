"""最終プロジェクトの評価：抽出の正解率・CER・遅延 p50/p95 を、最終のアプリ（src.final.app）の入口から測る。

    docker compose exec api python -m src.final.evaluate --update-baseline   # 基準を作る
    docker compose exec api python -m src.final.evaluate                     # 基準と比べる（悪化があれば終了コード 1）
    docker compose exec api python -m src.final.evaluate --skip-latency      # 遅延を測らない
    docker compose exec api python -m src.final.evaluate --skip-cer --targets voice --repeat 5   # 声の1ターンの内訳

基準（RULES）と終了コード（0 回帰なし／1 回帰あり／2 基準がない）はセッション12の evaluate.py と同じ。
違いは「パイプラインの関数ではなく、HTTP と WebSocket の入口から測る」こと。アプリは ASGITransport で同じプロセスに載せる。
- 抽出：POST /api/fridge/scan・/api/receipts/import。ケースごとに利用者を変える（応答キャッシュと二重取り込みの検査に当たらないように）
- CER：VOICEVOX で合成した10文を POST /api/voice/transcribe に送る
- 遅延：stt（transcribe）・tts（speak）・fridge_scan（キャッシュに当たらないよう毎回別の利用者）・voice（WS の1ターンの latency_ms）
時計は FixedClock（2026-10-02）に固定する。レシートの「未来の日付」の判定が実行日で変わらないように。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx2

from kondate.clock import FixedClock
from kondate.llm import ChatResult, FakeProvider, Usage
from kondate.media import media_path
from kondate.metrics import levenshtein, normalize_ja
from kondate.tts import Voicevox
from src.final.app import app
from src.final.asgi_ws import AsgiWebSocket
from src.final.gold import Gold, check_media, fridge_gold, receipt_gold
from src.final.matching import CaseScore, ratio, score_case, summarize
from src.final.talk import START, STOP, receive_until, send_frames, speech_pcm, utterance
from src.final.testkit import running
from src.final.textnorm import normalize_relaxed
from src.final.web import get_llm

OUT = Path("out/final/eval")
REPORT = OUT / "report.json"
BASELINE = OUT / "baseline.json"
LOOPBACK_TEXT = "鶏むね肉とキャベツで20分で作れる料理は？"
TARGETS = ("stt", "tts", "fridge_scan", "voice")
DEFAULT_TARGETS = ("stt", "tts", "fridge_scan")
MIN_FOR_P95 = 20
SENTENCES = (   # セッション8の10文（1文目は閉ループ検査の文）
    "鶏むね肉とキャベツで20分で作れる料理は？",
    "冷蔵庫に卵と牛乳とにんじんがあります。",
    "タイマーを5分にセットして。",
    "大さじ2杯は何ミリリットル？",
    "肉じゃがの作り方を最初から教えて。",
    "次の手順に進んでください。",
    "小麦を使わない晩ごはんを探して。",
    "豚こま切れ肉と玉ねぎの生姜焼きを4人分作りたい。",
    "買い物リストに豆腐とわかめを追加して。",
    "今日は30分以内で作れる和食がいいな。",
)

# 誤りを含む応答（セッション12と同じ）。採点器が誤りを数えられるかを確かめるために FakeProvider で返す
ERROR_FRIDGE = {"ingredients": [
    {"name": "キャベツ", "quantity": "1/2玉", "amount": 0.5, "unit": "玉", "confidence": 0.94, "category": "野菜"},
    {"name": "鶏ムネ肉", "quantity": "1枚", "amount": 1, "unit": "枚", "confidence": 0.88, "category": "肉"},
    {"name": "卵", "quantity": "3個", "amount": 3, "unit": "個", "confidence": 0.97, "category": "卵"},
    {"name": "にんじん", "quantity": "1本", "amount": 1, "unit": "本", "confidence": 0.81, "category": "野菜"},
    {"name": "ズッキーニ", "quantity": "1本", "amount": 1, "unit": "本", "confidence": 0.55, "category": "野菜"},
]}
ERROR_RECEIPT = {
    "store": "こんだてマート", "purchased_at": "2026-10-01", "total": 1072,
    "items": [
        {"name": "鶏むね肉", "quantity": 1, "price": 398},
        {"name": "キャベツ", "quantity": 1, "price": 198},
        {"name": "卵（10個入り）", "quantity": 1, "price": 248},
        {"name": "牛乳", "quantity": 1, "price": 223},
    ],
}


@dataclass(frozen=True)
class Rule:
    better: str
    tolerance: float
    limit: float | None = None


RULES = {
    "extraction.precision": Rule("higher", 0.0),
    "extraction.recall": Rule("higher", 0.0),
    "extraction.field_accuracy": Rule("higher", 0.0),
    "extraction.exact_match_rate": Rule("higher", 0.0),
    "cer.weighted_strict": Rule("lower", 0.01, limit=0.15),
    "cer.weighted_relaxed": Rule("lower", 0.01, limit=0.15),
}


# ---------------------------------------------------------------- 抽出の正解率（入口から）

@dataclass(frozen=True)
class Case:
    case_id: str
    kind: str                      # "fridge" か "receipt"
    gold: Gold
    fake_json: dict | None = None


def mock_cases() -> list[Case]:
    return [
        Case("fridge.jpg（mockllm）", "fridge", fridge_gold()),
        Case("receipt.png（mockllm）", "receipt", receipt_gold("receipt.png")),
        Case("receipt.pdf（mockllm）", "receipt", receipt_gold("receipt.pdf")),
    ]


def error_cases() -> list[Case]:
    return [
        Case("fridge.jpg（誤りの例）", "fridge", fridge_gold(), ERROR_FRIDGE),
        Case("receipt.png（誤りの例）", "receipt", receipt_gold("receipt.png"), ERROR_RECEIPT),
    ]


async def predict(client: httpx2.AsyncClient, case: Case, user: str) -> tuple[dict, list[dict]]:
    raw = media_path(case.gold.media).read_bytes()
    headers = {"x-user-id": user}
    if case.kind == "fridge":
        r = await client.post("/api/fridge/scan", files={"image": (case.gold.media, raw)}, headers=headers)
    else:
        r = await client.post("/api/receipts/import", files={"file": (case.gold.media, raw)}, headers=headers)
    body = r.json()
    if r.status_code not in (200, 201):    # 失敗は「予測0件」として採点に回す
        return {"items": [], "header": {}}, [{"index": None, "name": None, "reason": f"failed:{body['error']['type']}"}]
    if case.kind == "fridge":
        items = [{"name": i["name"], "amount": i["amount"]} for i in body["ingredients"]]
        return {"items": items, "header": {}}, body["issues"]
    items = [{"name": i["name"], "quantity": i["quantity"], "price": i["price"]} for i in body["items"]]
    header = {"store": body["store"], "purchased_at": body["purchased_at"], "total": body["total"]}
    return {"items": items, "header": header}, body["issues"]


def returning(obj: object) -> Callable[[], object]:
    """引数を取らない依存関数にする（引数があると FastAPI がクエリ引数と見なすため）。"""
    return lambda: obj


async def run_cases(client: httpx2.AsyncClient, cases: list[Case]) -> list[tuple[CaseScore, list[dict]]]:
    check_media({c.gold.media for c in cases})
    results = []
    for i, case in enumerate(cases):
        if case.fake_json is not None:
            fake = FakeProvider([ChatResult(json.dumps(case.fake_json, ensure_ascii=False), [], "end_turn", Usage(0, 0))])
            app.dependency_overrides[get_llm] = returning(fake)
        try:
            pred, issues = await predict(client, case, f"u{900 + i:03d}")
        finally:
            app.dependency_overrides.pop(get_llm, None)
        results.append((score_case(case.case_id, case.gold, pred), issues))
    return results


def show_cases(results: list[tuple[CaseScore, list[dict]]]) -> dict:
    for s, issues in results:
        print(f"{s.case_id}: 予測 {s.predicted}・正解 {s.gold}・一致 {s.matched}"
              f"／適合率 {ratio(s.matched, s.predicted)}・再現率 {ratio(s.matched, s.gold)}"
              f"・項目 {s.fields_correct}/{s.fields_checked}・完全一致 {'○' if s.exact else '×'}")
        if issues:
            print("    要確認：" + "・".join(f"{i['name']} {i['reason']}" if i["name"] else i["reason"] for i in issues))
    total = summarize(s for s, _ in results)
    print(f"合計 {total['cases']}件: 適合率 {total['precision']}・再現率 {total['recall']}"
          f"・項目一致率 {total['field_accuracy']}・完全一致率 {total['exact_match_rate']}")
    return total


# ---------------------------------------------------------------- CER（入口から）

def cer_weighted(pairs: Sequence[tuple[str, str]], norm: Callable[[str], str] = normalize_ja) -> float:
    edits = sum(levenshtein(norm(ref), norm(hyp)) for ref, hyp in pairs)
    chars = sum(len(norm(ref)) for ref, _ in pairs)
    return round(edits / max(1, chars), 3)


async def synthesize_wavs(texts: Sequence[str]) -> list[bytes]:
    vv = Voicevox()
    try:
        await vv.ensure_user_dict()
        return [(await vv.synthesize(t, sample_rate=16000)).wav for t in texts]
    finally:
        await vv.aclose()


async def evaluate_cer(client: httpx2.AsyncClient) -> dict:
    hyps = []
    for wav in await synthesize_wavs(SENTENCES):
        r = await client.post("/api/voice/transcribe", files={"audio": ("s.wav", wav, "audio/wav")},
                              headers={"x-user-id": "u950"})
        r.raise_for_status()
        hyps.append(r.json()["text"])
    pairs = list(zip(SENTENCES, hyps, strict=True))
    for ref, hyp in pairs:
        if normalize_ja(ref) != normalize_ja(hyp):
            print(f"  誤りのあった文：{ref} → {hyp}")
    return {"cer_weighted": cer_weighted(pairs), "cer_weighted_relaxed": cer_weighted(pairs, normalize_relaxed)}


# ---------------------------------------------------------------- 遅延（入口から。合否には使わない）

def percentile(values: Sequence[float], p: float) -> float:
    """最近傍順位法：小さい順に並べて ceil(p/100 × n) 番目の値（セッション12と同じ）。"""
    if not values:
        raise ValueError("値が1つもありません")
    ordered = sorted(values)
    return ordered[math.ceil(p * len(ordered) / 100) - 1]


def summarize_ms(values: Sequence[int]) -> dict:
    return {"n": len(values), "mean_ms": round(statistics.fmean(values)), "p50_ms": percentile(values, 50),
            "p95_ms": percentile(values, 95), "max_ms": max(values)}


async def time_ms(op: Callable[[], Awaitable[object]]) -> int:
    started = time.perf_counter()
    await op()
    return round((time.perf_counter() - started) * 1000)


async def voice_turn_ms(pcm: bytes, user: str = "u970") -> dict[str, int]:
    """WS の1ターンを流し、サーバーが turn_end で返した latency_ms をそのまま返す（20ms ごとに送る）。"""
    log: list = []
    async with AsgiWebSocket(app, headers={"x-user-id": user}) as ws:
        await ws.send_text(START)
        await send_frames(ws, utterance(pcm), realtime=True)
        await receive_until(ws, log)
        await ws.send_text(STOP)
        await receive_until(ws, log, stop_types=())
    end = next((m for m in log if isinstance(m, dict) and m["type"] == "turn_end"), None)
    if end is None:
        raise RuntimeError(f"turn_end が届きませんでした：{[m['type'] for m in log if isinstance(m, dict)]}")
    return end["latency_ms"]


async def run_latency(client: httpx2.AsyncClient, targets: Sequence[str], repeat: int) -> dict[str, dict]:
    """1回目（モデルの読み込みなどを含む）は warmup_ms として別に残し、続く repeat 回を集計する。"""
    results: dict[str, dict] = {}
    if any(t in targets for t in ("stt", "voice")):
        pcm = await speech_pcm(LOOPBACK_TEXT)
    if "stt" in targets:
        wav = (await synthesize_wavs([LOOPBACK_TEXT]))[0]

        async def stt_op() -> None:
            r = await client.post("/api/voice/transcribe", files={"audio": ("l.wav", wav, "audio/wav")})
            r.raise_for_status()

        samples = [await time_ms(stt_op) for _ in range(repeat + 1)]
        results["stt"] = {"warmup_ms": samples[0], **summarize_ms(samples[1:])}
    if "tts" in targets:
        async def tts_op() -> None:
            r = await client.post("/api/voice/speak", json={"text": LOOPBACK_TEXT})
            r.raise_for_status()

        samples = [await time_ms(tts_op) for _ in range(repeat + 1)]
        results["tts"] = {"warmup_ms": samples[0], **summarize_ms(samples[1:])}
    if "fridge_scan" in targets:
        raw = media_path("fridge.jpg").read_bytes()
        samples = []
        for i in range(repeat + 1):
            async def scan_op(user: str = f"u{(800 + i) % 1000:03d}") -> None:   # 毎回別の利用者＝キャッシュに当たらない
                r = await client.post("/api/fridge/scan", files={"image": ("fridge.jpg", raw)}, headers={"x-user-id": user})
                r.raise_for_status()
            samples.append(await time_ms(scan_op))
        results["fridge_scan"] = {"warmup_ms": samples[0], **summarize_ms(samples[1:])}
    if "voice" in targets:
        turns = [await voice_turn_ms(pcm) for _ in range(repeat + 1)]
        for key in ("vad", "stt", "llm_first_sentence", "tts_first", "first_audio"):
            results[f"voice.{key}"] = {"warmup_ms": turns[0][key], **summarize_ms([t[key] for t in turns[1:]])}
    return results


# ---------------------------------------------------------------- 報告と基準との比較（セッション12と同じ）

def build_report(extraction: dict, cer_row: dict | None, latency: dict | None) -> dict:
    deterministic = {f"extraction.{k}": extraction[k] for k in ("precision", "recall", "field_accuracy", "exact_match_rate")}
    if cer_row is not None:
        deterministic["cer.weighted_strict"] = cer_row["cer_weighted"]
        deterministic["cer.weighted_relaxed"] = cer_row["cer_weighted_relaxed"]
    environment = {}
    for name, s in (latency or {}).items():
        environment[f"latency.{name}.p50_ms"] = s["p50_ms"]
        environment[f"latency.{name}.p95_ms"] = s["p95_ms"]
    return {"deterministic": deterministic, "environment": environment}


def find_regressions(current: dict, baseline: dict, rules: dict[str, Rule] = RULES) -> list[str]:
    now, before = current["deterministic"], baseline["deterministic"]
    found = []
    for key, rule in rules.items():
        if key not in now:
            found.append(f"{key}：今回の結果にありません")
            continue
        value = now[key]
        sign = 1 if rule.better == "higher" else -1
        if rule.limit is not None and sign * (value - rule.limit) < 0:
            word = "下限 {} を下回りました" if rule.better == "higher" else "上限 {} を超えました"
            found.append(f"{key}：{value} が{word.format(rule.limit)}")
        old = before.get(key)
        if old is not None and round(sign * (value - old), 6) < -rule.tolerance:
            found.append(f"{key}：{old} → {value}（悪化。許容幅 {rule.tolerance}）")
    return found


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def collect(a: argparse.Namespace) -> tuple[dict, dict | None]:
    async with running(clock=FixedClock(), out=OUT / "work") as client:
        extraction = show_cases(await run_cases(client, mock_cases()))
        cer_row = None if a.skip_cer else await evaluate_cer(client)
        latency = None if a.skip_latency else await run_latency(client, a.targets, a.repeat)
    return build_report(extraction, cer_row, latency), latency


def main() -> int:
    p = argparse.ArgumentParser(description="最終のアプリの入口から、抽出・CER・遅延を測って基準と比べる")
    p.add_argument("--update-baseline", action="store_true")
    p.add_argument("--skip-latency", action="store_true")
    p.add_argument("--skip-cer", action="store_true")
    p.add_argument("--targets", nargs="+", default=list(DEFAULT_TARGETS), choices=TARGETS)
    p.add_argument("--repeat", type=int, default=MIN_FOR_P95)
    a = p.parse_args()

    report, latency = asyncio.run(collect(a))
    for key, value in report["deterministic"].items():
        print(f"[決定的] {key} = {value}")
    for name, s in (latency or {}).items():
        note = "（n<20 なので p95 は最大値と同じ）" if s["n"] < MIN_FOR_P95 else ""
        print(f"[環境依存] {name}：準備 {s['warmup_ms']}ms ／ n={s['n']}・p50 {s['p50_ms']}ms・p95 {s['p95_ms']}ms{note}")
    write_json(REPORT, report)
    print(f"→ {REPORT}")

    if a.update_baseline:
        write_json(BASELINE, report)
        print(f"基準を保存しました：{BASELINE}")
        return 0
    if not BASELINE.exists():
        print("基準がありません。先に --update-baseline で作ってください")
        return 2
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    rules = {k: r for k, r in RULES.items() if k in report["deterministic"]}   # 測らなかった指標は比べない
    found = find_regressions(report, baseline, rules)
    for line in found:
        print(f"回帰：{line}")
    print(f"回帰なし（決定的な指標 {len(rules)} 件を基準と比較）" if not found else f"回帰 {len(found)} 件")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
