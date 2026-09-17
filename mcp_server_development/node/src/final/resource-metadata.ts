/**
 * Protected Resource Metadata を最終プロジェクトの仕様で公開するミドルウェア
 *
 * セッション12 の protectWithOAuth は、セッション12 のスコープ（docs:*）で
 * メタデータを組み立てます。セッション12 のファイルは書き換えない方針なので、
 * その「外側」に 1 枚かぶせて、メタデータのパスだけを自分で処理します。
 *
 * ★ 認証より外側に置くことが必須です。401 を受けた人がここを読みに来るので、
 *   ここを保護すると発見フローが永久に閉じます（鶏と卵）。
 */
import http from "node:http";

import { protectedResourceMetadataPaths } from "../session12/auth-middleware.js";

export type ResourceMetadataOptions = {
  readonly inner: http.RequestListener;
  readonly resource: string;
  readonly authorizationServers: readonly string[];
  readonly scopesSupported: readonly string[];
  readonly resourceName: string;
  readonly endpoint?: string;
};

export function withResourceMetadata(options: ResourceMetadataOptions): http.RequestListener {
  const endpoint = options.endpoint ?? "/mcp";
  // パスの決め方（RFC 9728）はセッション12 の実装を再利用する。2 か所に書かない
  const paths = new Set(protectedResourceMetadataPaths(endpoint));
  const body = JSON.stringify({
    resource: options.resource,
    authorization_servers: [...options.authorizationServers],
    scopes_supported: [...options.scopesSupported],
    bearer_methods_supported: ["header"],
    resource_name: options.resourceName,
  });

  return (req, res) => {
    const pathname = new URL(req.url ?? "/", "http://placeholder").pathname;
    if (!paths.has(pathname)) {
      options.inner(req, res);
      return;
    }
    if (req.method !== "GET") {
      res.writeHead(405, { allow: "GET", "content-type": "application/json" });
      res.end(JSON.stringify({ error: "method_not_allowed" }));
      return;
    }
    res.writeHead(200, {
      "content-type": "application/json",
      "content-length": Buffer.byteLength(body),
      // 変わらない情報なのでキャッシュさせる
      "cache-control": "public, max-age=3600",
    });
    res.end(body);
  };
}
