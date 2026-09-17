"""ASGI 認証ミドルウェア（Python 版）

TypeScript 版は http.RequestListener を包みましたが、Python SDK は HTTP サーバーを
内部で組み立てるため、包む場所が ASGI アプリになります。やっていることは同じです。

  ① Protected Resource Metadata を無認証で公開する
  ② Authorization ヘッダーを検証して 401
  ③ ベーススコープを見て 403
  ④ 認証文脈を scope["state"] に載せて下流へ渡す
"""

from __future__ import annotations

import json
import sys
from collections.abc import Awaitable, Callable
from typing import Any

from tokens import SCOPE_DOCS_READ, SUPPORTED_SCOPES, AuthError, verify_token

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


class BearerAuthMiddleware:
    def __init__(
        self,
        app: Callable[[Scope, Receive, Send], Awaitable[None]],
        *,
        secret: str,
        issuer: str,
        audience: str,
        endpoint: str = "/mcp",
        base_scope: str = SCOPE_DOCS_READ,
        skip_audience: bool = False,
    ) -> None:
        self.app = app
        self.secret = secret
        self.issuer = issuer
        self.audience = audience
        self.base_scope = base_scope
        self.skip_audience = skip_audience
        base = "/.well-known/oauth-protected-resource"
        # RFC 9728 のパス挿入と、パス無しの位置の両方で応答する
        self.metadata_paths = (base, f"{base}{endpoint}")
        origin = audience.split(endpoint)[0]
        self.metadata_url = f"{origin}{base}{endpoint}"
        self.metadata_body = json.dumps(
            {
                "resource": audience,
                "authorization_servers": [issuer],
                "scopes_supported": list(SUPPORTED_SCOPES),
                "bearer_methods_supported": ["header"],
                "resource_name": "社内ドキュメント検索 MCP サーバー（Python 版）",
            },
            ensure_ascii=False,
        ).encode("utf-8")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        if path in self.metadata_paths:
            await self._send(send, 200, self.metadata_body, [])
            return

        token = self._bearer_token(scope)
        if token is None:
            await self._challenge(send, 401, None, "An access token is required")
            return
        try:
            context = verify_token(
                token,
                secret=self.secret,
                issuer=self.issuer,
                audience=self.audience,
                skip_audience=self.skip_audience,
            )
        except AuthError as error:
            # 理由はログに残し、クライアントには一般化した文面だけ返す
            print(f"[mcp-auth] 認証失敗（{error.reason}）: {path}", file=sys.stderr)
            await self._challenge(send, 401, "invalid_token", "The access token is invalid")
            return

        if self.base_scope not in context.scopes:
            print(
                f"[mcp-auth] 認可失敗（insufficient_scope）: sub={context.subject}"
                f" token={context.fingerprint}",
                file=sys.stderr,
            )
            await self._challenge(
                send, 403, "insufficient_scope", "The token lacks the required scope", self.base_scope
            )
            return

        print(
            f"[mcp-auth] 許可: sub={context.subject} scopes={list(context.scopes)}"
            f" token={context.fingerprint}",
            file=sys.stderr,
        )
        # ASGI では scope["state"] が下流への受け渡しに使われる慣習の場所
        state = scope.setdefault("state", {})
        state["auth"] = context
        await self.app(scope, receive, send)

    @staticmethod
    def _bearer_token(scope: Scope) -> str | None:
        for name, value in scope.get("headers", []):
            if name.lower() == b"authorization":
                text = value.decode("latin-1").strip()
                if text.lower().startswith("bearer "):
                    return text[7:].strip()
                return None
        return None

    async def _challenge(
        self,
        send: Send,
        status: int,
        error: str | None,
        description: str,
        scope_hint: str | None = None,
    ) -> None:
        # ⚠️ ヘッダーには ASCII しか置けない。日本語は本文の JSON に書く
        parts = [f'Bearer resource_metadata="{self.metadata_url}"']
        if error is not None:
            parts.append(f'error="{error}"')
        parts.append(f'error_description="{description}"')
        if scope_hint is not None:
            parts.append(f'scope="{scope_hint}"')
        message = (
            "このトークンには必要な権限（スコープ）がありません。"
            if status == 403
            else "有効なアクセストークンが必要です。WWW-Authenticate ヘッダーの resource_metadata を参照してください。"
        )
        body = json.dumps(
            {"jsonrpc": "2.0", "error": {"code": -32005 if status == 403 else -32004, "message": message}, "id": None},
            ensure_ascii=False,
        ).encode("utf-8")
        await self._send(send, status, body, [(b"www-authenticate", ", ".join(parts).encode("ascii"))])

    @staticmethod
    async def _send(
        send: Send, status: int, body: bytes, extra: list[tuple[bytes, bytes]]
    ) -> None:
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
            *extra,
        ]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
