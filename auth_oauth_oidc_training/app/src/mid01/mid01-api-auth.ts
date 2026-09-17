// 中間プロジェクト mid01: api-service が Authorization ヘッダを受け取って「誰か」を確定する部分。
// 署名・iss・aud・時刻の検証はセッション 4 で書いた verifyAccessToken() をそのまま使い、
// ここでは HTTP の入口の作法（Bearer の取り出しと、失敗の伝え方）だけを足します。
import type { JWTPayload } from "jose";
import { rejectReason, verifyAccessToken } from "../session04/api-service-verify-jwt.js";

/** 検証を通ったトークンから取り出した呼び出し元。画面にも認可判断にも、ここから先は claims を直接使いません */
export type AuthenticatedCaller = {
  /** 不変の識別子。利用者名が変わっても変わらない（セッション 8） */
  readonly sub: string;
  /** 表示と対応表の初回登録にだけ使う利用者名 */
  readonly username: string;
  /** aud を配列に正規化したもの（セッション 4） */
  readonly audiences: readonly string[];
};

export type AuthFailure = {
  readonly ok: false;
  /**
   * WWW-Authenticate に載せる error。
   * RFC 6750 は「認証情報がまったく無い場合は error を付けない」と定めているため undefined になりえます。
   */
  readonly error: "invalid_request" | "invalid_token" | undefined;
  /** 失敗の理由。ログにだけ書き、クライアントには返しません */
  readonly logReason: string;
};

export type AuthResult = { readonly ok: true; readonly caller: AuthenticatedCaller } | AuthFailure;

/**
 * aud は文字列にも配列にもなります（セッション 4 の実測）。
 * 検証側は必ず配列に正規化してから扱います。
 */
export function audiencesOf(claims: JWTPayload): string[] {
  const aud: unknown = claims.aud;
  if (typeof aud === "string") {
    return [aud];
  }
  if (Array.isArray(aud)) {
    return aud.filter((value): value is string => typeof value === "string");
  }
  return [];
}

/** クレームは JSON なので、文字列として使う前に型を確かめます */
export function claimAsString(claims: JWTPayload, name: string): string {
  const value = claims[name];
  return typeof value === "string" ? value : "";
}

/**
 * Authorization ヘッダから Bearer トークンを取り出します。
 * スキームの綴りは大文字小文字を区別しません（RFC 7235）。書式が違えば undefined を返します。
 */
export function bearerTokenOf(header: string | undefined): string | undefined {
  if (header === undefined) {
    return undefined;
  }
  const parts = header.trim().split(/\s+/);
  if (parts.length !== 2) {
    return undefined;
  }
  const scheme = parts[0];
  const token = parts[1];
  if (scheme === undefined || scheme.toLowerCase() !== "bearer" || token === undefined || token === "") {
    return undefined;
  }
  return token;
}

/**
 * Authorization ヘッダ 1 本から「誰か」を確定します。
 * HTTP には触らない純粋な関数にしてあるので、サーバーを起動しなくても単体で確かめられます。
 */
export async function authenticate(authorization: string | undefined): Promise<AuthResult> {
  const token = bearerTokenOf(authorization);
  if (token === undefined) {
    return {
      ok: false,
      // ヘッダ自体が無いのは「まだ出していない」だけなので error を付けず、認証方法だけを教える
      error: authorization === undefined ? undefined : "invalid_request",
      logReason: authorization === undefined ? "Authorization ヘッダが無い" : "Bearer の書式ではない",
    };
  }
  try {
    // 署名 → iss → aud → 時刻。4 つとも verifyOptions で指定済み（セッション 4）
    const { payload } = await verifyAccessToken(token);
    const sub = payload.sub;
    if (sub === undefined || sub === "") {
      // 誰のトークンか分からないものは通せません
      return { ok: false, error: "invalid_token", logReason: "sub が無いトークン" };
    }
    return {
      ok: true,
      caller: {
        sub,
        username: claimAsString(payload, "preferred_username"),
        audiences: audiencesOf(payload),
      },
    };
  } catch (err) {
    return { ok: false, error: "invalid_token", logReason: rejectReason(err) };
  }
}
