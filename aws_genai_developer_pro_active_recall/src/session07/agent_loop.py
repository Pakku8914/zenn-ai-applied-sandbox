#!/usr/bin/env python3
"""セッション7: 単一エージェントの推論ループを「止まる形」で実装する。

    docker compose exec app python src/session07/agent_loop.py

やっていることは Converse API の1往復（`toolConfig` → `toolUse` → `toolResult`）を
繰り返すだけです。実務では Strands Agents や Amazon Bedrock AgentCore に載せますが、
**中で何が起きているか**を見るために本章では自分で書きます。

止め方は4つを同時に掛けます。

    1. 最大反復（max_iterations）      … 何周まで許すか
    2. タイムアウト（timeout_seconds） … 依頼1件に何秒まで使うか
    3. トークン予算（max_tokens）      … 依頼1件に何トークンまで使うか
    4. ツールの許可リスト（allowed_tools）… 実行してよい道具だけを通す

1つでは足りません。1反復が長い／太いときは反復数では守れず、反復が短いときは
時間では守れないためです。4つのうちどれで止まったかは必ず記録します。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session05")
sys.path.insert(0, "/workspace/src/session06")
sys.path.insert(0, "/workspace/src/session07")

from awskit import clients  # noqa: E402
from bedrock_mock import catalog  # noqa: E402

import conversation_store  # noqa: E402
import memory  # noqa: E402
import tools  # noqa: E402

# ツール利用に対応したモデルを選ぶ（カタログの `supports_tool_use`）。
# 計画の質が要る工程では amazon.nova-pro-v1:0 を使うが、単価は約13倍になる
MODEL_ID = "amazon.nova-lite-v1:0"

SYSTEM_PROMPT = (
    "あなたはサンプル商事の社内ヘルプデスクの担当者です。"
    "必要な情報は与えられた道具で調べ、資料に無いことは書かないでください。"
    "回答は3文以内にまとめ、根拠にした資料の出典を添えてください。"
)

MAX_OUTPUT_TOKENS = 400

# 本章で使う依頼（章をまたいで同じ入力を使い、結果を比べられるようにする）
QUESTION = (
    "有給休暇の繰越上限は何日ですか。"
    "社内規程の文書を検索して制度を確認し、私の残日数も含めて回答してください。"
)
FOLLOW_UP = "その繰越分は次年度のいつまでに使えばよいですか。社内規程の文書で確認してください。"

# 打ち切ったときに返す文。決めておかないと空文字や例外が利用者に届く
# （セッション2の縮退応答と同じ作法）
STOPPED_MESSAGE = (
    "回答を確定できなかったため、処理を打ち切りました。"
    "社内ヘルプデスク（内線1234）へお問い合わせください。"
)

# モデル側が返す停止理由と、こちら側の停止条件は混ぜずに記録する。
# 混ぜると「モデルが答え終わった」のか「こちらが打ち切った」のか区別できなくなる
MODEL_STOP_REASONS = ("end_turn", "max_tokens", "guardrail_intervened")
AGENT_STOP_REASONS = ("max_iterations", "timeout", "token_budget", "tool_not_allowed")
STOP_REASONS = MODEL_STOP_REASONS + AGENT_STOP_REASONS

# 反復ごとに必ず残す項目（可観測性の最小単位。ダッシュボード化はセッション17）
TRACE_FIELDS = ("iteration", "stopReason", "tool", "notes", "tokens", "elapsedSeconds")


@dataclass(frozen=True)
class Budget:
    """1回の依頼に許す上限。**呼び出しごとに差し替えられる**ようにしておく。"""

    max_iterations: int = 6
    timeout_seconds: float = 20.0
    max_tokens: int = 4_000
    allowed_tools: frozenset[str] = tools.DEFAULT_ALLOWED


@dataclass
class AgentResult:
    text: str
    stop_reason: str
    iterations: int = 0
    tool_calls: list[str] = field(default_factory=list)
    tokens_used: int = 0
    notes: list[str] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)

    @property
    def completed(self) -> bool:
        """モデルが自分で答え終わったときだけ True。打ち切りは完了ではない。"""
        return self.stop_reason == "end_turn"


class StepClock:
    """呼ばれるたびに一定量だけ進む偽の時計。

    タイムアウトの検証で `time.sleep` を使わないために置いています。待たせるテストは
    遅いうえ、「本当に停止条件が効いたのか」の証明になりません。
    エージェント側は**1反復に1回だけ**時計を読む約束にしてあります。
    """

    def __init__(self, step: float = 1.0, start: float = 0.0) -> None:
        self.step = step
        self.start = start
        self.calls = 0

    def __call__(self) -> float:
        value = self.start + self.calls * self.step
        self.calls += 1
        return value


class Agent:
    """道具を持った単一エージェント。ツールは自プロセス内の関数だけ。"""

    def __init__(
        self,
        runtime=None,
        agent_runtime=None,
        *,
        model_id: str = MODEL_ID,
        tool_config: dict | None = None,
        budget: Budget | None = None,
        facts: dict | None = None,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        spec, _ = catalog.resolve(model_id)
        if not spec.supports_tool_use:
            # API に投げれば ValidationException になるが、起動時に分かることを
            # 実行時まで持ち越さない（利用者の待ち時間で気づくのは最悪）
            raise ValueError(f"ツール利用に対応していないモデルです: {model_id}")
        self._runtime = runtime if runtime is not None else clients.bedrock_runtime()
        self._agent = (
            agent_runtime if agent_runtime is not None else clients.agent_runtime()
        )
        self.model_id = model_id
        self.tool_config = tool_config or tools.TOOL_CONFIG
        self.budget = budget or Budget()
        self.facts = facts or {}
        self._time_fn = time_fn

    # ------------------------------------------------------------------
    # 推論ループ（ReAct: 思考 → 行動 → 観測 の繰り返し）
    # ------------------------------------------------------------------

    def run(
        self,
        question: str,
        *,
        budget: Budget | None = None,
        history: list[dict] | None = None,
    ) -> AgentResult:
        budget = budget or self.budget

        # 短期メモリ（過去のターン）を先に積み、最後に今回の質問を置く
        messages: list[dict] = [
            {"role": row["role"], "content": [{"text": row["text"]}]}
            for row in (history or [])
        ]
        messages.append({"role": "user", "content": [{"text": question}]})

        result = AgentResult(text="", stop_reason="", messages=messages)
        started = self._time_fn()

        def finish(reason: str, text: str | None = None) -> AgentResult:
            result.stop_reason = reason
            result.text = STOPPED_MESSAGE if text is None else text
            return result

        for iteration in range(1, budget.max_iterations + 1):
            # 時計は1反復に1回だけ読む（読む回数を増やすと注入した時計の進み方が変わる）
            elapsed = self._time_fn() - started
            if elapsed >= budget.timeout_seconds:
                result.trace.append(
                    self._entry(iteration, "timeout", None, [], result.tokens_used, elapsed)
                )
                return finish("timeout")
            if result.tokens_used >= budget.max_tokens:
                result.trace.append(
                    self._entry(
                        iteration, "token_budget", None, [], result.tokens_used, elapsed
                    )
                )
                return finish("token_budget")

            response = self._runtime.converse(
                modelId=self.model_id,
                system=[{"text": SYSTEM_PROMPT}],
                messages=messages,
                toolConfig=self.tool_config,
                inferenceConfig={
                    "maxTokens": MAX_OUTPUT_TOKENS,
                    "temperature": 0.0,
                },
            )
            result.tokens_used += response["usage"]["totalTokens"]
            result.iterations = iteration
            model_stop = response["stopReason"]
            block = response["output"]["message"]["content"][0]

            if model_stop != "tool_use":
                # モデルが自分で答え終わった（または max_tokens で切れた）
                result.trace.append(
                    self._entry(
                        iteration, model_stop, None, [], result.tokens_used, elapsed
                    )
                )
                return finish(model_stop, block.get("text", ""))

            use = block["toolUse"]
            if use["name"] not in budget.allowed_tools:
                # モデルが見せた一覧（toolConfig）と、実行を許す一覧は別の層。
                # 実 AWS ではここに加えてツール側の IAM でも拒否させる
                note = f"{use['name']} は実行を許可していないツールです"
                result.notes.append(note)
                result.trace.append(
                    self._entry(
                        iteration,
                        "tool_not_allowed",
                        use["name"],
                        [note],
                        result.tokens_used,
                        elapsed,
                    )
                )
                return finish("tool_not_allowed")

            observation, step_notes = self._observe(use, question=question)
            result.notes.extend(step_notes)
            result.tool_calls.append(use["name"])
            result.trace.append(
                self._entry(
                    iteration,
                    "tool_use",
                    use["name"],
                    step_notes,
                    result.tokens_used,
                    elapsed,
                )
            )

            # 会話に「行動」と「観測」を積む。ここを積み忘れるとモデルは同じ要求を続け、
            # ループが終わらない（よくある詰まり方）
            messages.append({"role": "assistant", "content": [{"toolUse": use}]})
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "toolResult": {
                                "toolUseId": use["toolUseId"],
                                "content": [{"text": f"<context>{observation}</context>"}],
                                "status": "success",
                            }
                        }
                    ],
                }
            )

        return finish("max_iterations")

    # ------------------------------------------------------------------

    def _observe(self, use: dict, *, question: str) -> tuple[str, list[str]]:
        """ツールを実行して観測を作る。ツールの失敗ではループ全体を落とさない。"""
        args, notes = tools.validate_input(
            use["name"], use.get("input") or {}, question=question, facts=self.facts
        )
        try:
            observation = tools.call(use["name"], args, agent=self._agent)
        except Exception as exc:  # 失敗もモデルに返す情報の1つとして扱う
            notes.append(f"{use['name']} の実行に失敗しました: {type(exc).__name__}")
            observation = "道具の実行に失敗しました。取得できた情報はありません。"
        return tools.sanitize(observation), notes

    @staticmethod
    def _entry(
        iteration: int,
        stop_reason: str,
        tool: str | None,
        notes: list[str],
        tokens: int,
        elapsed: float,
    ) -> dict:
        return {
            "iteration": iteration,
            "stopReason": stop_reason,
            "tool": tool,
            "notes": list(notes),
            "tokens": tokens,  # ここまでの累計
            "elapsedSeconds": round(elapsed, 3),
        }


# ---------------------------------------------------------------------------
# モック専用の制御 API（実 AWS には存在しない）
# ---------------------------------------------------------------------------


def reset_mock() -> None:
    request = urllib.request.Request(
        f"{clients.mock_base_url()}/_mock/reset",
        data=json.dumps({}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10):
        return None


# ---------------------------------------------------------------------------
# 演習の本体
# ---------------------------------------------------------------------------


def trace_line(entry: dict) -> str:
    line = (
        f"反復{entry['iteration']}  {entry['stopReason']:<9} "
        f"{(entry['tool'] or '-'):<22}"
    )
    if entry["notes"]:
        line += "[検証] " + " / ".join(entry["notes"])
    return line.rstrip()


def summary(label: str, result: AgentResult) -> str:
    return (
        f"{label}: stop_reason={result.stop_reason}"
        f" / 反復{result.iterations}回 / ツール{len(result.tool_calls)}回"
    )


def main() -> None:
    reset_mock()
    facts = memory.bootstrap()
    agent = Agent(facts=facts)

    print("=== 1. 道具立て ===")
    spec, _ = catalog.resolve(agent.model_id)
    print(f"モデル: {agent.model_id}（ツール利用: {'対応' if spec.supports_tool_use else '非対応'}）")
    print(f"登録したツール: {', '.join(sorted(tools.TOOL_NAMES))}")
    print(f"実行を許すツール: {', '.join(sorted(agent.budget.allowed_tools))}")
    print(f"長期メモリ: {', '.join(f'{k}={v}' for k, v in sorted(facts.items()))}")

    print()
    print("=== 2. 推論ループ（思考 → 行動 → 観測 の繰り返し） ===")
    result = agent.run(QUESTION)
    for entry in result.trace:
        print(trace_line(entry))
    print(summary("結果", result))
    print(f"最終回答: {result.text}")

    print()
    print("=== 3. 停止条件を1つずつ発火させる ===")
    capped = agent.run(
        QUESTION, budget=Budget(max_iterations=len(result.tool_calls))
    )
    print(summary(f"最大反復（{len(result.tool_calls)}回で打ち切る）", capped))

    slow = Agent(facts=facts, time_fn=StepClock(step=1.0))
    timed = slow.run(QUESTION, budget=Budget(timeout_seconds=1.5))
    print(summary("タイムアウト（偽の時計で1.5秒）", timed))

    budgeted = agent.run(QUESTION, budget=Budget(max_tokens=result.trace[0]["tokens"]))
    print(summary("トークン予算（1反復ぶんに設定）", budgeted))

    blocked = result.tool_calls[-1]
    restricted = agent.run(
        QUESTION, budget=Budget(allowed_tools=tools.DEFAULT_ALLOWED - {blocked})
    )
    print(summary(f"許可リスト（{blocked} を実行禁止）", restricted))
    print(f"打ち切ったときに返す文: {capped.text}")

    print()
    print("=== 4. メモリの置き場 ===")
    ddb = conversation_store.ensure_table()
    conversation_id = "agent-demo"
    conversation_store.append_turn(ddb, conversation_id, 1, "user", QUESTION)
    conversation_store.append_turn(ddb, conversation_id, 2, "assistant", result.text)
    rows = conversation_store.turns(ddb, conversation_id)
    print(f"作業メモリ（messages）: {len(result.messages)} 件 … 依頼が終われば捨てる")
    print(f"短期メモリ（{conversation_store.TABLE_NAME}）: {len(rows)} ターン")
    print(f"長期メモリ（{memory.TABLE_NAME}）: {', '.join(sorted(facts))}")
    print(f"履歴にツール結果が混ざっていない: {all('<context>' not in r['text'] for r in rows)}")


if __name__ == "__main__":
    main()
