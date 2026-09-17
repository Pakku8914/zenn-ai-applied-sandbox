// 練習問題 6（発展）その 1: 本物のブラウザでログインするための URL を作り、
// state と code_verifier をファイルに預ける。
import { writeFile } from "node:fs/promises";
import { ISSUER_PUBLIC } from "./bookstore-client.js";
import { PendingLoginStore } from "./rp-authorize.js";

/** プロセスをまたいで持ち越すための置き場（コンテナの中だけに置く。Git には残らない） */
export const PENDING_FILE = "/tmp/session06-pending.json";

const store = new PendingLoginStore();
const started = store.start(ISSUER_PUBLIC);

await writeFile(
  PENDING_FILE,
  `${JSON.stringify({ state: started.state, codeVerifier: started.codeVerifier }, null, 2)}\n`,
  "utf8",
);

console.log("次の URL をブラウザで開き、alice / alice-pass でログインしてください。");
console.log(started.authorizationUrl);
console.log("");
console.log("ログインすると http://localhost:3100/callback?... に転送されます。");
console.log("3100 番では誰も待っていないので画面はエラーになりますが、URL 欄に認可コードが入っています。");
console.log("その URL 全体をコピーして、次のコマンドに渡してください（引用符で囲むこと）。");
console.log('  docker compose exec app npx tsx src/session06/rp-q6-exchange.ts "<コピーした URL>"');
