"""Session 4 練習問題の解答の動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session04
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from pathlib import Path

from kondate.settings import get_settings
from kondate.verifykit import check, eq, finish
from src.session04.contract_kit import TEXT_REQ, TOOLS, event_shape, provider_under_test
from src.session04.practice_echo import EchoProvider
from src.session04.practice_portable import check_portable
from src.session04.providers import ChatRequest, LLMProvider, ProviderError, Usage, to_openai_messages

ROOT = Path(__file__).resolve().parents[2]
logging.getLogger("kondate.session04").addHandler(logging.NullHandler())


def run_pytest(path: str) -> int:
    r = subprocess.run([sys.executable, "-m", "pytest", path, "-p", "no:cacheprovider"],
                       cwd=ROOT, capture_output=True, text=True)
    lines = r.stdout.strip().splitlines()
    eq(r.returncode, 0, f"pytest の終了コード\n{r.stdout[-3000:]}{r.stderr[-2000:]}")
    m = re.search(r"(\d+) passed", lines[-1] if lines else "")
    assert m, lines[-1:]
    return int(m.group(1))


@check("P1 EchoProvider が LLMProvider を満たし、6文字ずつ返す")
async def _():
    p = EchoProvider()
    assert isinstance(p, LLMProvider)
    req = ChatRequest(messages=[{"role": "user", "content": "冷蔵庫に卵がある"}])
    result = await p.complete(req)
    events = [ev async for ev in p.stream(req)]
    eq((result.text, result.usage, result.stop_reason), ("冷蔵庫に卵がある", Usage(8, 8), "end_turn"), "complete()")
    eq(event_shape(events), "TextDelta×2 → Done", "stream()")
    return "「冷蔵庫に卵がある」→ TextDelta×2 → Done・input_tokens=8 output_tokens=8"


@check("P2 usage と stop_reason の正規化テスト（pytest）")
def _():
    passed = run_pytest("src/session04/test_normalize.py")
    eq(passed, 8, "passed の数")
    return f"{passed} passed"


@check("P3 FakeProvider で POST /api/ask を単体テストする（pytest）")
def _():
    passed = run_pytest("src/session04/test_app_fake.py")
    eq(passed, 3, "passed の数")
    return f"{passed} passed"


@check("P4 max_tokens の契約テストが3実装で通り、2つの SDK で値が一致する")
async def _():
    passed = run_pytest("src/session04/test_contract_max_tokens.py")
    eq(passed, 3, "passed の数")
    req = ChatRequest(messages=TEXT_REQ.messages, max_tokens=10)
    got = {}
    for name in ["anthropic", "openai"]:
        async with provider_under_test(name) as p:
            r = await p.complete(req)
            events = [ev async for ev in p.stream(req)]
        got[name] = (r.text, r.stop_reason, r.usage.output_tokens, event_shape(events))
    eq(got, {n: ("鶏むね肉とキャベツが", "max_tokens", 10, "TextDelta×2 → Done") for n in got}, "打ち切り")
    return f"{passed} passed・「鶏むね肉とキャベツが」・stop_reason=max_tokens・output_tokens=10・TextDelta×2 → Done"


@check("P5 交互に届くツール差分を index で束ねる（pytest）")
def _():
    passed = run_pytest("src/session04/test_interleaved.py")
    eq(passed, 3, "passed の数")
    return f"{passed} passed"


@check("P6 check_portable が OpenAI 互換へ持ち出せない指定を見つける")
def _():
    req = ChatRequest(
        messages=[
            {"role": "user", "content": [
                {"type": "text", "text": "（長い前提の説明）", "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "R999 の作り方は？"}]},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "toolu_1", "name": "get_recipe", "input": {"recipe_id": "R999"}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "見つかりません", "is_error": True}]},
            {"role": "assistant", "content": "代わりに冷蔵庫の写真を送ってください。"},
            {"role": "user", "content": [
                {"type": "image", "source": {"type": "url", "url": "https://example.com/fridge.jpg"}}]},
        ],
        tools=[{**TOOLS[1], "cache_control": {"type": "ephemeral"}}],
        model=get_settings().llm_model_light,
    )
    found = check_portable(req)
    eq(found, ["messages[0].content[0]: cache_control", "messages[2].content[0]: is_error",
               "messages[4].content[0]: unsupported:image", "tools[0]: cache_control", "model"], "点検結果")
    try:
        to_openai_messages(req.messages)
    except ProviderError as e:
        eq(e.kind, "unsupported", "画像を含むときの変換")
    else:
        raise AssertionError("画像を含む messages が変換できてしまった")
    tool_msg = to_openai_messages(req.messages[:4])[2]
    eq(tool_msg, {"role": "tool", "tool_call_id": "toolu_1", "content": "見つかりません"}, "is_error は消える")
    return f"{len(found)} 件：" + "・".join(f.split(": ")[-1] for f in found)


finish("session04 practice")
