/**
 * Origin / Host の検証 ―― ローカルで待ち受ける HTTP サーバーの必須対策
 *
 * ブラウザ上の JavaScript は Origin ヘッダーを偽装できません（fetch では設定不可）。
 * だから「Origin が許可リストに無ければ 403」というだけの単純な検査が、
 * 悪意あるサイトからローカルサーバーを叩く経路（DNS リバインディング）を塞げます。
 *
 * セッション12（OAuth 2.1）では、この検証の直後に「トークン検証」を 1 段足します。
 */
import type { IncomingHttpHeaders } from "node:http";

/** 既定で許可する Origin。MCP Inspector の UI（既定ポート 6274）だけを通す */
export const DEFAULT_ALLOWED_ORIGINS: readonly string[] = [
  "http://127.0.0.1:6274",
  "http://localhost:6274",
];

/** Host ヘッダーの許可リストはポート番号に依存するので関数で作る */
export function defaultAllowedHosts(port: number): string[] {
  return [`127.0.0.1:${port}`, `localhost:${port}`];
}

export type TrustPolicy = {
  /** false にすると検証を丸ごと外す（Bad 実装の実験用。本番では絶対に false にしない） */
  readonly enabled: boolean;
  readonly allowedOrigins: readonly string[];
  readonly allowedHosts: readonly string[];
};

export type TrustFailure = "origin_not_allowed" | "host_not_allowed";

export type TrustResult =
  | { readonly ok: true }
  | { readonly ok: false; readonly reason: TrustFailure; readonly detail: string };

export function createTrustPolicy(overrides: Partial<TrustPolicy> = {}): TrustPolicy {
  return {
    enabled: overrides.enabled ?? true,
    allowedOrigins: overrides.allowedOrigins ?? DEFAULT_ALLOWED_ORIGINS,
    allowedHosts: overrides.allowedHosts ?? defaultAllowedHosts(3939),
  };
}

/** 環境変数から組み立てる。設定を外から差し替えられるようにしておく */
export function resolveTrustPolicy(env: NodeJS.ProcessEnv, port: number): TrustPolicy {
  const origins = env["MCP_ALLOWED_ORIGINS"];
  const hosts = env["MCP_ALLOWED_HOSTS"];
  return createTrustPolicy({
    // 実験用の抜け道。既定は「有効」で、明示的に off と書いたときだけ無効になる
    enabled: env["MCP_TRUST_CHECK"] !== "off",
    allowedOrigins: origins === undefined ? DEFAULT_ALLOWED_ORIGINS : splitList(origins),
    allowedHosts: hosts === undefined ? defaultAllowedHosts(port) : splitList(hosts),
  });
}

export function verifyRequestTrust(headers: IncomingHttpHeaders, policy: TrustPolicy): TrustResult {
  if (!policy.enabled) {
    return { ok: true };
  }

  // Origin が無いリクエスト＝ブラウザ以外（curl・SDK クライアント・Inspector CLI）。
  // ブラウザは必ず Origin を付けるので、「無い」ことは「ブラウザ発ではない」を意味する
  const origin = firstHeader(headers.origin);
  if (origin !== undefined && origin !== "" && !policy.allowedOrigins.includes(origin)) {
    return {
      ok: false,
      reason: "origin_not_allowed",
      detail: "この Origin からのリクエストは許可されていません。",
    };
  }

  // Host も見る（多層防御）。DNS リバインディングでは Host が攻撃者のドメインになる
  const host = firstHeader(headers.host);
  if (host !== undefined && host !== "" && !policy.allowedHosts.includes(host)) {
    return {
      ok: false,
      reason: "host_not_allowed",
      detail: "この Host 名では受け付けていません。",
    };
  }

  return { ok: true };
}

/** ヘッダーは配列で来ることがある（同名ヘッダーが複数ある場合） */
export function firstHeader(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function splitList(raw: string): string[] {
  return raw
    .split(",")
    .map((value) => value.trim())
    .filter((value) => value.length > 0);
}
