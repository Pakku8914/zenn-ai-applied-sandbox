// 問題2(c) の解答。「やってはいけない実装」を実際に書いて、何が漏れるかを目で見ます。
// 確認したら捨ててよいコードです。アプリに残してはいけません。
import { Hono } from "hono";
import * as client from "openid-client";
import { CLIENT_ID, REDIRECT_URI, SCOPE, getOpenIdConfig, toBrowserUrl } from "./rp-openid-config.js";

/** code_verifier をクエリに載せてしまう /login（悪い例） */
export function createLeakyLoginApp(): Hono {
  const app = new Hono();
  app.get("/login", async (c) => {
    const config = await getOpenIdConfig();
    const codeVerifier = client.randomPKCECodeVerifier();
    const codeChallenge = await client.calculatePKCECodeChallenge(codeVerifier);
    const url = client.buildAuthorizationUrl(config, {
      redirect_uri: REDIRECT_URI,
      scope: SCOPE,
      state: client.randomState(),
      nonce: client.randomNonce(),
      code_challenge: codeChallenge,
      code_challenge_method: "S256",
      // ❌ これが問題。手元に置くべき値をブラウザに渡している
      code_verifier: codeVerifier,
    });
    return c.redirect(toBrowserUrl(url).toString(), 302);
  });
  return app;
}

export async function reportLeak(): Promise<readonly string[]> {
  const app = createLeakyLoginApp();
  const res = await app.request("/login");
  const location = res.headers.get("location") ?? "";
  const params = new URL(location).searchParams;
  const verifier = params.get("code_verifier");
  return [
    `クライアント ID: ${CLIENT_ID}`,
    `リダイレクトのクエリに含まれるパラメータ: ${[...params.keys()].sort().join(", ")}`,
    `code_verifier がブラウザに渡ったか: ${verifier !== null}`,
    `code_challenge と対応しているか: ${verifier !== null && params.get("code_challenge") !== null}`,
  ];
}

if (process.argv[1]?.endsWith("rp-q2-leaky-login.ts") === true) {
  for (const line of await reportLeak()) console.log(line);
}
