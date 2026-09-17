// セッションの一生（発行 → 更新 → ログインで再生成 → ログアウトで破棄）を追いかけます。
// 実行: docker compose exec app npx tsx src/session03/web-app-session-trace.ts
import { attribute, call, cookieHeader, hasFlag, parseSetCookie } from "./web-app-cookie-tools.js";
import type { CallResult } from "./web-app-cookie-tools.js";
import { SESSION_COOKIE, createWebApp } from "./web-app-session-login.js";

const show = (title: string, result: CallResult): void => {
  console.log(`${title} → ${result.status} ${result.body}`);
};
const detail = (text: string): void => {
  console.log(`    ${text}`);
};

const app = await createWebApp();
console.log("=== セッションの一生を追いかける ===");

// [1] Cookie を持たずにカートを見る → 匿名セッションが発行される
const step1 = await call(app, "/cart");
show("[1] GET /cart（Cookie なし）", step1);
const issued = parseSetCookie(step1.setCookie);
detail(
  `sid: ${issued?.value.length ?? 0}文字` +
    ` / HttpOnly=${issued !== undefined && hasFlag(issued, "HttpOnly")}` +
    ` / SameSite=${issued === undefined ? "-" : attribute(issued, "SameSite")}` +
    ` / Path=${issued === undefined ? "-" : attribute(issued, "Path")}` +
    ` / Secure=${issued !== undefined && hasFlag(issued, "Secure")}`,
);
const beforeHeader = cookieHeader(SESSION_COOKIE, issued?.value ?? "");

// [2] 同じ Cookie を付けて本を 1 冊カゴに入れる → サーバー側の状態が育つ
show(
  "[2] POST /cart（同じ Cookie で本を 1 冊入れる）",
  await call(app, "/cart", {
    method: "POST",
    cookie: beforeHeader,
    form: { title: "Clean Architecture" },
  }),
);

// [3] ログインする → セッション ID が再生成され、カートは引き継がれる
const step3 = await call(app, "/login", {
  method: "POST",
  cookie: beforeHeader,
  form: { username: "alice", password: "alice-pass" },
});
show("[3] POST /login（alice / 正しいパスワード）", step3);
const afterHeader = cookieHeader(SESSION_COOKIE, parseSetCookie(step3.setCookie)?.value ?? "");
detail(
  `セッション ID の再生成: ${afterHeader !== beforeHeader}` +
    ` / カートの引き継ぎ: ${step3.body.includes("Clean Architecture")}`,
);

// [4] 新しい Cookie なら本人情報が取れる
show("[4] GET /me（ログイン後の新しい Cookie）", await call(app, "/me", { cookie: afterHeader }));

// [5] 古い Cookie はもう通らない（攻撃者に仕込まれていても無効）
show("[5] GET /me（ログイン前の古い Cookie）", await call(app, "/me", { cookie: beforeHeader }));

// [6] ログアウト → サーバー側のレコードを消し、Cookie も空にする
const step6 = await call(app, "/logout", { method: "POST", cookie: afterHeader });
show("[6] POST /logout", step6);
detail(`Set-Cookie の値の長さ: ${parseSetCookie(step6.setCookie)?.value.length ?? -1}`);

// [7] ログアウト後は同じ Cookie でも通らない
show("[7] GET /me（ログアウト後の Cookie）", await call(app, "/me", { cookie: afterHeader }));
