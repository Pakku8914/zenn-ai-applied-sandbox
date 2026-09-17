// セッション 8 の自己検証スクリプト。
// 期待値と一致しない項目が 1 つでもあれば非 0 で終了するため、人が出力を読んで判断する必要はありません。
// realm の設定は一切書き換えません（利用者の属性も変更しません）。
import { API_AUDIENCE, CLIENT_ID, DISCOVERY_URL, ISSUER, USERINFO_ENDPOINT } from "./bookstore-oidc.js";
import { IdTokenError, verifyIdToken, verifyWithAudience } from "./rp-verify-id-token.js";
import { PendingLoginStore } from "./rp-pending-login.js";
import { badLoginCheck, fetchMachineTokens, goodLoginCheck } from "./rp-login-check.js";
import { fetchUserInfo } from "./rp-userinfo.js";
import { decodeJwtPart, loginHeadless } from "../test-helpers/headless-login.js";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

/** 非同期処理が拒否した理由を取り出します（IdTokenError なら reason をそのまま返します） */
async function reasonOf(run: () => Promise<unknown>): Promise<string> {
  try {
    await run();
    return "拒否されませんでした";
  } catch (err) {
    if (err instanceof IdTokenError) return err.reason;
    return err instanceof Error ? err.message : String(err);
  }
}

/** 同期処理が投げた例外のメッセージを返します */
function rejectedBy(run: () => unknown): string {
  try {
    run();
    return "例外になりませんでした";
  } catch (err) {
    return err instanceof Error ? err.message : String(err);
  }
}

// 1. discovery に UserInfo エンドポイントがある（OIDC が足した層の目印）
const discovery = (await (await fetch(DISCOVERY_URL)).json()) as Record<string, unknown>;
check("discovery の userinfo_endpoint", discovery["userinfo_endpoint"], USERINFO_ENDPOINT);

// 2. 認可コードフローを完走して ID トークンを受け取る
const browser = await loginHeadless(); // 既定は alice
const idToken = browser.tokens.id_token ?? "";
check("id_token が返っている", idToken !== "", true);
check("応答された scope", browser.tokens.scope, "openid email profile");
check("ID トークンの署名アルゴリズム", decodeJwtPart(idToken, 0)["alg"], "RS256");

const idClaims = decodeJwtPart(idToken, 1);
const accessClaims = decodeJwtPart(browser.tokens.access_token, 1);
const idNames = Object.keys(idClaims).sort();
const accessNames = Object.keys(accessClaims).sort();

check("ID トークンのクレーム（並べ替え）", idNames, [
  "acr",
  "at_hash",
  "aud",
  "auth_time",
  "azp",
  "email",
  "email_verified",
  "exp",
  "family_name",
  "given_name",
  "iat",
  "iss",
  "jti",
  "name",
  "nonce",
  "preferred_username",
  "sid",
  "sub",
  "typ",
]);
check("ID トークンのクレーム数", idNames.length, 19);
check("アクセストークンのクレーム数", accessNames.length, 20);
check(
  "ID トークンだけにあるクレーム",
  idNames.filter((name) => !accessNames.includes(name)),
  ["at_hash", "nonce"],
);
check(
  "アクセストークンだけにあるクレーム",
  accessNames.filter((name) => !idNames.includes(name)),
  ["allowed-origins", "realm_access", "scope"],
);
check("アクセストークンに nbf は無い", "nbf" in accessClaims, false);

// 3. 宛名（aud）の非対称。ここが本章の核心
check("ID トークンの aud", idClaims["aud"], CLIENT_ID);
check("ID トークンの aud は文字列", typeof idClaims["aud"], "string");
check("アクセストークンの aud", accessClaims["aud"], API_AUDIENCE);
check("ID トークンの azp", idClaims["azp"], CLIENT_ID);
check("アクセストークンの azp", accessClaims["azp"], CLIENT_ID);
check("ID トークンの iss", idClaims["iss"], ISSUER);
check("ID トークンの exp - iat", Number(idClaims["exp"]) - Number(idClaims["iat"]), 300);
check("ID トークンには権限（realm_access）が載らない", "realm_access" in idClaims, false);

// 4. nonce は ID トークンにだけ返ってくる
check("ID トークンの nonce は送った値と同じ", idClaims["nonce"], browser.nonce);
check("アクセストークンに nonce は無い", "nonce" in accessClaims, false);
check("at_hash は ID トークンにある", typeof idClaims["at_hash"], "string");

// 5. ID トークンの検証（署名・iss・aud・時刻・nonce・azp）
const identity = await verifyIdToken({ idToken, expectedNonce: browser.nonce });
check("sub が取れている", identity.subject !== "", true);
check("preferred_username", identity.username, "alice");
check("name", identity.name, "Alice Customer");
check("email", identity.email, "alice@example.com");
check("email_verified", identity.emailVerified, true);
check("auth_time が入っている", identity.authTime > 0, true);
check("sid が入っている", identity.sessionId !== "", true);

check(
  "nonce が違えば拒否する",
  await reasonOf(() => verifyIdToken({ idToken, expectedNonce: `${browser.nonce}x` })),
  "nonce が一致しない（使い回しの可能性）",
);
check(
  "保存していた nonce が空なら拒否する",
  await reasonOf(() => verifyIdToken({ idToken, expectedNonce: "" })),
  "保存していた nonce が無い（照合できない）",
);
check(
  "アクセストークンを ID トークンとして渡すと拒否する",
  await reasonOf(() => verifyIdToken({ idToken: browser.tokens.access_token, expectedNonce: browser.nonce })),
  "aud が期待した値ではない",
);
check(
  "壊れた文字列は JWT として拒否する",
  await reasonOf(() => verifyIdToken({ idToken: "not-a-jwt", expectedNonce: browser.nonce })),
  "JWT の形式ではない",
);

// 6. 宛名の検証マトリクス（2 種類のトークン × 2 つの宛先）
check("ID トークンを web-app 宛てとして検証", await verifyWithAudience(idToken, CLIENT_ID), "通った");
check(
  "ID トークンを api-service 宛てとして検証",
  await verifyWithAudience(idToken, API_AUDIENCE),
  "aud が期待した値ではない",
);
check(
  "アクセストークンを web-app 宛てとして検証",
  await verifyWithAudience(browser.tokens.access_token, CLIENT_ID),
  "aud が期待した値ではない",
);
check(
  "アクセストークンを api-service 宛てとして検証",
  await verifyWithAudience(browser.tokens.access_token, API_AUDIENCE),
  "通った",
);

// 7. state と nonce を覚えておく入れ物
const store = new PendingLoginStore();
const pending = store.start("code-verifier-1");
check("state と nonce は別の値", pending.state === pending.nonce, false);
check("nonce の長さ", pending.nonce.length, 22);
check("覚えている件数", store.size, 1);
check("state で取り出せる", store.consume(pending.state).nonce, pending.nonce);
check("取り出したら記録は残らない", store.size, 0);
check(
  "同じ state は 2 回使えない",
  rejectedBy(() => store.consume(pending.state)),
  "state が一致しません（自分が始めたログインではありません）",
);
const stale = store.start("code-verifier-2", 0);
check(
  "古すぎる記録は拒否する",
  rejectedBy(() => store.consume(stale.state, 10 * 60 * 1000 + 1)),
  "ログインの開始から時間が経ちすぎています（やり直してください）",
);

// 8. セッション 5 の破綻が ID トークンでは成立しないこと
const machine = await fetchMachineTokens();
const machineAccessToken = typeof machine["access_token"] === "string" ? machine["access_token"] : "";
check("機械のトークンレスポンスのキー数", Object.keys(machine).length, 6);
check("機械のトークンレスポンスに id_token は無い", "id_token" in machine, false);
check("Bad: alice のアクセストークンでログイン判定", await badLoginCheck(browser.tokens.access_token), {
  loggedIn: true,
  user: "alice",
});
check(
  "Bad: 機械のアクセストークンでもログイン済みになってしまう",
  (await badLoginCheck(machineAccessToken)).loggedIn,
  true,
);
const goodAlice = await goodLoginCheck({ idToken, expectedNonce: browser.nonce });
check("Good: alice はログイン済み", goodAlice.loggedIn, true);
check("Good: 取り出せた利用者", goodAlice.loggedIn ? goodAlice.user.username : "", "alice");
const goodMachine = await goodLoginCheck({ idToken: undefined, expectedNonce: browser.nonce });
check("Good: 機械は未ログイン", goodMachine.loggedIn, false);
check(
  "Good: 未ログインの理由",
  goodMachine.loggedIn ? "" : goodMachine.reason,
  "ID トークンが無い（認証イベントが存在しない）",
);

// 9. UserInfo（いまの属性）と ID トークン（認証イベントのスナップショット）
const userInfo = await fetchUserInfo(browser.tokens.access_token);
check("UserInfo の HTTP ステータス", userInfo.status, 200);
check("UserInfo の sub は ID トークンと一致する", userInfo.claims["sub"], identity.subject);
const SHARED = ["email", "email_verified", "family_name", "given_name", "name", "preferred_username", "sub"];
check(
  "UserInfo に属性がそろっている",
  SHARED.filter((name) => !(name in userInfo.claims)),
  [],
);
check(
  "UserInfo の属性は ID トークンと同じ値",
  SHARED.filter((name) => JSON.stringify(userInfo.claims[name]) !== JSON.stringify(idClaims[name])),
  [],
);
check(
  "UserInfo にトークン固有のクレームは無い",
  ["aud", "at_hash", "exp", "nonce"].filter((name) => name in userInfo.claims),
  [],
);

// 10. 別の利用者でも同じ構造になる（権限は ID トークンに載らない）
const bobLogin = await loginHeadless({ username: "bob", password: "bob-pass" });
const bobIdentity = await verifyIdToken({
  idToken: bobLogin.tokens.id_token ?? "",
  expectedNonce: bobLogin.nonce,
});
check("bob の preferred_username", bobIdentity.username, "bob");
check("bob の name", bobIdentity.name, "Bob Staff");
check("bob の sub は alice と別", bobIdentity.subject === identity.subject, false);
const bobIdClaims = decodeJwtPart(bobLogin.tokens.id_token ?? "", 1);
check("bob の ID トークンにもロールは載らない", "realm_access" in bobIdClaims, false);
const bobAccessClaims = decodeJwtPart<{ realm_access?: { roles?: string[] } }>(
  bobLogin.tokens.access_token,
  1,
);
check("bob のロールはアクセストークンに載る", (bobAccessClaims.realm_access?.roles ?? []).sort(), [
  "customer",
  "staff",
]);

console.log(
  failures === 0
    ? "\nセッション 8 のすべての検証に成功しました。"
    : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
