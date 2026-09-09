#!/usr/bin/env python3
"""セッション10: スロットリングとリトライの実測。

    docker compose exec app python src/session10/retry_lab.py

`POST /_mock/behavior {"throttle_next": N}` で次の N 回を確実に HTTP 429
（`ThrottlingException`）にできます。乱数で失敗させないので、
「何回試行したか」「何回スロットリングされたか」を数字で確かめられます。

扱うのは2層です。
  1. boto3 に任せる層 … `max_attempts` と `mode`
  2. 自分で書く層     … 指数バックオフ ＋ ジッター（上限つき）

**リトライ回数は思い込みで書かず、必ず数えます。** この環境（boto3 1.43.89）で
`throttle_next` を多めに入れて `GET /_mock/usage` の `throttled` を読むと、
`max_attempts=N` の指定に対して **N+1 回**のリクエストが飛びました
（`max_attempts=1` でも2回）。数え方は `run_matrix()` を参照してください。

**リトライは「一時的な失敗」にしか効きません。** どのエラーが一時的かの
分類はセッション2で作った `FATAL_CODES` を再利用します（設定・権限・
リクエストの誤りは、何回投げても直りません）。
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session01")
sys.path.insert(0, "/workspace/src/session02")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from botocore.exceptions import ClientError  # noqa: E402

from awskit import clients  # noqa: E402

import model_router  # noqa: E402
import poc_probe  # noqa: E402
import streaming  # noqa: E402

# 待てば直る見込みのあるエラー。これ以外は再試行しない
RETRYABLE_CODES = frozenset(
    {
        "ThrottlingException",
        "ServiceUnavailableException",
        "InternalServerException",
        "ModelNotReadyException",
    }
)

# 教材では待ち時間を短くしている。実務の出発点は base 0.5〜1 秒 / cap 20 秒
BASE_DELAY_SECONDS = 0.05
MAX_DELAY_SECONDS = 0.40


def backoff_window(attempt: int, *, base: float = BASE_DELAY_SECONDS,
                   cap: float = MAX_DELAY_SECONDS) -> float:
    """`attempt` 回目の再試行までに許される最大待ち時間（秒）。

    指数（`base * 2 ** attempt`）で伸ばし、`cap` で頭を押さえます。
    頭を押さえないと、5回目の再試行で数十秒待つ実装になります。
    """
    return min(cap, base * (2**attempt))


def backoff_delay(
    attempt: int,
    *,
    base: float = BASE_DELAY_SECONDS,
    cap: float = MAX_DELAY_SECONDS,
    jitter: bool = True,
    rng: random.Random | None = None,
) -> float:
    """実際に待つ秒数。既定は full jitter（0 〜 窓の一様乱数）。

    ジッターが無いと、同時に失敗した呼び出し元が**揃って**同じ時刻に
    再送します（thundering herd）。相手が復旧しかけたところへ全員で
    殺到するので、ジッターは飾りではなく必須です。
    """
    window = backoff_window(attempt, base=base, cap=cap)
    if not jitter:
        return window
    return (rng or random).uniform(0.0, window)


def backoff_plan(
    attempts: int,
    *,
    base: float = BASE_DELAY_SECONDS,
    cap: float = MAX_DELAY_SECONDS,
    jitter: bool = True,
    seed: int | None = None,
) -> list[float]:
    """再試行ごとの待ち時間を並べる（本文の表を作るため）。"""
    rng = random.Random(seed) if seed is not None else None
    return [
        backoff_delay(i, base=base, cap=cap, jitter=jitter, rng=rng)
        for i in range(attempts)
    ]


def call_with_backoff(
    runtime,
    question: str,
    source: str | None = None,
    *,
    model_id: str = streaming.DEFAULT_MODEL,
    max_attempts: int = 4,
    rng: random.Random | None = None,
    sleep=time.sleep,
) -> dict:
    """自分でリトライする版。`runtime` は `max_attempts=1` で作ること。

    boto3 に任せる場合との違いは「何が起きたかを自分で記録できる」点です。
    試行回数・待った時間・最後のエラーコードを呼び出し元へ返せるため、
    監視に出す値を作れます（何を出すかはセッション17で扱います）。

    ここで返る `attempts` は**この関数が回した回数**です。SDK 側にもリトライが
    残っている場合、実際に飛ぶリクエスト数は掛け算になります
    （この環境では `max_attempts=1` でも1回あたり2リクエスト）。
    数えるのは `attempts` ではなく `GET /_mock/usage` の側です。
    """
    waited: list[float] = []
    attempts = 0
    while True:
        attempts += 1
        try:
            answer = streaming.sync_answer(
                runtime, question, source, model_id=model_id
            )
        except ClientError as error:
            code = error.response["Error"]["Code"]
            if code in model_router.FATAL_CODES:
                # 何回投げても直らない。握りつぶすと設定ミスに永遠に気づけない
                raise
            if code not in RETRYABLE_CODES:
                raise
            if attempts >= max_attempts:
                return {
                    "outcome": code,
                    "attempts": attempts,
                    "waited": waited,
                    "text": None,
                }
            delay = backoff_delay(attempts - 1, rng=rng)
            waited.append(delay)
            sleep(delay)
            continue
        return {
            "outcome": "ok",
            "attempts": attempts,
            "waited": waited,
            "text": answer["text"],
            "outputTokens": answer["usage"]["outputTokens"],
        }


# ---------------------------------------------------------------------------
# boto3 に任せる層の実測
# ---------------------------------------------------------------------------

# throttle は「注入するスロットリング回数」、requests は「モックが実際に
# 429 を返した回数」の期待値（＝ max_attempts + 1。実測値）。
# None は「断定しない（観測するだけ）」
ROWS: tuple[dict, ...] = (
    {
        "label": "standard / max_attempts=1",
        "mode": "standard",
        "maxAttempts": 1,
        "throttle": 5,
        "expectOutcome": "ThrottlingException",
        "expectRequests": 2,
    },
    {
        "label": "standard / max_attempts=3",
        "mode": "standard",
        "maxAttempts": 3,
        "throttle": 5,
        "expectOutcome": "ThrottlingException",
        "expectRequests": 4,
    },
    {
        "label": "standard / max_attempts=4",
        "mode": "standard",
        "maxAttempts": 4,
        "throttle": 2,
        "expectOutcome": "ok",
        "expectRequests": 2,
    },
    {
        "label": "legacy   / max_attempts=1",
        "mode": "legacy",
        "maxAttempts": 1,
        "throttle": 5,
        "expectOutcome": "ThrottlingException",
        "expectRequests": 2,
    },
    {
        # legacy はサービスごとの判定表（botocore の _retry.json）で
        # 「このエラーコードとこの HTTP ステータスなら再試行」を決めるため、
        # 何回試行するかが版とサービスに依存する。**依存させないために
        # standard を明示する**ことが本節の結論なので、ここは断定しない
        "label": "legacy   / max_attempts=4",
        "mode": "legacy",
        "maxAttempts": 4,
        "throttle": 2,
        "expectOutcome": None,
        "expectRequests": None,
    },
)


def run_row(row: dict, question: str, source: str | None) -> dict:
    """1行分の実験。スロットリング設定は必ず行の終わりで戻す。"""
    model_router.set_behavior(throttle_next=row["throttle"])
    before = model_router.mock_usage()["throttled"]
    runtime = clients.bedrock_runtime(
        max_attempts=row["maxAttempts"], mode=row["mode"]
    )
    started = time.perf_counter()
    outcome = "ok"
    try:
        streaming.sync_answer(runtime, question, source)
    except ClientError as error:
        outcome = error.response["Error"]["Code"]
    elapsed_ms = (time.perf_counter() - started) * 1000
    after = model_router.mock_usage()["throttled"]
    # 次の行へ残すと結果が読めなくなる
    model_router.set_behavior(throttle_next=0)
    return {
        "label": row["label"],
        "mode": row["mode"],
        "maxAttempts": row["maxAttempts"],
        "throttleInjected": row["throttle"],
        "outcome": outcome,
        "requests": after - before,
        "wallMs": elapsed_ms,
        "expectOutcome": row["expectOutcome"],
        "expectRequests": row["expectRequests"],
    }


def run_matrix(question: str, source: str | None) -> list[dict]:
    return [run_row(row, question, source) for row in ROWS]


# ---------------------------------------------------------------------------
# 演習の本体
# ---------------------------------------------------------------------------


def main() -> None:
    model_router.reset_mock()
    question, source = poc_probe.QUESTIONS[0]

    print("=== 1. 指数バックオフの窓とジッター ===")
    print("試行  窓(秒)  ジッター無し  ジッターあり(seed=11)")
    plain = backoff_plan(4, jitter=False)
    jittered = backoff_plan(4, jitter=True, seed=11)
    for i in range(4):
        print(f"  {i + 1}   {backoff_window(i):.3f}   {plain[i]:.3f}"
              f"         {jittered[i]:.3f}")
    print(f"合計待ち時間: ジッター無し {sum(plain):.3f} 秒 / "
          f"ありは 0〜{sum(plain):.3f} 秒の範囲に散る")

    print()
    print("=== 2. boto3 に任せる層（mode と max_attempts） ===")
    print("設定                        注入  実際の429  結果")
    for row in run_matrix(question, source):
        print(f"{row['label']:<26} {row['throttleInjected']:>4}"
              f"  {row['requests']:>8}   {row['outcome']}")
    print("この環境の実測では、飛んだリクエストは max_attempts + 1 回でした。")
    print("回数は仕様の記憶ではなく GET /_mock/usage の throttled で数えます。")

    print()
    print("=== 3. 自分で書く層（記録を残す） ===")
    # 内側（SDK）が1回あたり2リクエスト出すため、外側を3回回すには4回分の
    # スロットリングが必要になる。**リトライは重ねると掛け算になる**
    model_router.set_behavior(throttle_next=4)
    before = model_router.mock_usage()["throttled"]
    manual = call_with_backoff(
        clients.bedrock_runtime(max_attempts=1),
        question,
        source,
        rng=random.Random(7),
    )
    throttled = model_router.mock_usage()["throttled"] - before
    print(f"結果={manual['outcome']} / 自作の試行{manual['attempts']}回 / "
          f"待った回数{len(manual['waited'])}")
    print(f"実際に 429 を受けたのは {throttled}回"
          "（自作の1回あたり SDK が2リクエスト出しています）")
    print("待ち時間は毎回ばらつきます（full jitter なので同じ値になりません）。")

    print()
    print("=== 4. リトライで直らないものは即座に返す ===")
    model_router.set_behavior(force_validation_error=True)
    try:
        call_with_backoff(
            clients.bedrock_runtime(max_attempts=1), question, source
        )
        print("NG: 例外が出ませんでした")
    except ClientError as error:
        code = error.response["Error"]["Code"]
        print(f"{code} は FATAL_CODES に含まれるため、待たずにそのまま返しました")

    model_router.reset_mock()
    print()
    print("モックの状態を初期化しました（注入した設定は残していません）")


if __name__ == "__main__":
    main()
