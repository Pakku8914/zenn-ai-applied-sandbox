"""セッション4の動作確認。api コンテナの中で実行する：

    docker compose exec api python src/session04/verify.py

アプリは httpx2.ASGITransport で同じプロセスに載せ、LLM は依存関係 get_llm を差し替えて渡す
（api の APP_MODULE が何であっても実行できる）。mockllm に実際に送るもの（V2・V5・V6）と、
FakeProvider で失敗を作るもの（V3・V4・V7）がある。
"""

from __future__ import annotations

import json
import logging

import httpx2
from anthropic import AsyncAnthropic

from kondate.llm import AnthropicProvider, ChatResult, FakeProvider, LLMProvider, Usage
from kondate.media import media_path
from kondate.settings import get_settings
from kondate.verifykit import check, eq, finish
from src.session04.app import app, get_llm
from src.session04.intake import accept_image
from src.session04.models import FRIDGE_SCHEMA, FridgeScan
from src.session04.recipes import SearchRecipesIn, search_recipes, to_search_args
from src.session04.review import confirmed_names, find_issues
from src.session04.scan import InvalidOutput, error_summary, scan_fridge

logging.getLogger("src.session04").setLevel(logging.ERROR)  # 失敗を作ったときの警告で出力が乱れないように

MOCK = get_settings().mockllm_url
FRIDGE = media_path("fridge.jpg").read_bytes()
NAMES = ["キャベツ", "鶏むね肉", "卵", "にんじん", "牛乳"]
FIELDS = ["name", "quantity", "amount", "unit", "confidence", "category"]
MSG_502 = "読み取り結果の形式が正しくありませんでした"
MSG_503 = "画像の読み取りに失敗しました。時間をおいて試してください"


def item(name: str, confidence: float = 0.9, **over) -> dict:
    """食材1件の辞書。値に None を渡した項目は取り除く（欠けた項目を作るため）。"""
    d = {"name": name, "quantity": "1個", "amount": 1, "unit": "個", "confidence": confidence, "category": "野菜"}
    d.update(over)
    return {k: v for k, v in d.items() if v is not None}


def answer(items: list[dict], output_tokens: int = 120, stop: str = "end_turn") -> ChatResult:
    text = json.dumps({"ingredients": items}, ensure_ascii=False)
    return ChatResult(text, [], stop, Usage(1668, output_tokens), "req_fake")


GOOD = [item(n) for n in NAMES]


async def post(llm: LLMProvider, field: str = "image", raw: bytes = FRIDGE) -> httpx2.Response:
    app.dependency_overrides[get_llm] = lambda: llm
    try:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as c:
            return await c.post("/api/fridge/scan", files={field: ("fridge.jpg", raw, "image/jpeg")})
    finally:
        app.dependency_overrides.clear()


async def mock(method: str, path: str) -> dict:
    async with httpx2.AsyncClient(base_url=MOCK, timeout=10) as c:
        r = await c.request(method, path)
        r.raise_for_status()
        return r.json()


def rejected(r: httpx2.Response, status: int, type_: str, message: str) -> None:
    eq(r.status_code, status, f"status（本文 {r.text}）")
    err = r.json()["error"]
    eq((err["type"], err["message"]), (type_, message), "エラー本文")
    eq(err["request_id"], r.headers["x-request-id"], "request_id がヘッダーと同じ")


@check("V1 transform_schema は additionalProperties: false を足し、値の範囲・長さの制約をスキーマから外して説明文に移す")
def _():
    ing = FRIDGE_SCHEMA["$defs"]["Ingredient"]
    eq(ing["required"], FIELDS, "必須の項目")
    eq((FRIDGE_SCHEMA["additionalProperties"], ing["additionalProperties"]), (False, False), "additionalProperties")
    constraints = {"name": ["minLength", "maxLength"], "amount": ["exclusiveMinimum"], "confidence": ["minimum", "maximum"]}
    for field, keys in constraints.items():
        prop = ing["properties"][field]
        eq([k for k in keys if k in prop], [], f"{field} のスキーマに残った制約")
        eq([k for k in keys if k in prop.get("description", "")], keys, f"{field} の説明文に書き写された制約")
    return "必須 6 項目・additionalProperties=False・name/amount/confidence の制約は説明文へ"


@check("V2 mockllm に fridge.jpg を送ると、5件の食材・要確認なし・usage 1668/194 が1回で返る")
async def _():
    await mock("POST", "/_mock/reset")
    client = AsyncAnthropic()
    try:
        r = await post(AnthropicProvider(client))
    finally:
        await client.close()
    eq(r.status_code, 200, f"status（本文 {r.text}）")
    body = r.json()
    eq(list(body), ["ingredients", "needs_review", "issues", "image", "usage"], "応答の項目")
    eq([i["name"] for i in body["ingredients"]], NAMES, "食材の名前")
    eq(body["ingredients"][0], {"name": "キャベツ", "quantity": "1/2玉", "amount": 0.5, "unit": "玉",
                                "confidence": 0.94, "category": "野菜"}, "1件目の6項目")
    eq((body["needs_review"], body["issues"]), (False, []), "要確認")
    eq((body["image"]["bytes"], body["image"]["exif_removed"]), (89080, True), "送った画像")
    eq(body["usage"], {"input_tokens": 1668, "output_tokens": 194}, "usage")
    eq((await mock("GET", "/_mock/stats"))["by_scenario"], {"fridge_photo": 1}, "mockllm が使ったシナリオと回数")
    return "キャベツ・鶏むね肉・卵・にんじん・牛乳／input_tokens=1668・output_tokens=194"


@check("V3 範囲外の confidence が2回続くと、2回呼んだうえで 502 invalid_output")
async def _():
    bad = answer([item("キャベツ", 1.5)] + GOOD[1:])
    fake = FakeProvider([bad, bad])
    rejected(await post(fake), 502, "invalid_output", MSG_502)
    eq(len(fake.requests), 2, "LLM を呼んだ回数")
    eq(fake.requests[0].output_schema, FRIDGE_SCHEMA, "output_schema に変換済みのスキーマを渡している")
    try:
        FridgeScan.model_validate_json(bad.text)
    except Exception as e:
        summary = error_summary(e)
    eq(summary, ["ingredients.0.confidence: less_than_equal"], "違反の要約")
    return f"{summary[0]} ×2 → 502"


@check("V4 1回目に項目が欠けても、再試行の2回目が正しければ 200（usage は2回分の合計）")
async def _():
    broken = [item(n, unit=None) if n == "卵" else item(n) for n in NAMES]
    fake = FakeProvider([answer(broken, 120), answer(GOOD, 194)])
    r = await post(fake)
    eq(r.status_code, 200, f"status（本文 {r.text}）")
    eq(len(fake.requests), 2, "LLM を呼んだ回数")
    eq(r.json()["usage"], {"input_tokens": 3336, "output_tokens": 314}, "usage（2回分）")
    try:
        FridgeScan.model_validate_json(answer(broken).text)
    except Exception as e:
        summary = error_summary(e)
    eq(summary, ["ingredients.2.unit: missing"], "1回目の違反")
    return f"{summary[0]} → 再試行で成功・input_tokens=3336・output_tokens=314"


@check("V5 max_tokens で打ち切られた応答は再試行せず失敗にする（mockllm に max_tokens=100 で送る）")
async def _():
    await mock("POST", "/_mock/reset")
    client = AsyncAnthropic()
    try:
        await scan_fridge(AnthropicProvider(client), accept_image(FRIDGE).data, max_tokens=100)
        raise AssertionError("InvalidOutput にならなかった")
    except InvalidOutput as e:
        eq((e.reason, e.attempts), ("max_tokens", 1), "失敗の理由と試行回数")
        assert e.usage.output_tokens <= 100, e.usage
    finally:
        await client.close()
    reqs = (await mock("GET", "/_mock/stats"))["requests"]
    eq([q["stop_reason"] for q in reqs], ["max_tokens"], "mockllm が受けたリクエストの stop_reason")
    return "stop_reason=max_tokens・mockllm への送信 1 回"


@check("V6 上流が 529 を返すと 503 upstream_unavailable（上流の文は返さない）")
async def _():
    await mock("POST", "/_mock/reset")
    client = AsyncAnthropic(default_headers={"x-mock-fault": "529"}, max_retries=0)
    try:
        r = await post(AnthropicProvider(client))
    finally:
        await client.close()
    rejected(r, 503, "upstream_unavailable", MSG_503)
    assert "mockllm" not in r.text and "overloaded" not in r.text, r.text
    eq((await mock("GET", "/_mock/stats"))["by_status"], {"529": 1}, "mockllm が返した状態コード")
    return f"529 → 503「{MSG_503}」"


@check("V7 confidence 0.6 未満と食材辞書に無い名前に、要確認の印が付く（食材は消さない）")
async def _():
    items = [item("キャベツ", 0.94), item("鶏ムネ肉", 0.9), item("にんじん", 0.42), item("ズッキーニ", 0.35), item("卵", 0.6)]
    r = await post(FakeProvider([answer(items)]))
    eq(r.status_code, 200, f"status（本文 {r.text}）")
    body = r.json()
    eq(len(body["ingredients"]), 5, "ingredients の件数")
    eq(body["needs_review"], True, "needs_review")
    eq([(i["index"], i["name"], i["reason"]) for i in body["issues"]], [
        (1, "鶏ムネ肉", "unknown_name"),
        (2, "にんじん", "low_confidence"),
        (3, "ズッキーニ", "low_confidence"),
        (3, "ズッキーニ", "unknown_name"),
    ], "issues")
    return "鶏ムネ肉→unknown_name・にんじん(0.42)→low_confidence・ズッキーニ(0.35)→両方・卵(0.6)→なし"


def ids(args: SearchRecipesIn) -> list[str]:
    return [r["id"] for r in search_recipes(args)["recipes"]]


@check("V8 search_recipes は一致数→minutes→id の順に並べ、limit は 10 まで")
def _():
    eq(ids(SearchRecipesIn(ingredients=NAMES)), ["R064", "R067", "R001", "R025", "R095"], "冷蔵庫の5食材")
    eq(ids(SearchRecipesIn(ingredients=["鶏むね肉", "キャベツ"], max_minutes=20)),
       ["R001", "R067", "R083", "R112", "R009"], "鶏むね肉+キャベツ・20分以内")
    first = search_recipes(SearchRecipesIn(ingredients=NAMES))["recipes"][0]
    eq(list(first), ["id", "name", "minutes", "kcal", "tags"], "1件の項目")
    for bad in ({"limit": 11}, {"ingredients": NAMES * 3}, {"max_minutes": 0}):
        try:
            SearchRecipesIn(**bad)
            raise AssertionError(f"{bad} が通ってしまった")
        except ValueError:  # pydantic の ValidationError は ValueError の仲間
            pass
    return "5食材→R064,R067,R001,R025,R095／鶏むね肉+キャベツ・20分以内→R001,R067,R083,R112,R009"


@check("V9 要確認を除いた食材だけを search_recipes に渡す")
def _():
    items = [item("キャベツ", 0.94), item("鶏ムネ肉", 0.9), item("にんじん", 0.42), item("ズッキーニ", 0.35), item("卵", 0.6)]
    scan = FridgeScan.model_validate_json(answer(items).text)
    names = confirmed_names(scan.ingredients, find_issues(scan.ingredients))
    eq(names, ["キャベツ", "卵"], "確認済みの食材")
    got = ids(to_search_args(names))
    eq(got, ["R119", "R039", "R038", "R064", "R067"], "検索結果")
    return f"キャベツ・卵 → {','.join(got)}"


@check("V10 受付検査はセッション2・3と同じ（画像でなければ 415、項目名が違えば 422）")
async def _():
    never = FakeProvider([])  # LLM まで届かないことも確かめる（呼ばれたら RuntimeError）
    rejected(await post(never, raw="鶏むね肉 1枚\n".encode()), 415, "unsupported_media", "JPEG・PNG・WebP・GIF の画像を送ってください")
    rejected(await post(never, field="file"), 422, "invalid_request", "入力値が正しくありません：image")
    eq(len(never.requests), 0, "LLM を呼んだ回数")
    return "テキスト→415・項目名 file→422"


finish("session04")
