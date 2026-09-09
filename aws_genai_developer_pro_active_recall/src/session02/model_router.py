#!/usr/bin/env python3
"""セッション2: モデル解決層（設定 → 選択 → 呼び出し → 切り替え → 縮退）。

アプリのコードにモデル ID を書かず、**アプリの外から差し替えられる1枚の層**を作ります。

    docker compose exec app python src/session02/model_router.py

実務では設定の配布に AWS AppConfig を使います（版管理・段階デプロイ・検証フック・
即時ロールバックが付いてくるため）。LocalStack Community は AppConfig に未対応なので、
本書では **SSM パラメータストア**で同じ役割（アプリの外から設定を差し替える）を再現します。
API の形は違っても、設計上の役割分担は同じです。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from typing import Callable

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session01")

from botocore.exceptions import ClientError  # noqa: E402

from awskit import clients  # noqa: E402
from bedrock_mock import catalog  # noqa: E402

# 前章の PoC プローブを再利用する。system プロンプトと質問をそのまま使うので、
# 計測値（入力90 / 出力66 トークン / 86 ms）が前章と一致し、
# 「構成を変えても回答の質は変わっていない」ことを数字で言える
import poc_probe  # noqa: E402

# 設定の置き場。実務では AppConfig の「アプリケーション / 環境 / 設定プロファイル」
PARAM_NAME = "/sample-shoji/helpdesk/model-config"

# 設定を読み直す間隔。AppConfig エージェントのポーリング間隔に相当する。
# 短すぎると呼び出しごとに設定取得が増え、長すぎると切り替えが効くまで待たされる
CONFIG_TTL_SECONDS = 30.0

# クロスリージョン推論（推論プロファイル）の地理接頭辞
GEO_PREFIXES = ("", "us.", "eu.", "apac.", "jp.")

DEFAULT_CONFIG: dict = {
    "primary": "amazon.nova-lite-v1:0",
    "fallbacks": ["anthropic.claude-3-5-haiku-20241022-v1:0"],
    "geoPrefix": "",
    "maxTokens": 300,
    "temperature": 0.0,
    "breaker": {"failureThreshold": 2, "cooldownSeconds": 30},
    "degradedMessage": (
        "現在AIによる回答を生成できません。"
        "お手数ですが社内ヘルプデスク（内線1234）へご連絡ください。"
    ),
}

# 別のモデルへ切り替えても直らないエラー。設定・権限・リクエストの誤りなので、
# 握りつぶさずそのまま呼び出し元へ返す（黙って代替へ流すと設定ミスに永遠に気づけない）
FATAL_CODES = frozenset(
    {"ValidationException", "AccessDeniedException", "ResourceNotFoundException"}
)

# 直前に設定の読み込みで起きた問題（監視に出す用）
LAST_CONFIG_ERROR: str | None = None

_CACHE: dict = {"config": None, "fetchedAt": float("-inf")}
_SSM = None


# ---------------------------------------------------------------------------
# 設定レイヤ（AppConfig の代替として SSM パラメータストアを使う）
# ---------------------------------------------------------------------------


def ssm():
    """SSM クライアント（LocalStack 経由）。生成は1回だけにする。"""
    global _SSM
    if _SSM is None:
        _SSM = clients.aws("ssm")
    return _SSM


def validate_config(config: dict) -> dict:
    """設定の中身を検査する。AppConfig の「バリデータ」に相当する。

    モデル差し替えの仕組みを入れたときの最大のリスクは、
    **壊れた設定を配ってしまうこと**です。配布時と読み込み時の2か所で検査します。
    """
    if not isinstance(config, dict):
        raise ValueError("設定は JSON オブジェクトである必要があります")

    chain = [config.get("primary"), *(config.get("fallbacks") or [])]
    for model_id in chain:
        if not isinstance(model_id, str) or not model_id:
            raise ValueError(f"モデル ID が文字列ではありません: {model_id!r}")
        try:
            spec, _ = catalog.resolve(model_id)
        except KeyError:
            raise ValueError(f"カタログに無いモデル ID です: {model_id}") from None
        if not spec.supports_converse:
            raise ValueError(f"Converse API に対応していないモデルです: {model_id}")

    if config.get("geoPrefix", "") not in GEO_PREFIXES:
        raise ValueError(f"未知の地理接頭辞です: {config.get('geoPrefix')!r}")
    if not config.get("degradedMessage"):
        raise ValueError("縮退時の応答文（degradedMessage）が空です")
    return config


def put_config(config: dict, *, validate: bool = True) -> None:
    """設定を配布する（AppConfig のデプロイに相当）。

    `validate=False` は「コンソールから手で書き換えられた」状況の再現用です。
    実運用では配布経路を1つに絞り、検証を通らない設定は配布させません。
    """
    if validate:
        validate_config(config)
    ssm().put_parameter(
        Name=PARAM_NAME,
        Value=json.dumps(config, ensure_ascii=False),
        Type="String",
        Overwrite=True,
    )


def load_config(*, force: bool = False, now: float | None = None) -> dict:
    """設定を読む。TTL 内はキャッシュを返し、読めなければ直前の正しい設定を使う。

    ここが「落ちない」ための要です。設定の取得や検査に失敗したときに例外を投げると、
    **設定ストアの障害がアプリ全体の障害になります。**
    直前に検証を通った設定（last known good）を使い続け、問題は監視へ出します。
    """
    global LAST_CONFIG_ERROR
    stamp = time.monotonic() if now is None else now
    cached = _CACHE["config"]
    if (
        cached is not None
        and not force
        and (stamp - _CACHE["fetchedAt"]) < CONFIG_TTL_SECONDS
    ):
        return cached

    try:
        raw = ssm().get_parameter(Name=PARAM_NAME)["Parameter"]["Value"]
        config = validate_config(json.loads(raw))
    except (ClientError, ValueError, json.JSONDecodeError) as exc:
        LAST_CONFIG_ERROR = f"{type(exc).__name__}: {exc}"
        # fetchedAt は更新しない。次の呼び出しでまた読みに行く（復旧を待たない）
        return cached if cached is not None else dict(DEFAULT_CONFIG)

    LAST_CONFIG_ERROR = None
    _CACHE["config"] = config
    _CACHE["fetchedAt"] = stamp
    return config


def bootstrap() -> dict:
    """演習を何度実行しても同じ状態から始まるよう、既定の設定を配布して読み直す。"""
    put_config(DEFAULT_CONFIG)
    return load_config(force=True)


# ---------------------------------------------------------------------------
# サーキットブレーカー
# ---------------------------------------------------------------------------


class CircuitBreaker:
    """1つの呼び出し先（モデル ID）ぶんのサーキットブレーカー。

    CLOSED（通す）→ 連続失敗が閾値に達すると OPEN（呼ばずに即あきらめる）
    → クールダウン経過で HALF_OPEN（1回だけ試す）→ 成功で CLOSED / 失敗で OPEN。

    ブレーカーの目的はリトライではなく**呼ばないこと**です。効果は2つあります。
      1. 落ちている相手を待つ時間を、利用者に払わせない（自分の保護）
      2. 復旧しかけた相手に全トラフィックをぶつけない（相手の保護）

    比喩で言えば、停電したブレーカーを上げ続けないのと同じです。
    まず切り離し、時間をおいて1回だけ試します。
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 2,
        cooldown_seconds: float = 30.0,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.state = "CLOSED"
        self.failures = 0
        self._opened_at = 0.0
        self._time_fn = time_fn

    def allow(self) -> bool:
        """いま呼んでよいか。OPEN の間はクールダウンが明けるまで False。"""
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if self._time_fn() - self._opened_at >= self.cooldown_seconds:
                self.state = "HALF_OPEN"
                return True
            return False
        return True  # HALF_OPEN: 試行を通す

    def on_success(self) -> None:
        self.state = "CLOSED"
        self.failures = 0

    def on_failure(self) -> None:
        self.failures += 1
        # 半開で失敗したら即座に開き直す（まだ復旧していない）
        if self.state == "HALF_OPEN" or self.failures >= self.failure_threshold:
            self.state = "OPEN"
            self._opened_at = self._time_fn()


# ---------------------------------------------------------------------------
# モデル解決層
# ---------------------------------------------------------------------------


class ModelRouter:
    """設定に書かれた順にモデルを試し、全滅したら縮退応答を返す層。"""

    def __init__(
        self,
        runtime=None,
        *,
        config: dict | None = None,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        # フェイルオーバーは「リトライを使い切ったあと」の話なので、演習では
        # 再試行を止めて切り替えだけを観察する（リトライ方針はセッション10で扱う）
        self._runtime = (
            runtime if runtime is not None else clients.bedrock_runtime(max_attempts=1)
        )
        self._config = config
        self._time_fn = time_fn
        self._breakers: dict[str, CircuitBreaker] = {}
        self.last_attempts: list[dict] = []

    def breaker(self, model_id: str, settings: dict | None = None) -> CircuitBreaker:
        """モデル ID ごとのブレーカー。**呼び出しに使った ID 単位**で持つ。

        `us.` 付きの推論プロファイル ID と接頭辞なしの ID は別の呼び出し経路なので、
        障害の範囲（failure domain）も分けて数えます。
        """
        if model_id not in self._breakers:
            values = settings or DEFAULT_CONFIG["breaker"]
            self._breakers[model_id] = CircuitBreaker(
                failure_threshold=int(values.get("failureThreshold", 2)),
                cooldown_seconds=float(values.get("cooldownSeconds", 30)),
                time_fn=self._time_fn,
            )
        return self._breakers[model_id]

    def invoke(
        self, question: str, *, context: str | None = None, config: dict | None = None
    ) -> dict:
        """設定の順にモデルを試す。1つも成功しなければ縮退応答を返す。"""
        cfg = config or self._config or load_config()
        prefix = cfg.get("geoPrefix", "")
        attempts: list[dict] = []
        self.last_attempts = attempts  # 例外で抜けたときも外から追跡できるようにする

        for base_id in [cfg["primary"], *(cfg.get("fallbacks") or [])]:
            model_id = f"{prefix}{base_id}"
            breaker = self.breaker(model_id, cfg.get("breaker"))
            if not breaker.allow():
                attempts.append({"modelId": model_id, "outcome": "skipped_open"})
                continue
            try:
                result = self._converse(model_id, base_id, question, context, cfg)
            except ClientError as exc:
                code = exc.response["Error"]["Code"]
                attempts.append({"modelId": model_id, "outcome": code})
                if code in FATAL_CODES:
                    # 切り替えても直らない。代替に流すと設定ミスが隠れる
                    raise
                breaker.on_failure()
                continue
            breaker.on_success()
            result["serviceLevel"] = "full" if not attempts else "fallback"
            attempts.append({"modelId": model_id, "outcome": "ok"})
            result["attempts"] = attempts
            result["degraded"] = False
            return result

        return {
            "serviceLevel": "degraded",
            "degraded": True,
            "modelId": None,
            "baseModelId": None,
            "geo": None,
            "text": cfg["degradedMessage"],
            "grounded": False,
            "inputTokens": 0,
            "outputTokens": 0,
            "latencyMs": 0,
            "estimatedUsd": 0.0,
            "stopReason": "degraded",
            "attempts": attempts,
        }

    def _converse(
        self,
        model_id: str,
        base_id: str,
        question: str,
        context: str | None,
        cfg: dict,
    ) -> dict:
        """Converse API を1回呼ぶ。呼び方は前章とまったく同じにする。"""
        text = question if context is None else f"{question}\n<context>{context}</context>"
        response = self._runtime.converse(
            modelId=model_id,
            system=[{"text": poc_probe.SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": text}]}],
            inferenceConfig={
                "maxTokens": int(cfg.get("maxTokens", 300)),
                "temperature": float(cfg.get("temperature", 0.0)),
            },
        )
        answer = response["output"]["message"]["content"][0]["text"]
        usage = response["usage"]
        headers = response["ResponseMetadata"]["HTTPHeaders"]
        return {
            "modelId": model_id,
            "baseModelId": base_id,
            # モックが「どの地理に解決したか」を返すヘッダ。実 Bedrock には無い
            "geo": headers.get("x-mock-geo-prefix", "-"),
            "text": answer,
            "grounded": poc_probe.GROUNDING_MARKER in answer,
            "inputTokens": usage["inputTokens"],
            "outputTokens": usage["outputTokens"],
            "latencyMs": response["metrics"]["latencyMs"],
            # 単価はモデルごとに違う。切り替え先のコストを黙って払わないために毎回出す
            "estimatedUsd": catalog.cost_usd(
                base_id, usage["inputTokens"], usage["outputTokens"]
            ),
            "stopReason": response["stopReason"],
        }


# ---------------------------------------------------------------------------
# モック専用の制御 API（実 AWS には存在しない。障害を確実に起こすために使う）
# ---------------------------------------------------------------------------


def mock_control(path: str, payload: dict | None = None) -> dict:
    request = urllib.request.Request(
        f"{clients.mock_base_url()}{path}",
        data=json.dumps(payload or {}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def set_behavior(**patch) -> dict:
    """障害注入。乱数ではなく指定したタイミングで確実に失敗させる。"""
    return mock_control("/_mock/behavior", patch)


def reset_mock() -> dict:
    return mock_control("/_mock/reset", {})


def mock_usage() -> dict:
    with urllib.request.urlopen(
        f"{clients.mock_base_url()}/_mock/usage", timeout=10
    ) as response:
        return json.loads(response.read())


# ---------------------------------------------------------------------------
# 演習の本体
# ---------------------------------------------------------------------------


def line(result: dict) -> str:
    return (
        f"serviceLevel={result['serviceLevel']} / modelId={result['modelId']}"
        f" / geo={result['geo']} / 根拠提示={'○' if result['grounded'] else '×'}"
        f" / 入力{result['inputTokens']}tok 出力{result['outputTokens']}tok"
        f" {result['latencyMs']}ms / {result['estimatedUsd']:.6f} USD"
    )


def attempts_line(result: dict) -> str:
    return "attempts: " + " -> ".join(
        f"{a['modelId']}: {a['outcome']}" for a in result["attempts"]
    )


def main() -> None:
    reset_mock()
    config = bootstrap()
    question, source = poc_probe.QUESTIONS[0]
    router = ModelRouter(config=config)

    print("=== 1. 設定を読む（AppConfig 相当・SSM パラメータストア） ===")
    print(f"パラメータ名: {PARAM_NAME}")
    print(f"primary   : {config['primary']}")
    print(f"fallbacks : {', '.join(config['fallbacks'])}")
    print(f"geoPrefix : {config['geoPrefix'] or '(なし)'}")

    print()
    print("=== 2. 通常時 ===")
    normal = router.invoke(question, context=source)
    print(attempts_line(normal))
    print(line(normal))

    print()
    print("=== 3. primary のリージョン障害を注入する ===")
    set_behavior(unavailable_model=config["primary"])
    first = router.invoke(question, context=source)
    print(f"[1回目] {attempts_line(first)}")
    print(f"        {line(first)}")
    second = router.invoke(question, context=source)
    print(f"[2回目] {attempts_line(second)}")
    breaker = router.breaker(config["primary"])
    print(
        f"ブレーカー: {config['primary']} = {breaker.state}"
        f"（連続失敗{breaker.failures} / 閾値{breaker.failure_threshold}）"
    )
    third = router.invoke(question, context=source)
    print(f"[3回目] {attempts_line(third)}")
    print("        落ちているモデルへの HTTP リクエストは1回も出していません")

    print()
    print("=== 4. 推論プロファイル（クロスリージョン推論）経由で呼ぶ ===")
    via_profile = router.invoke(
        question, context=source, config={**DEFAULT_CONFIG, "geoPrefix": "us."}
    )
    print(line(via_profile))
    print(f"接頭辞なしの呼び出しと出力テキストが一致: {via_profile['text'] == normal['text']}")
    print("単一リージョン ID への障害注入をすり抜けました（別の呼び出し経路として扱われます）")

    print()
    print("=== 5. コードを変えずに primary を差し替える ===")
    swapped = {**DEFAULT_CONFIG, "primary": DEFAULT_CONFIG["fallbacks"][0]}
    put_config(swapped)
    print(f"put_parameter で primary を {swapped['primary']} に変更しました")
    print(f"再読込後の primary: {load_config(force=True)['primary']}")

    print()
    print("=== 6. 代替先が無いときの段階的縮退 ===")
    degraded = router.invoke(
        question, context=source, config={**DEFAULT_CONFIG, "fallbacks": []}
    )
    print(attempts_line(degraded))
    print(f"serviceLevel={degraded['serviceLevel']} / 応答={degraded['text']}")
    print("例外は投げていません。ブレーカーが開いている間は待ち時間ゼロで縮退応答を返します")

    put_config(DEFAULT_CONFIG)
    reset_mock()
    print()
    print("設定を既定値に戻しました（モックの障害注入も解除しました）")


if __name__ == "__main__":
    main()
