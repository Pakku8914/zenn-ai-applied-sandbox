"""HS256（共有鍵）のアクセストークン ―― 標準ライブラリだけで署名・検証する

TypeScript 版は RS256（非対称鍵 ＋ JWKS）です。ここでは対称鍵の HS256 を書きます。
違いは「秘密を誰が持つか」の 1 点で、これが構成の選択肢を決めます（下の表）。

⚠️ 学習用です。本番では実績あるライブラリ（PyJWT / authlib）と JWKS を使ってください。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass

ALGORITHM = "HS256"
CLOCK_SKEW_SECONDS = 60
SCOPE_DOCS_READ = "docs:read"
SCOPE_DOCS_ADMIN = "docs:admin"
SUPPORTED_SCOPES = (SCOPE_DOCS_READ, SCOPE_DOCS_ADMIN)


class AuthError(Exception):
    """検証失敗。reason は機械可読な理由コード（クライアントには返さずログに残す）"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class AuthContext:
    subject: str
    client_id: str | None
    scopes: tuple[str, ...]
    expires_at: int
    fingerprint: str


def b64url_encode(raw: bytes) -> str:
    # JWT の base64url は padding（=）を付けない
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    # 逆に、デコードのときは padding を足してやる必要がある
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def load_shared_secret() -> str:
    """秘密はコードに書かない。環境変数から読み、短すぎる値は拒否する"""
    secret = os.environ.get("MCP_SHARED_SECRET", "")
    if len(secret) < 32:
        raise SystemExit(
            "環境変数 MCP_SHARED_SECRET（32 文字以上）を設定してください。コードには書かないこと。"
        )
    return secret


def _dumps(value: dict[str, object]) -> bytes:
    # 区切りに空白を入れない（トークンを無駄に長くしない）
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _signature(signing_input: str, secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()


def sign_token(claims: dict[str, object], secret: str) -> str:
    header = {"alg": ALGORITHM, "typ": "JWT"}
    signing_input = f"{b64url_encode(_dumps(header))}.{b64url_encode(_dumps(claims))}"
    return f"{signing_input}.{b64url_encode(_signature(signing_input, secret))}"


def issue_access_token(
    *,
    secret: str,
    issuer: str,
    audience: str,
    subject: str = "user-1001",
    scope: str = SCOPE_DOCS_READ,
    ttl_seconds: int = 300,
    client_id: str = "python-client",
) -> str:
    """テスト用の発行。本番でこれをリソースサーバー側に置いてはいけません
    （＝リソースサーバーが発行もできてしまう。対称鍵の弱点そのものです）"""
    now = int(time.time())
    return sign_token(
        {
            "iss": issuer,
            "sub": subject,
            "aud": audience,
            "exp": now + ttl_seconds,
            "iat": now,
            "nbf": now,
            "scope": scope,
            "client_id": client_id,
        },
        secret,
    )


def verify_token(
    token: str,
    *,
    secret: str,
    issuer: str,
    audience: str,
    skip_audience: bool = False,
    now: int | None = None,
) -> AuthContext:
    """検証の順序は TypeScript 版と同じ（形式 → alg → 署名 → iss → exp → aud）"""
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthError("malformed_token")
    raw_header, raw_payload, raw_signature = parts
    try:
        header = json.loads(b64url_decode(raw_header))
        claims = json.loads(b64url_decode(raw_payload))
        signature = b64url_decode(raw_signature)
    except (ValueError, UnicodeDecodeError) as error:
        raise AuthError("malformed_token") from error
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise AuthError("malformed_token")

    # ① alg は許可リスト方式。"none" を受け入れたら署名検証が無意味になる
    if header.get("alg") != ALGORITHM:
        raise AuthError("unsupported_alg")
    # ② 署名。比較は必ず定数時間で（== は不一致の位置が処理時間に出る）
    expected = _signature(f"{raw_header}.{raw_payload}", secret)
    if not hmac.compare_digest(expected, signature):
        raise AuthError("bad_signature")
    # ③ 発行者
    if claims.get("iss") != issuer:
        raise AuthError("issuer_mismatch")
    # ④ 時刻
    current = int(time.time()) if now is None else now
    exp = claims.get("exp")
    if not isinstance(exp, int) or exp + CLOCK_SKEW_SECONDS < current:
        raise AuthError("expired")
    nbf = claims.get("nbf")
    if isinstance(nbf, int) and nbf - CLOCK_SKEW_SECONDS > current:
        raise AuthError("not_yet_valid")
    # ⑤ オーディエンス（ここを外すと他サービス向けトークンが通る）
    if not skip_audience and not _audience_matches(claims.get("aud"), audience):
        raise AuthError("audience_mismatch")

    scope = claims.get("scope")
    client_id = claims.get("client_id")
    return AuthContext(
        subject=claims["sub"] if isinstance(claims.get("sub"), str) else "(unknown)",
        client_id=client_id if isinstance(client_id, str) else None,
        scopes=tuple(scope.split()) if isinstance(scope, str) else (),
        expires_at=exp,
        # トークン本体ではなく指紋だけをログに使う
        fingerprint=hashlib.sha256(token.encode("ascii")).hexdigest()[:8],
    )


def _audience_matches(aud: object, expected: str) -> bool:
    if isinstance(aud, str):
        return aud == expected
    if isinstance(aud, list):
        return any(value == expected for value in aud)
    return False
