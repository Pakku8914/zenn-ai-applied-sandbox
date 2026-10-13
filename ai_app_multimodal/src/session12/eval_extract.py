"""抽出の正解率を測る（セッション12）。mockllm で測るのは「モデルの精度」ではなく「パイプラインの回帰」。

    docker compose exec api python -m src.session12.eval_extract
    docker compose exec api python -m src.session12.eval_extract --with-error-cases   # 誤りを含む応答も混ぜる

正解データは tools/make_media.py の元データ（gold.py）。結果は out/s12/extraction.json に書く。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import anyio
from anthropic import AsyncAnthropic

from kondate.llm import AnthropicProvider, ChatResult, FakeProvider, LLMProvider, Usage
from kondate.media import media_path
from src.session12 import target_fridge as fridge
from src.session12 import target_receipt as receipt
from src.session12.gold import Gold, check_media, fridge_gold, receipt_gold
from src.session12.matching import CaseScore, ratio, score_case, summarize

OUT = Path("out/s12")
TODAY = date(2026, 10, 2)   # 「未来の日付」の判定に使う日。評価の結果が実行日で変わらないよう固定する
FAILED = (fridge.InvalidOutput, fridge.UpstreamUnavailable, ValueError)

# 誤りを含む応答（FakeProvider で返す）。mockllm は毎回正しく答えるので、採点器が誤りを数えられるかはこれで確かめる
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
class Case:
    case_id: str
    kind: str                      # "fridge" か "receipt"
    gold: Gold
    fake_json: dict | None = None  # 指定すると LLM の代わりにこの応答を返す


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


async def predict(case: Case, llm: LLMProvider) -> tuple[dict, list[dict]]:
    """パイプラインを通し、採点できる形 {items, header} と要確認の印を返す。失敗したら「予測0件」として採点に回す。"""
    raw = media_path(case.gold.media).read_bytes()
    try:
        if case.kind == "fridge":
            jpeg = await anyio.to_thread.run_sync(fridge.prepare_image, raw)
            scan = await fridge.scan_fridge(llm, jpeg)
            items = [{"name": i.name, "amount": i.amount} for i in scan.ingredients]
            return {"items": items, "header": {}}, fridge.find_issues(scan.ingredients)
        kind, data = await anyio.to_thread.run_sync(receipt.accept_receipt, raw)
        read = await receipt.read_receipt(llm, kind, data)
        items = [{"name": i.name, "quantity": i.quantity, "price": i.price} for i in read.items]
        header = {"store": read.store, "purchased_at": read.purchased_at, "total": read.total}
        return {"items": items, "header": header}, receipt.check_receipt(read, TODAY)
    except FAILED as e:
        return {"items": [], "header": {}}, [{"index": None, "name": None, "reason": f"failed:{type(e).__name__}"}]


def fake(case: Case) -> FakeProvider:
    text = json.dumps(case.fake_json, ensure_ascii=False)
    return FakeProvider([ChatResult(text, [], "end_turn", Usage(0, 0))])


async def run_cases(cases: list[Case]) -> list[tuple[CaseScore, list[dict]]]:
    check_media({c.gold.media for c in cases})
    client = AsyncAnthropic()  # 接続先は ANTHROPIC_BASE_URL（既定は mockllm）
    try:
        results = []
        for case in cases:
            llm = fake(case) if case.fake_json is not None else AnthropicProvider(client)
            pred, issues = await predict(case, llm)
            results.append((score_case(case.case_id, case.gold, pred), issues))
        return results
    finally:
        await client.close()


def issue_text(issues: list[dict]) -> str:
    return "・".join(f"{i['name']} {i['reason']}" if i["name"] else i["reason"] for i in issues)


def show(results: list[tuple[CaseScore, list[dict]]]) -> dict:
    for s, issues in results:
        print(f"{s.case_id}: 予測 {s.predicted}・正解 {s.gold}・一致 {s.matched}"
              f"／適合率 {ratio(s.matched, s.predicted)}・再現率 {ratio(s.matched, s.gold)}"
              f"・項目 {s.fields_correct}/{s.fields_checked}・完全一致 {'○' if s.exact else '×'}")
        for err in s.errors:
            print(f"    {err}")
        if issues:
            print(f"    要確認：{issue_text(issues)}")
    total = summarize(s for s, _ in results)
    print(f"合計 {total['cases']}件: 適合率 {total['precision']}・再現率 {total['recall']}"
          f"・項目一致率 {total['field_accuracy']}・完全一致率 {total['exact_match_rate']}")
    return total


def to_json(results: list[tuple[CaseScore, list[dict]]], total: dict) -> dict:
    cases = [{**asdict(s), "exact": s.exact, "issues": [i["reason"] for i in issues]} for s, issues in results]
    return {"summary": total, "cases": cases}


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="抽出の正解率を測る")
    p.add_argument("--with-error-cases", action="store_true", help="誤りを含む応答（FakeProvider）も混ぜる")
    a = p.parse_args()
    cases = mock_cases() + (error_cases() if a.with_error_cases else [])
    print("正解データ：tools/make_media.py の元データ（画像・PDF の版を確認済み）")
    results = asyncio.run(run_cases(cases))
    total = show(results)
    write_json(OUT / "extraction.json", to_json(results, total))
    print(f"→ {OUT / 'extraction.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
