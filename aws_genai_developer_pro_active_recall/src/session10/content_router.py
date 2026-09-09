#!/usr/bin/env python3
"""セッション10: 内容に応じたモデルルーティング。

    docker compose exec app python src/session10/content_router.py

**呼ぶ前に、入力の内容だけで宛先を決める**層です。1件のリクエストにつき
モデルの呼び出しは1回で完結します。

セッション9のカスケード（安い層で呼んでみて、駄目なら上位へ昇格）や
セッション2のフェイルオーバー（落ちていたら代替へ）とは別物です。

    ルーティング  … 内容で宛先を決める（呼び出しは1回）
    カスケード    … 出力の質で昇格する（呼び出しが2回になることがある）
    フェイルオーバー … 障害で代替へ切り替える（S02 の ModelRouter が担当）

「どのモデルへ」を決めるのがこの層、「どう呼ぶか（再試行・縮退）」は
セッション2の `ModelRouter` に任せます。作り直しません。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session01")
sys.path.insert(0, "/workspace/src/session02")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bedrock_mock import catalog, generation  # noqa: E402

import model_router  # noqa: E402
import poc_probe  # noqa: E402
import streaming  # noqa: E402

MICRO = "amazon.nova-micro-v1:0"
LITE = "amazon.nova-lite-v1:0"
PRO = "amazon.nova-pro-v1:0"
HAIKU = "anthropic.claude-3-5-haiku-20241022-v1:0"
SONNET = "anthropic.claude-sonnet-4-5-20250929-v1:0"

# 入力がこれを超えたら、コンテキスト長に余裕のあるモデルへ回す
LONG_INPUT_TOKENS = 600

# ルート表。**アプリのコードではなくデータ**として持つのが要点で、
# 実務では AppConfig / SSM に置いて配布します（セッション2と同じ理由）
ROUTE_MODELS: dict[str, str] = {
    "needs_image": LITE,   # 画像を含む → マルチモーダル対応が必須
    "long_input": PRO,     # 入力が長い → コンテキスト長に余裕がある側
    "classify": MICRO,     # 短く定型 → 最小モデルで十分
    "summarize": HAIKU,    # 要約は指示追従の質が効く
    "plan": PRO,           # 多段の推論が要る
    "default": LITE,       # 資料つきの通常応答
}

# 宛先ごとの代替先。**別プロバイダから選ぶ**（同じ基盤で同時に落ちるのを避ける）
FALLBACK_OF: dict[str, list[str]] = {
    MICRO: [HAIKU],
    LITE: [HAIKU],
    HAIKU: [PRO],
    PRO: [SONNET],
}

# 判定の順序。上から評価して最初に当たったものを採用する
ROUTE_ORDER = ("needs_image", "long_input", "classify", "summarize", "plan")

# `task` の値がそのまま宛先になるもの。これ以外の task は default 扱い
TASK_ROUTES = ("classify", "summarize", "plan")


def validate_routes(
    models: dict[str, str] | None = None,
    fallbacks: dict[str, list[str]] | None = None,
) -> None:
    """ルート表を配る前に検査する。壊れた表を配ると全リクエストが落ちる。

    人間の目視では「カタログから消えたモデル ID」を見つけられません。
    カタログ（`ListFoundationModels` 相当）と突き合わせて機械で弾きます。
    """
    models = models or ROUTE_MODELS
    fallbacks = fallbacks or FALLBACK_OF

    if set(models) != set(ROUTE_ORDER) | {"default"}:
        raise ValueError(f"ルートの集合が想定と違います: {sorted(models)}")

    for reason, model_id in models.items():
        try:
            spec, _ = catalog.resolve(model_id)
        except KeyError:
            raise ValueError(f"カタログに無いモデル ID です: {model_id}") from None
        if not spec.supports_converse:
            raise ValueError(f"Converse API に対応していません: {model_id}")
        if reason == "needs_image" and "IMAGE" not in spec.modality:
            raise ValueError(f"画像を扱えないモデルです: {model_id}")

        alternatives = fallbacks.get(model_id) or []
        if not alternatives:
            raise ValueError(f"代替先が定義されていません: {model_id}")
        for alt in alternatives:
            try:
                alt_spec, _ = catalog.resolve(alt)
            except KeyError:
                raise ValueError(f"カタログに無い代替先です: {alt}") from None
            if not alt_spec.supports_converse:
                raise ValueError(f"代替先が Converse に非対応です: {alt}")
            if alt_spec.provider == spec.provider:
                raise ValueError(
                    f"代替先が同じプロバイダです: {model_id} -> {alt}"
                )
            if reason == "needs_image" and "IMAGE" not in alt_spec.modality:
                raise ValueError(f"代替先が画像を扱えません: {alt}")


def estimate_input_tokens(request: dict) -> int:
    """呼ぶ前にトークン数を見積もる（モックの数え方と同じ規則）。"""
    text = streaming.prompt_text(request["question"], request.get("context"))
    return generation.count_tokens(poc_probe.SYSTEM_PROMPT + text)


def route(request: dict) -> dict:
    """内容から宛先を決める。判定は上から順に、最初に当たったものを採る。"""
    tokens = estimate_input_tokens(request)
    task = request.get("task", "answer")

    if request.get("hasImage"):
        reason = "needs_image"
    elif tokens > LONG_INPUT_TOKENS:
        reason = "long_input"
    elif task in TASK_ROUTES:
        reason = task
    else:
        reason = "default"

    model_id = ROUTE_MODELS[reason]
    return {
        "requestId": request.get("requestId", "-"),
        "task": task,
        "reason": reason,
        "modelId": model_id,
        "fallbacks": list(FALLBACK_OF[model_id]),
        "estimatedInputTokens": tokens,
    }


def config_for(decision: dict) -> dict:
    """決めた宛先を、セッション2のモデル解決層が読む設定の形にする。"""
    return {
        **model_router.DEFAULT_CONFIG,
        "primary": decision["modelId"],
        "fallbacks": decision["fallbacks"],
    }


def serve(request: dict, router: model_router.ModelRouter) -> dict:
    """振り分けてから呼ぶ。呼び方（再試行・縮退）は ModelRouter に任せる。"""
    decision = route(request)
    result = router.invoke(
        request["question"],
        context=request.get("context"),
        config=config_for(decision),
    )
    return {**decision, "servedBy": result["modelId"], "result": result}


def serve_all(
    requests: list[dict], router: model_router.ModelRouter
) -> list[dict]:
    return [serve(r, router) for r in requests]


def distribution(served: list[dict]) -> dict[str, int]:
    """宛先ごとの件数。**この分布を見て閾値を直す**のがメトリクス駆動の入口。

    CloudWatch へ出して自動で調整するところまではセッション17で扱います。
    """
    counts: dict[str, int] = {}
    for item in served:
        counts[item["modelId"]] = counts.get(item["modelId"], 0) + 1
    return counts


# ---------------------------------------------------------------------------
# 演習用のワークロード（決定的）
# ---------------------------------------------------------------------------

# 就業規則を丸ごと貼ったような長い入力を再現する
LONG_CONTEXT = "年次有給休暇の未消化分は翌年度に限り繰り越せますが、繰越上限は20日です。" * 20

WORKLOAD: list[dict] = [
    {
        "requestId": "api-001",
        "task": "classify",
        "question": "次の問い合わせを IT／経費／人事／セキュリティに分類してください。「VPN に接続できません」",
    },
    {
        "requestId": "api-002",
        "task": "answer",
        "question": poc_probe.QUESTIONS[0][0],
        "context": poc_probe.QUESTIONS[0][1],
    },
    {
        "requestId": "api-003",
        "task": "summarize",
        "question": "次の問い合わせ履歴を要約してください。VPN が切れる、経費の締め日を知りたい、在宅勤務の日数を確認したい。",
    },
    {
        "requestId": "api-004",
        "task": "plan",
        "question": "社内文書の棚卸し計画を立ててください。対象は人事・経費・IT の規程です。",
    },
    {
        "requestId": "api-005",
        "task": "answer",
        "question": "添付したエラー画面から原因を教えてください。",
        "hasImage": True,
    },
    {
        "requestId": "api-006",
        "task": "answer",
        "question": "就業規則の該当箇所を踏まえて繰越上限を答えてください。",
        "context": LONG_CONTEXT,
    },
    {
        "requestId": "api-007",
        "task": "classify",
        "question": "次の依頼のカテゴリを1語で答えてください。「宿泊費の上限を知りたい」",
    },
    {
        "requestId": "api-008",
        "task": "answer",
        "question": poc_probe.QUESTIONS[1][0],
        "context": poc_probe.QUESTIONS[1][1],
    },
]

# 期待される振り分け（requestId, reason, modelId）
EXPECTED_ROUTES = [
    ("api-001", "classify", MICRO),
    ("api-002", "default", LITE),
    ("api-003", "summarize", HAIKU),
    ("api-004", "plan", PRO),
    ("api-005", "needs_image", LITE),
    ("api-006", "long_input", PRO),
    ("api-007", "classify", MICRO),
    ("api-008", "default", LITE),
]


def main() -> None:
    model_router.reset_mock()
    validate_routes()
    router = model_router.ModelRouter(config=model_router.bootstrap())

    print("=== 1. ルート表の検査（配る前に必ず通す） ===")
    for reason in (*ROUTE_ORDER, "default"):
        model_id = ROUTE_MODELS[reason]
        print(f"  {reason:<12} -> {model_id}（代替 {FALLBACK_OF[model_id][0]}）")

    print()
    print("=== 2. 内容で振り分ける（呼ぶ前に決まる） ===")
    print("id       task       入力tok  理由           宛先")
    served = serve_all(WORKLOAD, router)
    for item in served:
        print(f"{item['requestId']}  {item['task']:<9}"
              f"{item['estimatedInputTokens']:>7}  {item['reason']:<13}"
              f"  {item['modelId']}")

    print()
    print("=== 3. 分布（閾値を直すための材料） ===")
    usage = model_router.mock_usage()
    for model_id, count in sorted(distribution(served).items()):
        print(f"  {model_id:<44} {count}件")
    print(f"呼び出し総数 {usage['calls']}回 / 依頼{len(WORKLOAD)}件"
          f"（1件1回で完結。カスケードとの違いはここに出ます）")
    print(f"推定コスト {usage['estimatedUsdTotal']:.6f} USD")

    print()
    print("=== 4. 壊れたルート表は配らせない ===")
    broken = {**ROUTE_MODELS, "needs_image": MICRO}
    try:
        validate_routes(broken)
        print("NG: 例外が出ませんでした")
    except ValueError as error:
        print(f"  弾きました: {error}")

    model_router.reset_mock()


if __name__ == "__main__":
    main()
