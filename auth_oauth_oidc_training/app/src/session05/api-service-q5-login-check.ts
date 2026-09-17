// 練習問題 5 の解答。
// 「アクセストークンの検証が通った」を「ログインできた」と読み替えると何が起きるかを、
// 動くコードで確かめるためのリソースサーバーです。
// /me が壊れている書き方（Bad）、/orders/:orderId が正しい書き方（Good）です。
import { Hono } from "hono";
import { createRemoteJWKSet, jwtVerify } from "jose";
import { AUDIENCE, ISSUER, JWKS_URI } from "../session04/bookstore-endpoints.js";

// 公開鍵はセッション 4 と同じ入手口。取得結果はライブラリ側でキャッシュされます
const jwks = createRemoteJWKSet(new URL(JWKS_URI));

/** 注文の持ち主。セッション 2 で決めた題材をそのまま使います */
const ORDER_OWNERS: Readonly<Record<string, string>> = {
  "order-1001": "alice",
  "order-1002": "alice",
  "order-2001": "bob",
};

type Presenter = {
  /** トークンの持ち主を表す、変わらない識別子 */
  readonly subject: string;
  /** 題材の語彙（alice / bob）と突き合わせるための表示名 */
  readonly username: string;
  /** このトークンを要求したクライアント */
  readonly client: string;
};

/** Authorization ヘッダのアクセストークンを検証する（セッション 4 の手順と同じ） */
async function verifyBearer(header: string | undefined): Promise<Presenter | null> {
  if (header === undefined || !header.startsWith("Bearer ")) {
    return null;
  }
  try {
    const { payload } = await jwtVerify(header.slice("Bearer ".length), jwks, {
      // セッション 4 の verifyOptions をそのまま使う。algorithms を省くと
      // 「検証方法をトークンに決めさせる」状態に戻ってしまう
      algorithms: ["RS256"],
      issuer: ISSUER,
      audience: AUDIENCE,
      clockTolerance: 5,
    });
    return {
      subject: typeof payload.sub === "string" ? payload.sub : "",
      username:
        typeof payload["preferred_username"] === "string" ? payload["preferred_username"] : "",
      client: typeof payload["azp"] === "string" ? payload["azp"] : "",
    };
  } catch {
    // 署名・iss・aud・時刻のどれかが合わなければ、持ち主を名乗らせない
    return null;
  }
}

export function createApiService() {
  const app = new Hono();

  // Bad（セキュリティの問題）: 検証が通ったことを「ログイン成功」と読み替えている。
  // このトークンは利用者が一度もログインしていなくても手に入ります。
  app.get("/me", async (c) => {
    const presenter = await verifyBearer(c.req.header("authorization"));
    if (presenter === null) {
      return c.json({ error: "unauthorized" }, 401);
    }
    return c.json({ loggedIn: true, user: presenter.username, client: presenter.client });
  });

  // Good（セキュリティの改善）: 「誰が来たか」ではなく「この操作が許されているか」を判断する。
  app.get("/orders/:orderId", async (c) => {
    const presenter = await verifyBearer(c.req.header("authorization"));
    if (presenter === null) {
      return c.json({ error: "unauthorized" }, 401);
    }
    const orderId = c.req.param("orderId");
    const owner = ORDER_OWNERS[orderId];
    if (owner === undefined) {
      return c.json({ error: "not_found" }, 404);
    }
    if (presenter.username !== owner) {
      // 誰であるかは分かるが、この注文を読む権限は無い（セッション 2 の 403）
      return c.json({ error: "forbidden" }, 403);
    }
    return c.json({ orderId, owner });
  });

  return app;
}
