// 認可リクエストを組み立て、state と code_verifier を手元に保管し、
// コールバックで state を突き合わせる。クライアント（web-app）側の実装です。
import { randomBytes } from "node:crypto";
import { CLIENT_ID, ISSUER_PUBLIC, REDIRECT_URI, SCOPE, authorizationEndpoint } from "./bookstore-client.js";
import { createPkcePair } from "./rp-pkce.js";

export type AuthorizationRequest = {
  /** ブラウザに渡すなら ISSUER_PUBLIC、コードから直接叩くなら ISSUER_INTERNAL */
  issuer: string;
  state: string;
  codeChallenge: string;
  clientId?: string;
  redirectUri?: string;
  scope?: string;
  /**
   * 仕様から外れたリクエストを作って挙動を観察するための上書き（実験用）。
   * 値に null を渡すとそのパラメータを削除します。
   */
  override?: Record<string, string | null>;
};

/** 認可エンドポイントに向ける URL を組み立てます */
export function buildAuthorizationUrl(req: AuthorizationRequest): string {
  const params = new URLSearchParams({
    response_type: "code", // 認可コードフロー。token を指定するのが廃止された implicit
    client_id: req.clientId ?? CLIENT_ID,
    redirect_uri: req.redirectUri ?? REDIRECT_URI,
    scope: req.scope ?? SCOPE,
    state: req.state, // 戻ってきたときに「自分が始めたログインか」を見分ける値
    code_challenge: req.codeChallenge, // code_verifier のハッシュ
    code_challenge_method: "S256", // plain は使わない
  });
  for (const [key, value] of Object.entries(req.override ?? {})) {
    if (value === null) params.delete(key);
    else params.set(key, value);
  }
  return `${authorizationEndpoint(req.issuer)}?${params}`;
}

/** コールバックを受け付けられなかった理由。メッセージの文面ではなくこの値で分岐します */
export type CallbackFailureReason = "authorization_error" | "state_mismatch" | "missing_code";

export class CallbackError extends Error {
  readonly reason: CallbackFailureReason;

  constructor(reason: CallbackFailureReason, message: string) {
    super(message);
    this.reason = reason;
  }
}

export type PendingLogin = { state: string; codeVerifier: string };

/**
 * 始めたけれどまだ終わっていないログインを、state をキーに覚えておく入れ物です。
 * 本番では Cookie で紐づけたサーバー側セッションに置きます（メモリに持つのは学習用の簡略化）。
 */
export class PendingLoginStore {
  private readonly pending = new Map<string, PendingLogin>();

  /** ログインを開始します。ブラウザに渡す URL と、手元に残す state / code_verifier を返します */
  start(issuer: string = ISSUER_PUBLIC): { authorizationUrl: string; state: string; codeVerifier: string } {
    const state = randomBytes(16).toString("base64url");
    const { codeVerifier, codeChallenge } = createPkcePair();
    this.pending.set(state, { state, codeVerifier });
    return {
      authorizationUrl: buildAuthorizationUrl({ issuer, state, codeChallenge }),
      state,
      codeVerifier,
    };
  }

  /** 別の手段で始めたログインを預けます（検証でブラウザ役のヘルパーと合流するために使う） */
  remember(entry: PendingLogin): void {
    this.pending.set(entry.state, entry);
  }

  /** コールバックのクエリから、認可コードと code_verifier を取り出します */
  consumeCallback(params: URLSearchParams): { code: string; codeVerifier: string } {
    // 1. エラーで戻ってきた場合はここで終わり（code も state も当てにできない）
    const error = params.get("error");
    if (error !== null) {
      throw new CallbackError(
        "authorization_error",
        `認可サーバーがエラーを返しました: ${error} / ${params.get("error_description") ?? ""}`,
      );
    }
    // 2. state の突き合わせ。保管していない state は「自分が始めていないログイン」
    const state = params.get("state") ?? ""; // state が無い場合も「一致しない」として扱う
    const entry = this.pending.get(state);
    if (entry === undefined) {
      throw new CallbackError("state_mismatch", "state が一致しません（自分が始めたログインではありません）");
    }
    this.pending.delete(state); // 1 度使った state は捨てる（同じコールバックは 2 回処理できない）
    // 3. ここまで通ってから認可コードを取り出す
    const code = params.get("code");
    if (code === null) {
      throw new CallbackError("missing_code", "認可コードがありません");
    }
    return { code, codeVerifier: entry.codeVerifier };
  }

  /** 保管中のログインの数（検証用） */
  get size(): number {
    return this.pending.size;
  }
}

export type AuthzOutcome = {
  status: number;
  result: "ログイン画面" | "エラーでリダイレクト" | "エラーページ" | "その他";
  error: string | null;
  description: string | null;
  /** エラーがクエリで返ったか、フラグメント（#）で返ったか */
  place: "query" | "fragment" | "-";
};

/**
 * 認可リクエストを 1 回投げて、応答の形を分類します（実験用）。
 * リダイレクトを追わないので、認可サーバーがどこに何を返したかがそのまま観察できます。
 */
export async function probeAuthorizationRequest(urlString: string): Promise<AuthzOutcome> {
  const res = await fetch(urlString, { redirect: "manual" });
  const body = await res.text();
  const location = res.headers.get("location");

  if (location !== null) {
    const target = new URL(location);
    const query = target.searchParams;
    const fragment = new URLSearchParams(target.hash.replace(/^#/, ""));
    const error = query.get("error") ?? fragment.get("error");
    if (error !== null) {
      return {
        status: res.status,
        result: "エラーでリダイレクト",
        error,
        description: query.get("error_description") ?? fragment.get("error_description"),
        place: query.get("error") !== null ? "query" : "fragment",
      };
    }
    return { status: res.status, result: "その他", error: null, description: null, place: "-" };
  }

  if (res.status === 200 && body.includes('id="kc-form-login"')) {
    return { status: 200, result: "ログイン画面", error: null, description: null, place: "-" };
  }
  return {
    status: res.status,
    result: res.status >= 400 ? "エラーページ" : "その他",
    error: null,
    description: null,
    place: "-",
  };
}
