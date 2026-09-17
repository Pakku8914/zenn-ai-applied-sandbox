"""セッション12 のテスト（Python 版）

実行： docker compose exec python python -m pytest src/session12 -q

pytest-asyncio の設定に依存しないよう、非同期のテストは asyncio.run() で閉じ込めています
（設定ファイルの差異でテストが動かなくなるのを避けるため）。
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

import pytest

# 同じディレクトリのモジュールを import できるようにする（章ごとにディレクトリを分けているため）
sys.path.insert(0, str(Path(__file__).resolve().parent))

from auth_middleware import BearerAuthMiddleware  # noqa: E402
from tokens import (  # noqa: E402
    CLOCK_SKEW_SECONDS,
    SCOPE_DOCS_ADMIN,
    SCOPE_DOCS_READ,
    AuthError,
    b64url_encode,
    issue_access_token,
    sign_token,
    verify_token,
)

SECRET = "test-shared-secret-0123456789abcdef"
OTHER_SECRET = "another-shared-secret-0123456789abc"
ISSUER = "http://127.0.0.1:9100"
RESOURCE = "http://127.0.0.1:8787/mcp"
OTHER_RESOURCE = "https://kintai.example.internal/api"


def make_token(**overrides: Any) -> str:
    params: dict[str, Any] = {
        "secret": SECRET,
        "issuer": ISSUER,
        "audience": RESOURCE,
        "scope": SCOPE_DOCS_READ,
        "ttl_seconds": 300,
    }
    params.update(overrides)
    return issue_access_token(**params)


def verify(token: str, **overrides: Any) -> Any:
    params: dict[str, Any] = {"secret": SECRET, "issuer": ISSUER, "audience": RESOURCE}
    params.update(overrides)
    return verify_token(token, **params)


# ---------------------------------------------------------------- 正常系
def test_valid_token_passes() -> None:
    context = verify(make_token(subject="user-1001", scope=f"{SCOPE_DOCS_READ} {SCOPE_DOCS_ADMIN}"))
    assert context.subject == "user-1001"
    assert context.scopes == (SCOPE_DOCS_READ, SCOPE_DOCS_ADMIN)
    # 指紋は 8 文字。トークン本体はどこにも残さない
    assert len(context.fingerprint) == 8


# ------------------------------------------------------------ 署名の改ざん
def test_tampered_signature_is_rejected() -> None:
    token = make_token()
    head, payload, signature = token.split(".")
    # ★ 末尾ではなく先頭の 1 文字を変える（末尾は捨てられるビットを含むため）
    first = "B" if signature[0] == "A" else "A"
    tampered = f"{head}.{payload}.{first}{signature[1:]}"
    with pytest.raises(AuthError) as error:
        verify(tampered)
    assert error.value.reason == "bad_signature"


def test_alg_none_is_rejected() -> None:
    payload = b64url_encode(b'{"iss":"http://127.0.0.1:9100","sub":"attacker","exp":9999999999}')
    header = b64url_encode(b'{"alg":"none","typ":"JWT"}')
    with pytest.raises(AuthError) as error:
        verify(f"{header}.{payload}.")
    assert error.value.reason == "unsupported_alg"


def test_token_signed_with_other_secret_is_rejected() -> None:
    token = make_token(secret=OTHER_SECRET)
    with pytest.raises(AuthError) as error:
        verify(token)
    assert error.value.reason == "bad_signature"


# ---------------------------------------------------------------- 時刻
def test_expired_token_is_rejected() -> None:
    token = make_token(ttl_seconds=-600)
    with pytest.raises(AuthError) as error:
        verify(token)
    assert error.value.reason == "expired"


def test_within_clock_skew_is_accepted() -> None:
    # exp を 30 秒前に置く。許容幅（60 秒）の中なので通るのが正しい
    token = make_token(ttl_seconds=-30)
    context = verify(token, now=int(time.time()))
    assert context.expires_at < int(time.time())
    assert CLOCK_SKEW_SECONDS >= 30


# ------------------------------------------------------- オーディエンス・発行者
def test_audience_mismatch_is_rejected() -> None:
    token = make_token(audience=OTHER_RESOURCE)
    with pytest.raises(AuthError) as error:
        verify(token)
    assert error.value.reason == "audience_mismatch"


def test_issuer_mismatch_is_rejected() -> None:
    token = make_token(issuer="http://evil.example")
    with pytest.raises(AuthError) as error:
        verify(token)
    assert error.value.reason == "issuer_mismatch"


def test_audience_list_containing_self_is_accepted() -> None:
    now = int(time.time())
    token = sign_token(
        {
            "iss": ISSUER,
            "sub": "user-1001",
            # aud は配列でもよい。自分が含まれていれば通す
            "aud": [OTHER_RESOURCE, RESOURCE],
            "exp": now + 300,
            "iat": now,
            "scope": SCOPE_DOCS_READ,
        },
        SECRET,
    )
    assert verify(token).subject == "user-1001"


# ------------------------------------------------------------ ミドルウェア
def test_middleware_returns_401_without_token() -> None:
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def receive() -> dict[str, Any]:  # 呼ばれない（401 で返すため）
        return {"type": "http.request", "body": b""}

    async def downstream(scope: dict[str, Any], _receive: Any, _send: Any) -> None:
        raise AssertionError("認証を通していないのに下流が呼ばれました")

    middleware = BearerAuthMiddleware(
        downstream, secret=SECRET, issuer=ISSUER, audience=RESOURCE
    )
    scope = {"type": "http", "path": "/mcp", "method": "POST", "headers": []}
    asyncio.run(middleware(scope, receive, send))

    start = sent[0]
    assert start["status"] == 401
    headers = {name.decode(): value.decode() for name, value in start["headers"]}
    assert "resource_metadata=" in headers["www-authenticate"]
    # ヘッダーは ASCII のみ（日本語を入れると送信時に壊れる）
    assert headers["www-authenticate"].isascii()


def test_middleware_publishes_metadata_without_token() -> None:
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b""}

    async def downstream(scope: dict[str, Any], _receive: Any, _send: Any) -> None:
        raise AssertionError("メタデータの取得で下流が呼ばれてはいけません")

    middleware = BearerAuthMiddleware(
        downstream, secret=SECRET, issuer=ISSUER, audience=RESOURCE
    )
    scope = {
        "type": "http",
        "path": "/.well-known/oauth-protected-resource/mcp",
        "method": "GET",
        "headers": [],
    }
    asyncio.run(middleware(scope, receive, send))

    assert sent[0]["status"] == 200
    assert b"authorization_servers" in sent[1]["body"]
