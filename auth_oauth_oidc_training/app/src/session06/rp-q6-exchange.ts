// 練習問題 6（発展）その 2: ブラウザが受け取ったコールバック URL を渡して、
// 自分の手で認可コードをアクセストークンに交換する。
import { readFile } from "node:fs/promises";
import type { PendingLogin } from "./rp-authorize.js";
import { PendingLoginStore } from "./rp-authorize.js";
import { TokenExchangeError, exchangeCodeForTokens } from "./rp-token-exchange.js";
import { decodeJwtPart } from "../test-helpers/headless-login.js";

// rp-q6-start.ts が書き出した置き場（import すると start 側が動いてしまうので値を持ち直します）
const PENDING_FILE = "/tmp/session06-pending.json";

const callbackUrl = process.argv[2];
if (callbackUrl === undefined) {
  console.error('使い方: npx tsx src/session06/rp-q6-exchange.ts "<コールバックの URL 全体>"');
  process.exit(1);
}

const pending = JSON.parse(await readFile(PENDING_FILE, "utf8")) as PendingLogin;
const store = new PendingLoginStore();
store.remember(pending);

const params = new URL(callbackUrl).searchParams;
console.log(`コールバックのクエリ: ${[...params.keys()].sort().join(", ")}`);

const { code, codeVerifier } = store.consumeCallback(params);
console.log("state の突き合わせ: 成功");

try {
  const tokens = await exchangeCodeForTokens({ code, codeVerifier });
  const payload = decodeJwtPart<{ azp: string; preferred_username: string }>(tokens.access_token, 1);
  console.log(`交換に成功しました: token_type=${tokens.token_type} expires_in=${tokens.expires_in}`);
  console.log(`ログインした利用者: ${payload.preferred_username}`);
  console.log(`このトークンを発行させたクライアント（azp）: ${payload.azp}`);
} catch (err) {
  if (!(err instanceof TokenExchangeError)) throw err;
  console.error(`交換に失敗しました: HTTP ${err.status} ${err.error} / ${err.errorDescription}`);
  console.error("認可コードは短命です。期限切れならもう一度 rp-q6-start.ts から やり直してください。");
  process.exit(1);
}
