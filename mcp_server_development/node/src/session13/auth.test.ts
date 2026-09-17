/**
 * 認証付きサーバーのテスト（問題6 の解答）
 *
 *   docker compose exec node npx vitest run src/session13/auth.test.ts
 *
 * ここで固定したいのは「正しいトークンが通ること」ではありません（正常系が動いている
 * 限り自明です）。「間違ったトークンが通らないこと」です。
 * とくに aud 不一致は、検証を外しても正常系が全部通るため、専用のテストが無いと
 * 欠陥が永久に見えません（セッション12 の警告）。
 */
import http from "node:http";
import type { AddressInfo } from "node:net";

import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { createAuthServer } from "../session12/auth-server.js";
import { SCOPE_DOCS_ADMIN, SCOPE_DOCS_READ } from "../session12/scopes.js";
import { createTokenVerifier } from "../session12/token-verifier.js";

/** このサーバー（Resource Server）の識別子。トークンの aud はこれと完全一致しなければならない */
const RESOURCE = "http://127.0.0.1:3939/mcp";
/** 別サービスの識別子。同じ認可サーバーが発行するが、宛先が違う */
const OTHER_RESOURCE = "http://127.0.0.1:3939/expenses";

let httpServer: http.Server;
let issuer = "";

beforeAll(async () => {
  // ポートは 0 を指定して OS に選ばせる（固定ポートは CI で他のジョブと衝突する）。
  // issuer は listen したあとにしか決まらないので、リスナーを後から差し替えられる形で起こす
  let listener: http.RequestListener | undefined;
  httpServer = http.createServer((req, res) => {
    if (listener === undefined) {
      res.writeHead(503).end();
      return;
    }
    listener(req, res);
  });

  await new Promise<void>((resolve, reject) => {
    httpServer.once("error", reject);
    httpServer.listen(0, "127.0.0.1", () => resolve());
  });

  const { port } = httpServer.address() as AddressInfo;
  issuer = `http://127.0.0.1:${port}`;
  // debug: true でテスト用の鋳造口（/debug/mint）が開く。本物の認可サーバーにこの口は無い
  listener = createAuthServer({ issuer, debug: true }).listener;
});

afterAll(async () => {
  httpServer.closeAllConnections();
  await new Promise<void>((resolve) => httpServer.close(() => resolve()));
});

/** テスト用トークンを鋳造する。手で JWT を組み立てないのは、署名を間違えて別の理由で落ちるのを避けるため */
async function mint(
  params: {
    readonly audience?: string;
    readonly scope?: string;
    readonly ttlSeconds?: number;
    readonly subject?: string;
  } = {},
): Promise<string> {
  const response = await fetch(`${issuer}/debug/mint`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      audience: params.audience ?? RESOURCE,
      scope: params.scope ?? SCOPE_DOCS_READ,
      ttlSeconds: params.ttlSeconds ?? 300,
      subject: params.subject ?? "user-1001",
    }),
  });
  const payload = (await response.json()) as { access_token?: string };
  if (typeof payload.access_token !== "string") {
    throw new Error(`トークンを鋳造できませんでした（status=${response.status}）`);
  }
  return payload.access_token;
}

function verifier(overrides: { readonly issuer?: string; readonly skipAudience?: boolean } = {}) {
  return createTokenVerifier({
    issuer: overrides.issuer ?? issuer,
    audience: RESOURCE,
    // ★ 鍵の所在は変えない。ここを変えると jwks_unavailable になり、見たい理由が観測できない
    jwksUri: `${issuer}/jwks`,
    ...(overrides.skipAudience === undefined ? {} : { skipAudience: overrides.skipAudience }),
  });
}

/** 通ってはいけないトークンの検証。理由コードだけを返す（文面ではなくコードで検査する） */
async function expectFailure(
  authorization: string | undefined,
  overrides: { readonly issuer?: string } = {},
): Promise<string> {
  const outcome = await verifier(overrides).verify(authorization);
  if (outcome.ok) {
    throw new Error("通ってはいけないトークンが通りました");
  }
  return outcome.reason;
}

/** ペイロードだけを書き換え、署名は元のまま使う（改ざんの再現） */
function tamperScope(token: string, scope: string): string {
  const [header, payload, signature] = token.split(".");
  if (header === undefined || payload === undefined || signature === undefined) {
    throw new Error("トークンの形式が想定と違います");
  }
  const claims = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as Record<
    string,
    unknown
  >;
  claims["scope"] = scope;
  const forged = Buffer.from(JSON.stringify(claims), "utf8").toString("base64url");
  return `${header}.${forged}.${signature}`;
}

describe("① 正しいトークン", () => {
  it("検証を通り、認証文脈にスコープが入る", async () => {
    const outcome = await verifier().verify(`Bearer ${await mint()}`);

    expect(outcome.ok).toBe(true);
    if (!outcome.ok) {
      return;
    }
    expect(outcome.context.subject).toBe("user-1001");
    expect(outcome.context.scopes).toContain(SCOPE_DOCS_READ);
    // ログに出すのはトークン本体ではなく相関 ID（sha256 の先頭 8 文字）
    expect(outcome.context.fingerprint).toHaveLength(8);
  });
});

describe("② 通してはいけないトークン", () => {
  it("期限切れは expired", async () => {
    expect(await expectFailure(`Bearer ${await mint({ ttlSeconds: -600 })}`)).toBe("expired");
  });

  it("別サービス向け（aud 不一致）は audience_mismatch", async () => {
    expect(await expectFailure(`Bearer ${await mint({ audience: OTHER_RESOURCE })}`)).toBe(
      "audience_mismatch",
    );
  });

  it("ペイロードを書き換えたトークンは bad_signature", async () => {
    const forged = tamperScope(await mint(), `${SCOPE_DOCS_READ} ${SCOPE_DOCS_ADMIN}`);

    // 署名検証がクレームより先に走っているので、書き換えは通らない
    expect(await expectFailure(`Bearer ${forged}`)).toBe("bad_signature");
  });

  const malformed: [string, string | undefined, string][] = [
    ["Authorization ヘッダーが無い", undefined, "missing_token"],
    ["トークンの形が壊れている", "Bearer abc", "malformed_token"],
  ];

  it.each(malformed)("%s → %s", async (_label, header, expected) => {
    expect(await expectFailure(header)).toBe(expected);
  });

  it("信頼していない発行者のトークンは issuer_mismatch", async () => {
    expect(
      await expectFailure(`Bearer ${await mint()}`, { issuer: "https://as.example.com" }),
    ).toBe("issuer_mismatch");
  });
});

describe("③ 欠陥の再現と、認証／認可の境界", () => {
  it("aud 検証を外すと、別サービス向けのトークンが通ってしまう", async () => {
    const token = await mint({ audience: OTHER_RESOURCE });

    const outcome = await verifier({ skipAudience: true }).verify(`Bearer ${token}`);

    // ❌ これが「aud 検証を外した実装」の姿。正常系のテストは全部通ったまま、この 1 件だけが違う
    expect(outcome.ok).toBe(true);
  });

  it("スコープが足りないトークンは「検証は通る」（認可は別の層の仕事）", async () => {
    const outcome = await verifier().verify(`Bearer ${await mint({ scope: SCOPE_DOCS_ADMIN })}`);

    expect(outcome.ok).toBe(true);
    if (!outcome.ok) {
      return;
    }
    expect(outcome.context.scopes).toEqual([SCOPE_DOCS_ADMIN]);
    // docs:read が無いから断る、という判断は HTTP 層（403）かツール実行層（isError）で行う
    expect(outcome.context.scopes.includes(SCOPE_DOCS_READ)).toBe(false);
  });
});
