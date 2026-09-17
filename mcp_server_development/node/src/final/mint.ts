/**
 * 検証用のトークン取得（クライアント側）
 *
 * requests:* はセッション12 のモック認可サーバーの許可リストに載っていないため、
 * 動的クライアント登録を通す完全なフローでは付与されません。検証を決定的にする目的で
 * MCP_AS_DEBUG=on のときだけ開く鋳造口を使います。
 *
 * ⚠️ 本物の認可サーバーにこの口があってはいけません。
 */
export type MintOptions = {
  readonly issuer?: string;
  readonly audience: string;
  readonly scope: string;
  readonly ttlSeconds?: number;
  readonly subject?: string;
};

export async function mintToken(options: MintOptions): Promise<string> {
  const issuer = options.issuer ?? "http://127.0.0.1:9100";
  const response = await fetch(`${issuer}/debug/mint`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify({
      audience: options.audience,
      scope: options.scope,
      ttlSeconds: options.ttlSeconds ?? 300,
      ...(options.subject === undefined ? {} : { subject: options.subject }),
    }),
  });
  if (!response.ok) {
    throw new Error(
      `トークンの鋳造に失敗しました（status=${response.status}）。` +
        "MCP_AS_DEBUG=on で認可サーバーを起動していますか？",
    );
  }
  const payload = (await response.json()) as { access_token?: unknown };
  if (typeof payload.access_token !== "string") {
    throw new Error("応答に access_token がありません");
  }
  return payload.access_token;
}
