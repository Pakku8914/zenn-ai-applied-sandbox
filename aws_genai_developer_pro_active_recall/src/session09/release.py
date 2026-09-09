#!/usr/bin/env python3
"""セッション9: 決定的なカナリアリリースと、1操作で終わるロールバック。

    docker compose exec app python src/session09/release.py

新しいモデル（または新しいカスタムモデルの版）へ、一部のトラフィックだけを流します。
**乱数を使いません。** リクエストの識別子のハッシュで振り分けるので、

  * 同じリクエストは何度評価しても同じ経路になる（再現できる）
  * 割合を 10% → 25% に上げても、10% のときに新版だった相手は新版のまま（並び替えが起きない）
  * 割合を 0 に戻すだけでロールバックが完了する（再デプロイが要らない）

という3つの性質が手に入ります。品質が良いか悪いかの判定方法は本章の範囲外です
（評価と品質ゲートはセッション18で扱います）。ここで作るのは
「流す割合の制御」と「切り戻し」だけです。
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session01")
sys.path.insert(0, "/workspace/src/session02")

from botocore.exceptions import ClientError  # noqa: E402

from awskit import clients  # noqa: E402
from bedrock_mock import catalog  # noqa: E402

import model_router  # noqa: E402
import poc_probe  # noqa: E402

# リリース設定の置き場。実務では AWS AppConfig の設定プロファイルに置く
RELEASE_PARAM = "/sample-shoji/helpdesk/release-config"

# バケット数。100 にすると canaryPercent がそのまま「何%」になる
BUCKETS = 100

# 段階的移行の段。1段ごとに監視を挟んで次へ進む
STAGES = (10, 25, 50, 100)

DEFAULT_RELEASE: dict = {
    "stable": "amazon.nova-lite-v1:0",
    "canary": "anthropic.claude-3-5-haiku-20241022-v1:0",
    "canaryPercent": 0,
    # salt を変えると割り当てが総入れ替えになる。
    # リリースごとに固定し、移行が終わるまで変えない
    "salt": "helpdesk-2026-09",
    "previousPercent": 0,
}

_SSM = None


def ssm():
    global _SSM
    if _SSM is None:
        _SSM = clients.aws("ssm")
    return _SSM


# ---------------------------------------------------------------------------
# 決定的な振り分け
# ---------------------------------------------------------------------------


def bucket_of(request_id: str, salt: str) -> int:
    """リクエスト識別子を 0〜99 のバケットへ決定的に写す。

    乱数（`random.random() < 0.1`）との違いは決定性です。乱数だと
    同じ利用者が呼ぶたびに新版と旧版を行き来し、「新版で壊れた」という報告を
    再現できません。ハッシュなら**同じ識別子は必ず同じ側**に落ちます。
    """
    digest = hashlib.sha256(f"{salt}:{request_id}".encode("utf-8")).digest()
    return struct.unpack(">I", digest[:4])[0] % BUCKETS


def choose_arm(request_id: str, release: dict) -> str:
    """このリクエストを "stable" と "canary" のどちらへ流すか。"""
    percent = int(release.get("canaryPercent", 0))
    if percent <= 0:
        return "stable"
    if percent >= BUCKETS:
        return "canary"
    return "canary" if bucket_of(request_id, release["salt"]) < percent else "stable"


def model_for(request_id: str, release: dict) -> tuple[str, str]:
    """(どちらの側か, 使うモデル ID) を返す。"""
    arm = choose_arm(request_id, release)
    return arm, release[arm]


def distribution(request_ids: list[str], release: dict) -> dict[str, int]:
    counts = {"stable": 0, "canary": 0}
    for request_id in request_ids:
        counts[choose_arm(request_id, release)] += 1
    return counts


def canary_ids(request_ids: list[str], release: dict) -> list[str]:
    return [r for r in request_ids if choose_arm(r, release) == "canary"]


def synthetic_ids(count: int, prefix: str = "hd") -> list[str]:
    """分布を確かめるための合成識別子。"""
    return [f"{prefix}-{i:05d}" for i in range(count)]


# ---------------------------------------------------------------------------
# リリース設定の保管・検証・段階の進行・ロールバック
# ---------------------------------------------------------------------------


def validate_release(release: dict) -> dict:
    """壊れたリリース設定を配らないための検査。

    カナリアの事故で最も多いのは「新版のモデル ID を打ち間違えた」です。
    配布時に弾けば、切り替えた瞬間に全リクエストが失敗する事態を防げます。
    """
    for key in ("stable", "canary"):
        model_id = release.get(key)
        if not isinstance(model_id, str) or not model_id:
            raise ValueError(f"{key} のモデル ID が文字列ではありません: {model_id!r}")
        try:
            spec, _ = catalog.resolve(model_id)
        except KeyError:
            raise ValueError(f"カタログに無いモデル ID です: {model_id}") from None
        if not spec.supports_converse:
            raise ValueError(f"Converse API に対応していないモデルです: {model_id}")
    if release["stable"] == release["canary"]:
        raise ValueError("stable と canary が同じモデルです（比較になりません）")
    percent = release.get("canaryPercent")
    if not isinstance(percent, int) or isinstance(percent, bool):
        raise ValueError(f"canaryPercent が整数ではありません: {percent!r}")
    if not 0 <= percent <= 100:
        raise ValueError(f"canaryPercent が 0〜100 の範囲外です: {percent}")
    if not release.get("salt"):
        raise ValueError("salt が空です（割り当てが再現できません）")
    return release


def put_release(release: dict, *, validate: bool = True) -> None:
    if validate:
        validate_release(release)
    ssm().put_parameter(
        Name=RELEASE_PARAM,
        Value=json.dumps(release, ensure_ascii=False),
        Type="String",
        Overwrite=True,
    )


def load_release() -> dict:
    """リリース設定を読む。無ければ既定値（カナリア 0%）を配って返す。"""
    try:
        raw = ssm().get_parameter(Name=RELEASE_PARAM)["Parameter"]["Value"]
        return validate_release(json.loads(raw))
    except (ClientError, ValueError, json.JSONDecodeError):
        put_release(DEFAULT_RELEASE)
        return dict(DEFAULT_RELEASE)


def bootstrap() -> dict:
    """演習を何度実行しても同じ状態から始まるように既定値へ戻す。"""
    put_release(DEFAULT_RELEASE)
    return load_release()


def set_canary_percent(percent: int) -> dict:
    """段階を1つ進める（または戻す）。**書き込みは1回**で完了する。"""
    current = load_release()
    updated = {
        **current,
        "canaryPercent": percent,
        "previousPercent": int(current.get("canaryPercent", 0)),
    }
    put_release(updated)
    return updated


def rollback() -> dict:
    """カナリアを止める。1操作（割合を 0 にする書き込み1回）で完了する。

    旧版を止めてから新版を入れるデプロイと違い、
    **旧版はずっと動いたまま**なので、戻すのに再デプロイもモデルの再ロードも要りません。
    """
    current = load_release()
    rolled_from = int(current.get("canaryPercent", 0))
    updated = {**current, "canaryPercent": 0, "previousPercent": rolled_from}
    put_release(updated)
    return {"canaryPercent": 0, "rolledBackFrom": rolled_from}


# ---------------------------------------------------------------------------
# 実際に呼ぶ（モデル解決層はセッション2のものを再利用する）
# ---------------------------------------------------------------------------


def serve(
    request_id: str,
    question: str,
    context: str | None,
    release: dict,
    router,
) -> dict:
    """振り分けてから呼ぶ。どちら側で答えたかを必ず記録する。"""
    arm, model_id = model_for(request_id, release)
    config = {
        **model_router.DEFAULT_CONFIG,
        "primary": model_id,
        # カナリア側が落ちたら安定版が答える（カナリアの事故を利用者に見せない）
        "fallbacks": [release["stable"]] if arm == "canary" else [],
    }
    result = router.invoke(question, context=context, config=config)
    # arm は後で「どちらの版の応答だったか」を突き合わせるための鍵になる。
    # 記録しないと、カナリア中に集めた指標が使えなくなる
    return {"requestId": request_id, "arm": arm, "assignedModelId": model_id, **result}


# ---------------------------------------------------------------------------
# 演習の本体
# ---------------------------------------------------------------------------


def ok(condition: bool) -> str:
    return "OK" if condition else "NG"


def main() -> None:
    model_router.reset_mock()
    release = bootstrap()
    router = model_router.ModelRouter()
    question, source = poc_probe.QUESTIONS[0]
    ids = synthetic_ids(1_000)

    print("=== 1. リリース設定 ===")
    print(f"パラメータ名 : {RELEASE_PARAM}")
    print(f"stable       : {release['stable']}")
    print(f"canary       : {release['canary']}")
    print(f"canaryPercent: {release['canaryPercent']}（既定は 0＝全件が安定版）")
    print(f"salt         : {release['salt']}")

    print()
    print("=== 2. 決定的な振り分け ===")
    at_10 = {**release, "canaryPercent": 10}
    at_25 = {**release, "canaryPercent": 25}
    ten = set(canary_ids(ids, at_10))
    twenty_five = set(canary_ids(ids, at_25))
    repeated = {choose_arm(ids[0], at_10) for _ in range(100)}
    zero = distribution(ids, {**release, "canaryPercent": 0})
    full = distribution(ids, {**release, "canaryPercent": 100})
    other_salt = set(canary_ids(ids, {**at_10, "salt": "helpdesk-other"}))
    print(f"同じ識別子を100回評価した結果の種類: {len(repeated)}（決定的なので必ず1）")
    print(f"判定 10% のカナリア集合が 25% に含まれる : {ok(ten <= twenty_five)}")
    print(f"判定 0% なら全件が安定版 : {ok(zero['canary'] == 0)}")
    print(f"判定 100% なら全件がカナリア : {ok(full['stable'] == 0)}")
    print(f"判定 salt を変えると割り当てが入れ替わる : {ok(other_salt != ten)}")
    print(f"[実測] 1,000件のうちカナリアへ流れた件数: {len(ten)}件"
          "（設定 10% / 許容 6〜14%）")

    print()
    print("=== 3. 段階的移行 ===")
    for percent in STAGES:
        staged = {**release, "canaryPercent": percent}
        counts = distribution(ids, staged)
        print(f"[実測] {percent:>3}% → カナリア {counts['canary']:>4}件 /"
              f" 安定版 {counts['stable']:>4}件")
    print("各段のあいだに監視を挟みます。ここでは割合の制御だけを扱います")

    print()
    print("=== 4. カナリア側で障害が起きたとき ===")
    live = set_canary_percent(25)
    hit = canary_ids(ids, live)[0]
    miss = next(r for r in ids if choose_arm(r, live) == "stable")
    model_router.set_behavior(unavailable_model=live["canary"])
    fresh = model_router.ModelRouter()
    served = serve(hit, question, source, live, fresh)
    print(f"[実測] カナリアに当たった識別子: {hit}")
    print(f"  arm={served['arm']} / 実際に答えたモデル={served['modelId']}"
          f" / serviceLevel={served['serviceLevel']}")
    print("  attempts: " + " -> ".join(
        f"{a['modelId']}: {a['outcome']}" for a in served["attempts"]))
    untouched = serve(miss, question, source, live, fresh)
    print(f"[実測] 安定版に当たった識別子: {miss}")
    print(f"  arm={untouched['arm']}"
          f" / serviceLevel={untouched['serviceLevel']}（影響を受けない）")
    model_router.set_behavior(unavailable_model=None)

    print()
    print("=== 5. ロールバック（1操作） ===")
    rolled = rollback()
    after = load_release()
    print(f"canaryPercent: {rolled['rolledBackFrom']} → {after['canaryPercent']}"
          f"（put_parameter 1回・再デプロイなし）")
    print(f"直後の1,000件の内訳: {distribution(ids, after)}")
    print(f"どこから戻したかが設定に残る: previousPercent={after['previousPercent']}")

    bootstrap()
    model_router.reset_mock()
    print()
    print("リリース設定を既定値（カナリア 0%）へ戻しました")


if __name__ == "__main__":
    main()
