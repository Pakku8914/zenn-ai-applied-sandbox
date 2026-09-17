// 問題 4 の解答: セッション固定攻撃を再現し、ID 再生成の有無で結果が変わることを確かめます。
// 実行: docker compose exec app npx tsx src/session03/web-app-q4-fixation.ts
import { pathToFileURL } from "node:url";
import { call, cookieHeader, parseSetCookie } from "./web-app-cookie-tools.js";
import { SESSION_COOKIE, createWebApp } from "./web-app-session-login.js";

export type FixationResult = {
  readonly rotateSessionIdOnLogin: boolean;
  /** 被害者のログインは成功したか（攻撃者がいても成功してしまう） */
  readonly loginStatus: number;
  /** ログインでセッション ID が変わったか */
  readonly idChanged: boolean;
  /** 攻撃者が仕込んだ ID で /me を叩いた結果（200 なら乗っ取り成立） */
  readonly attackerStatus: number;
};

export async function runFixationScenario(rotateSessionIdOnLogin: boolean): Promise<FixationResult> {
  const app = await createWebApp({ rotateSessionIdOnLogin });

  // 1. 攻撃者が正規の手順でセッション ID を 1 つ受け取る（この時点では誰でもない匿名セッション）
  const planted = parseSetCookie((await call(app, "/cart")).setCookie)?.value ?? "";

  // 2. その ID を被害者のブラウザに仕込んだ状態で、被害者が正しいパスワードでログインする
  const login = await call(app, "/login", {
    method: "POST",
    cookie: cookieHeader(SESSION_COOKIE, planted),
    form: { username: "alice", password: "alice-pass" },
  });
  const after = parseSetCookie(login.setCookie)?.value ?? planted;

  // 3. 攻撃者が仕込んだ ID をそのまま使い、被害者になりすませるか試す
  const attack = await call(app, "/me", { cookie: cookieHeader(SESSION_COOKIE, planted) });

  return {
    rotateSessionIdOnLogin,
    loginStatus: login.status,
    idChanged: after !== planted,
    attackerStatus: attack.status,
  };
}

async function main(): Promise<void> {
  console.log("=== セッション固定攻撃の再現 ===");
  for (const rotate of [false, true]) {
    const result = await runFixationScenario(rotate);
    console.log(`--- ログイン時に ID を再生成する: ${rotate} ---`);
    console.log(`被害者のログイン : ${result.loginStatus}`);
    console.log(`ID は変わったか : ${result.idChanged}`);
    console.log(`攻撃者の /me : ${result.attackerStatus}`);
  }
}

const invokedDirectly =
  process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href;
if (invokedDirectly) {
  await main();
}
