// セッション 17 練習問題 4: パスキーでのログインを HTTP に組み込む。
// セッション 3 の SessionStore（ログイン時の ID 再生成つき）をそのまま使います。
import { Hono } from "hono";
import { getCookie, setCookie } from "hono/cookie";
import { SessionStore } from "../session03/web-app-session-store.js";
import { SESSION_COOKIE } from "../session03/web-app-session-login.js";
import { fromBase64Url, toBase64Url } from "./bookstore-webauthn.js";
import { CredentialStore, WebAuthnChallengeStore, verifyAssertion } from "./rp-webauthn-verify.js";
import type { AssertionInput } from "./rp-webauthn-verify.js";
import type { AssertionResponse } from "./authenticator-stub.js";

const asRecord = (value: unknown): Record<string, unknown> =>
  (typeof value === "object" && value !== null ? value : {}) as Record<string, unknown>;

/** ブラウザ役が JSON にして送る形（バイト列は base64url にします） */
export function toAssertionBody(response: AssertionResponse): Record<string, string> {
  return {
    credentialId: response.credentialId,
    clientDataJson: toBase64Url(response.clientDataJson),
    authenticatorData: toBase64Url(response.authenticatorData),
    signature: toBase64Url(response.signature),
  };
}

/** 受け取った JSON を検証の入力に戻します。1 つでも欠けたら undefined */
export function toAssertionInput(body: Record<string, unknown>): AssertionInput | undefined {
  const credentialId = body["credentialId"];
  const clientDataJson = body["clientDataJson"];
  const authenticatorData = body["authenticatorData"];
  const signature = body["signature"];
  if (typeof credentialId !== "string" || typeof clientDataJson !== "string") return undefined;
  if (typeof authenticatorData !== "string" || typeof signature !== "string") return undefined;
  return {
    credentialId,
    clientDataJson: fromBase64Url(clientDataJson),
    authenticatorData: fromBase64Url(authenticatorData),
    signature: fromBase64Url(signature),
  };
}

export type PasskeyAppOptions = {
  readonly credentials?: CredentialStore;
  readonly challenges?: WebAuthnChallengeStore;
  readonly sessions?: SessionStore;
};

export type PasskeyApp = {
  readonly app: Hono;
  readonly credentials: CredentialStore;
  readonly challenges: WebAuthnChallengeStore;
  readonly sessions: SessionStore;
};

export function createPasskeyApp(options: PasskeyAppOptions = {}): PasskeyApp {
  const credentials = options.credentials ?? new CredentialStore();
  const challenges = options.challenges ?? new WebAuthnChallengeStore();
  const sessions = options.sessions ?? new SessionStore();
  const app = new Hono();

  app.post("/passkey/login/start", async (c) => {
    const body = asRecord(await c.req.json().catch(() => ({})));
    const userId = typeof body["userId"] === "string" ? body["userId"] : "";
    const pending = challenges.start("webauthn.get", userId);
    c.header("cache-control", "no-store");
    // 利用者がいてもいなくても同じ形・同じ status で返します（存在を漏らさない）
    return c.json({
      challenge: pending.challenge,
      rpId: pending.rpId,
      origin: pending.origin,
      allowCredentials: credentials.forUser(userId).map((credential) => credential.credentialId),
    });
  });

  app.post("/passkey/login/finish", async (c) => {
    const body = asRecord(await c.req.json().catch(() => ({})));
    const input = toAssertionInput(body);
    c.header("cache-control", "no-store");
    if (input === undefined) {
      return c.json({ error: "malformed_request" }, 400);
    }
    const result = verifyAssertion(input, challenges, credentials);
    if (!result.ok) {
      // 失敗時は Cookie を一切触りません（セッションを作ってから落とすと固定攻撃の足場になります）
      return c.json({ error: result.reason }, 401);
    }
    // ログインが成立した瞬間にセッション ID を作り直します（セッション 3 の固定攻撃対策）
    const session = sessions.regenerate(getCookie(c, SESSION_COOKIE), result.userId);
    setCookie(c, SESSION_COOKIE, session.id, {
      path: "/",
      httpOnly: true,
      sameSite: "Lax",
      secure: false, // 学習環境は HTTP。本番では必ず true
    });
    return c.json({ userId: result.userId, signCount: result.signCount });
  });

  return { app, credentials, challenges, sessions };
}
