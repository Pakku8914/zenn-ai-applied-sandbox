// セッション 16 の自己検証スクリプト。
// realm は 1 か所も書き換えません（鍵プロバイダを操作する実験は
// admin-key-rotation-experiment.ts に隔離してあります）。
// 期待値と一致しない項目が 1 つでもあれば非 0 で終了します。
import { rejectReason, verifyAccessToken } from "../session04/api-service-verify-jwt.js";
import { RefreshError, refreshAccessToken } from "../session07/rp-refresh.js";
import { introspect } from "../session10/api-service-introspect.js";
import { decodeJwtPart, loginHeadless } from "../test-helpers/headless-login.js";
import {
  REALM,
  activeSigningKeys,
  adminFetch,
  fetchAdminToken,
  fetchJwks,
  fetchManagedKeys,
  fetchPublishedKeys,
  kidsOf,
  signingKeys,
  verifyWithKeySet,
} from "./bookstore-keys.js";
import {
  BOOKSTORE_LIFESPANS,
  SAFE_RUNBOOK,
  canVerify,
  overlapWindowSeconds,
  propagationWaitSeconds,
  retirementWaitSeconds,
} from "./bookstore-rotation-plan.js";
import {
  JtiDenyList,
  revokeToken,
  strategiesWithin,
  worstCaseDelaySeconds,
} from "./api-service-revocation-policy.js";
import type { RevocationInput } from "./api-service-revocation-policy.js";
import {
  FORBIDDEN_KEYS,
  auditFromClaims,
  auditRejection,
  formatLine,
  looksLikeJwt,
  maskSecret,
  redact,
} from "./api-service-audit-log.js";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

console.log("=== セッション 16 の検証 ===\n");

// 1. 鍵には「公開されている姿」と「内部の姿」がある
console.log("1. 鍵の 2 つの姿");
const published = await fetchPublishedKeys();
const sigKeys = signingKeys(published);
check("JWKS に RS256 の署名鍵がある", sigKeys.length >= 1, true);
check("公開されている kid はすべて空でない", kidsOf(published).length, published.length);
check(
  "JWKS に対称鍵（HS512）は載らない",
  published.some((key) => key.alg === "HS512"),
  false,
);

const adminToken = await fetchAdminToken();
const managed = await fetchManagedKeys(adminToken);
const activeSig = activeSigningKeys(managed);
check(
  "内部では HS512 も ACTIVE な署名鍵",
  [...new Set(activeSig.map((key) => key.algorithm))].sort(),
  ["HS512", "RS256"],
);
check(
  "RS256 の ACTIVE な署名鍵は 1 本以上",
  activeSig.filter((key) => key.algorithm === "RS256").length >= 1,
  true,
);

// 監査ログは既定で何も記録していません。ここが今章の出発点です
const eventsRes = await adminFetch(adminToken, `/realms/${REALM}/events/config`);
check("監査イベントの設定を読める", eventsRes.status, 200);
const eventsConfig = (await eventsRes.json()) as {
  eventsEnabled?: unknown;
  adminEventsEnabled?: unknown;
  eventsListeners?: unknown;
};
check("利用者のイベントは既定で無効", eventsConfig.eventsEnabled, false);
check("管理操作のイベントは既定で無効", eventsConfig.adminEventsEnabled, false);
check("イベントの受け手", eventsConfig.eventsListeners, ["jboss-logging"]);

// 2. kid で鍵を選ぶ実装は、鍵が増えても変えなくてよい
console.log("\n2. kid で鍵を選ぶ");
const { tokens } = await loginHeadless();
const accessToken = tokens.access_token;
const header = decodeJwtPart<{ alg?: string; kid?: string; typ?: string }>(accessToken, 0);
check("JOSE ヘッダの alg", header.alg, "RS256");
check("JOSE ヘッダの typ", header.typ, "JWT");
check("ヘッダの kid が JWKS に載っている", kidsOf(sigKeys).includes(header.kid ?? ""), true);

// セッション 4 で書いた検証コードを、1 行も変えずに通します
const verified = await verifyAccessToken(accessToken);
check("セッション 4 の検証コードがそのまま通る", typeof verified.payload.sub, "string");

// 「いま取った鍵束」で検証する形にすると、鍵束を変数として比べられます
const jwksNow = await fetchJwks();
const localPayload = await verifyWithKeySet(accessToken, jwksNow);
check("いま取った鍵束で検証できる", localPayload.sub, verified.payload.sub);

/** ヘッダの kid だけを差し替えます（JWKS に無い鍵を指したトークンを作るため） */
function withKid(token: string, kid: string): string {
  const parts = token.split(".");
  const swapped = { ...decodeJwtPart<Record<string, unknown>>(token, 0), kid };
  const encoded = Buffer.from(JSON.stringify(swapped)).toString("base64url");
  return `${encoded}.${parts[1] ?? ""}.${parts[2] ?? ""}`;
}

let unknownKidReason = "落ちなかった";
try {
  await verifyWithKeySet(withKid(accessToken, "kid-that-does-not-exist"), jwksNow);
} catch (err) {
  unknownKidReason = rejectReason(err);
}
check("JWKS に無い kid を指したトークン", unknownKidReason, "署名に使われた鍵が JWKS に無い");

// 3. ローテーションの段階（鍵が並んでいる間は、どちらの kid でも検証できる）
console.log("\n3. ローテーションの段階");
const SINGLE = ["old-kid"];
const OVERLAP = ["new-kid", "old-kid"];
const RETIRED = ["new-kid"];
check("重なっている間は古いトークンも検証できる", canVerify(OVERLAP, "old-kid"), true);
check("重なっている間は新しいトークンも検証できる", canVerify(OVERLAP, "new-kid"), true);
check("足す前は新しいトークンが検証できない", canVerify(SINGLE, "new-kid"), false);
check("消した後は古いトークンが検証できない", canVerify(RETIRED, "old-kid"), false);
check("安全な手順は 5 手", SAFE_RUNBOOK.length, 5);
check("最初の 1 手は鍵を載せること", SAFE_RUNBOOK[0], "add-key");
check("最後の 1 手は古い鍵を外すこと", SAFE_RUNBOOK[4], "remove-old-key");

// 4. 猶予期間
console.log("\n4. 猶予期間の計算");
check("realm のアクセストークン寿命", BOOKSTORE_LIFESPANS.accessTokenLifespan, 300);
check("realm のリフレッシュトークン寿命", BOOKSTORE_LIFESPANS.refreshIdleTimeout, 1800);
check("時計のずれの許容", BOOKSTORE_LIFESPANS.clockToleranceSeconds, 5);
check("新しい kid が届くまでの待ち", propagationWaitSeconds(BOOKSTORE_LIFESPANS), 35);
check("古いトークンが消えるまでの待ち", retirementWaitSeconds(BOOKSTORE_LIFESPANS), 1805);
check("2 本を並べておく合計時間", overlapWindowSeconds(BOOKSTORE_LIFESPANS), 1840);
check(
  "アクセストークンの寿命だけで決めると足りない",
  retirementWaitSeconds({ ...BOOKSTORE_LIFESPANS, refreshIdleTimeout: 0 }),
  305,
);

// 5. 失効の 3 つの選択肢
console.log("\n5. 失効の選択肢");
const REVOCATION: RevocationInput = {
  accessTokenLifespan: 300,
  blacklistPropagationSeconds: 10,
  introspectionCacheSeconds: 0,
};
check("寿命で押し切るときの最大の遅れ", worstCaseDelaySeconds("short-lifetime", REVOCATION), 300);
check("ブロックリストの最大の遅れ", worstCaseDelaySeconds("blacklist", REVOCATION), 10);
check("イントロスペクションの最大の遅れ", worstCaseDelaySeconds("introspection", REVOCATION), 0);
check("10 分以内でよいなら 3 方式すべてで足りる", strategiesWithin(600, REVOCATION), [
  "short-lifetime",
  "blacklist",
  "introspection",
]);
check("30 秒以内なら寿命では足りない", strategiesWithin(30, REVOCATION), ["blacklist", "introspection"]);
check("5 秒以内だと聞くしかない", strategiesWithin(5, REVOCATION), ["introspection"]);
check(
  "問い合わせ結果をキャッシュすると、聞いても間に合わなくなる",
  strategiesWithin(5, { ...REVOCATION, introspectionCacheSeconds: 60 }),
  [],
);

const deny = new JtiDenyList();
deny.revoke("jti-a", 1_000);
deny.revoke("jti-b", 2_000);
check("失効を覚えている件数", deny.size, 2);
check("失効したトークン", deny.isRevoked("jti-a"), true);
check("知らないトークンは失効していない", deny.isRevoked("jti-z"), false);
check("exp を過ぎた記録は捨てられる", deny.purgeExpired(1_500), 1);
check("捨てた後に残る件数", deny.size, 1);
check("まだ生きている記録は残る", deny.isRevoked("jti-b"), true);

// 6. 失効を実際に頼んでみる（realm の設定は変えません）
console.log("\n6. 失効の実測（RFC 7009）");
const beforeRevoke = await introspect(accessToken);
check("失効前はアクセストークンが有効", beforeRevoke.active, true);

const revoked = await revokeToken(tokens.refresh_token ?? "", "refresh_token");
check("失効の応答", revoked.status, 200);
check("失効の応答の本文は空", revoked.body, "");

const afterRevoke = await introspect(accessToken);
check("失効後は認可サーバーが無効と答える", afterRevoke.active, false);

// ここが「JWT は自己完結だから失効させにくい」の実証です
const stillValid = await verifyWithKeySet(accessToken, jwksNow);
check("失効後もローカル検証は通ってしまう", stillValid.sub, verified.payload.sub);

let refreshFailure = { status: 0, error: "", description: "" };
try {
  await refreshAccessToken({ refreshToken: tokens.refresh_token ?? "" });
} catch (err) {
  if (!(err instanceof RefreshError)) throw err;
  refreshFailure = { status: err.status, error: err.error, description: err.errorDescription };
}
check("失効後のリフレッシュ", refreshFailure, {
  status: 400,
  error: "invalid_grant",
  description: "Session not active",
});

// 7. 監査ログ
console.log("\n7. 監査ログ");
const FIXED_NOW = new Date("2026-09-08T00:00:00.000Z");
const event = auditFromClaims(
  verified.payload,
  { event: "authz.denied", decision: "deny", reason: "staff ロールが必要" },
  { now: FIXED_NOW, ip: "192.0.2.10" },
);
check("時刻は ISO 8601", event.at, "2026-09-08T00:00:00.000Z");
check("誰かは sub で記録する", event.sub, verified.payload.sub);
check("トークン 1 本の識別子", typeof event.jti === "string" && event.jti !== "", true);
check("どのクライアント経由か", event.clientId, "web-app");
check("宛先は配列にそろえる", event.audience, ["api-service"]);
check("判定結果", event.decision, "deny");
check(
  "記録する項目は 10 個だけ",
  Object.keys(event).sort(),
  ["at", "audience", "clientId", "decision", "event", "ip", "iss", "jti", "reason", "sub"],
);
check(
  "1 行 JSON にトークンは出てこない",
  formatLine(event).includes(accessToken.slice(0, 24)),
  false,
);

const rejection = auditRejection("署名が鍵と一致しない", { now: FIXED_NOW, ip: "192.0.2.99" });
check("検証に失敗したら誰かは書かない", rejection.sub, "");
check("失敗の記録も残す", rejection.event, "token.rejected");

check("禁止キーは 11 個", FORBIDDEN_KEYS.length, 11);
check("秘密は長さだけ残す", maskSecret("abcdefgh"), "<redacted> len=8");
check("JWT らしい値を見分ける", looksLikeJwt(accessToken), true);
check("Bearer 付きでも見分ける", looksLikeJwt(`Bearer ${accessToken}`), true);
check("ふつうの文字列は誤検知しない", looksLikeJwt("order-1001 は取り消し済み"), false);

const dangerous = {
  sub: "alice-sub",
  reason: "staff ロールが必要",
  // うっかり渡してしまいがちな値
  authorization: `Bearer ${accessToken}`,
  refresh_token: "e30.e30.sig",
  code_verifier: "0123456789abcdef",
  password: "alice-pass",
  // キー名では分からないが、値が JWT になっている
  note: accessToken,
};
const safe = redact(dangerous);
check("残す項目はそのまま", safe["sub"], "alice-sub");
check("理由は残す", safe["reason"], "staff ロールが必要");
check("Authorization ヘッダは落とす", safe["authorization"], maskSecret(`Bearer ${accessToken}`));
check("リフレッシュトークンは落とす", safe["refresh_token"], "<redacted> len=11");
check("code_verifier は落とす", safe["code_verifier"], "<redacted> len=16");
check("パスワードは落とす", safe["password"], "<redacted> len=10");
check("キー名で分からない秘密も値で落とす", safe["note"], maskSecret(accessToken));
check(
  "整形した 1 行にトークンの断片が残らない",
  JSON.stringify(safe).includes(accessToken.slice(0, 24)),
  false,
);

console.log(
  failures === 0 ? "\nセッション 16 のすべての検証に成功しました。" : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
