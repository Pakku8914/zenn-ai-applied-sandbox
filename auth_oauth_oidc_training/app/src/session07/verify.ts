// セッション 7 の自己検証スクリプト。
// 期待値と一致しない項目が 1 つでもあれば非 0 で終了するため、人が出力を読んで判断する必要はありません。
// realm の設定は一切書き換えません（設定を変える実験は admin-refresh-rotation-experiment.ts が担当）。
// ここで「旧リフレッシュトークンの再利用が成功する」「offline_access が拒否される」を確かめているので、
// 実験スクリプトが設定を戻し忘れた場合はこの検証が落ちます。
import { ACCESS_TOKEN_LIFESPAN, ISSUER_INTERNAL, REFRESH_IDLE_TIMEOUT } from "./bookstore-tokens.js";
import { inspectClientCredentials } from "./batch-worker-check.js";
import { RefreshError, ensureFreshAccessToken, refreshAccessToken } from "./rp-refresh.js";
import { buildRefreshDemo } from "./rp-refresh-demo.js";
import {
  FEATURE_SCOPES,
  missingScopes,
  normalizeScope,
  parseScope,
  requiredScopesFor,
  sameScopeSet,
  scopeRequestFor,
} from "./rp-scope.js";
import { canRefresh, needsRefresh, peekClaims, secondsLeft, toTokenSet } from "./rp-token-store.js";
import { loginHeadless, refreshTokens } from "../test-helpers/headless-login.js";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

/** 検証用ヘルパー経由のログインが失敗したときに、認可サーバーの応答を取り出します */
async function captureLoginFailure(
  run: () => Promise<unknown>,
): Promise<{ status: number; error: string; description: string }> {
  try {
    await run();
    return { status: 0, error: "成功してしまいました", description: "" };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    const matched = /トークン交換が (\d+) で失敗しました: (.*)$/s.exec(message);
    if (matched === null) return { status: -1, error: message, description: "" };
    const body = JSON.parse(matched[2] ?? "{}") as { error?: string; error_description?: string };
    return {
      status: Number(matched[1] ?? "0"),
      error: body.error ?? "",
      description: body.error_description ?? "",
    };
  }
}

const TOKEN_KEYS = [
  "access_token",
  "expires_in",
  "id_token",
  "not-before-policy",
  "refresh_expires_in",
  "refresh_token",
  "scope",
  "session_state",
  "token_type",
];

// ----------------------------------------------------------------------------
// 1. 期限の持ち方（時刻を固定した純粋な計算なので、いつ実行しても同じ結果になる）
// ----------------------------------------------------------------------------
const t0 = Date.parse("2026-09-08T09:00:00Z");
const sample = toTokenSet(
  {
    access_token: "access-1",
    refresh_token: "refresh-1",
    expires_in: ACCESS_TOKEN_LIFESPAN,
    refresh_expires_in: REFRESH_IDLE_TIMEOUT,
    scope: "openid email profile",
  },
  { now: t0 },
);
check("access の期限は受け取り時刻 + 300 秒", sample.accessExpiresAt, t0 + 300_000);
check("refresh の期限は受け取り時刻 + 1800 秒", sample.refreshExpiresAt, t0 + 1_800_000);
check("受け取った直後の残り秒数", secondsLeft(sample.accessExpiresAt, t0), 300);
check("受け取った直後は更新不要", needsRefresh(sample, t0), false);
check("期限の 31 秒前ではまだ更新しない", needsRefresh(sample, sample.accessExpiresAt - 31_000), false);
check("期限の 30 秒前になったら更新する", needsRefresh(sample, sample.accessExpiresAt - 30_000), true);
check("期限を過ぎていれば当然更新する", needsRefresh(sample, sample.accessExpiresAt + 1), true);
check("前倒しを 0 秒にすると期限まで更新しない", needsRefresh(sample, sample.accessExpiresAt - 1, 0), false);
check("refresh の期限内ならリフレッシュできる", canRefresh(sample, sample.refreshExpiresAt - 1), true);
check("refresh の期限が来たらリフレッシュできない", canRefresh(sample, sample.refreshExpiresAt), false);

// refresh_token が返らなかったときは手元のものを引き継ぐ（RFC 6749 §6）
const carried = toTokenSet(
  { access_token: "access-2", expires_in: ACCESS_TOKEN_LIFESPAN },
  { now: t0 + 10_000, previous: sample },
);
check("refresh_token が無い応答では手元の値を引き継ぐ", carried.refreshToken, "refresh-1");
check("refresh_expires_in が無い応答では期限も引き継ぐ", carried.refreshExpiresAt, sample.refreshExpiresAt);
check("scope も引き継ぐ", carried.scope, "openid email profile");
check(
  "expires_in をミリ秒と取り違えると即座に期限切れになる",
  secondsLeft(toTokenSet({ access_token: "a", expires_in: 0.3 }, { now: t0 }).accessExpiresAt, t0),
  0,
);

// ----------------------------------------------------------------------------
// 2. スコープの扱い（集合として比べる）
// ----------------------------------------------------------------------------
check("スコープは空白区切りで分解できる", parseScope("openid email profile"), [
  "openid",
  "email",
  "profile",
]);
check("空文字は空の配列になる", parseScope(""), []);
check("undefined でも落ちない", parseScope(undefined), []);
check("並べ替えた形に正規化できる", normalizeScope("openid profile email"), "email openid profile");
check("並び順が違っても同じ集合", sameScopeSet("openid profile email", "openid email profile"), true);
check("要素が違えば別の集合", sameScopeSet("openid profile", "openid profile email"), false);
check("足りないスコープを列挙できる", missingScopes("openid orders:read", ["orders:read", "orders:write"]), [
  "orders:write",
]);
check("足りていれば空配列", missingScopes("openid orders:read", ["orders:read"]), []);
check("一覧を見るだけならスコープは不要", requiredScopesFor("本の一覧を見る"), []);
check("注文するには書き込みのスコープが必要", requiredScopesFor("注文する"), ["orders:write"]);
check(
  "使う機能から要求するスコープを組み立てられる",
  scopeRequestFor(["自分の注文を見る", "注文する"]),
  "openid orders:read orders:write",
);
check(
  "設計した機能の数とスコープの数",
  [Object.keys(FEATURE_SCOPES).length, new Set(Object.values(FEATURE_SCOPES).flat()).size],
  [5, 4],
);

// ----------------------------------------------------------------------------
// 3. リフレッシュの実測（ログイン → 更新 → 旧トークンの再利用）
// ----------------------------------------------------------------------------
const login = await loginHeadless();
const receivedAt = Date.now();
const first = toTokenSet(login.tokens, { now: receivedAt });
check("ログイン時の expires_in", login.tokens.expires_in, ACCESS_TOKEN_LIFESPAN);
check("ログイン時の refresh_expires_in", login.tokens.refresh_expires_in, REFRESH_IDLE_TIMEOUT);

const firstRefreshClaims = peekClaims<Record<string, unknown>>(first.refreshToken);
check("リフレッシュトークンのクレーム（並べ替え）", Object.keys(firstRefreshClaims).sort(), [
  "aud",
  "aud_x",
  "azp",
  "exp",
  "iat",
  "iss",
  "jti",
  "prov",
  "scope",
  "sid",
  "sub",
  "typ",
]);
check("リフレッシュトークンの typ", firstRefreshClaims["typ"], "Refresh");
check("リフレッシュトークンの iss", firstRefreshClaims["iss"], ISSUER_INTERNAL);
check("リフレッシュトークンの azp", firstRefreshClaims["azp"], "web-app");

const renewed = await refreshAccessToken({ refreshToken: first.refreshToken });
const second = toTokenSet(renewed, { previous: first });
check("リフレッシュの応答のキー（並べ替え）", Object.keys(renewed).sort(), TOKEN_KEYS);
check("リフレッシュ後の expires_in", renewed.expires_in, ACCESS_TOKEN_LIFESPAN);
check("リフレッシュ後の refresh_expires_in", renewed.refresh_expires_in, REFRESH_IDLE_TIMEOUT);
check("新しい refresh_token が返る", renewed.refresh_token !== undefined, true);

const secondRefreshClaims = peekClaims<Record<string, unknown>>(second.refreshToken);
check(
  "リフレッシュトークンの jti は変わる",
  secondRefreshClaims["jti"] !== firstRefreshClaims["jti"],
  true,
);
check("利用者（sub）は変わらない", secondRefreshClaims["sub"], firstRefreshClaims["sub"]);
check("ログインのセッション（sid）は変わらない", secondRefreshClaims["sid"], firstRefreshClaims["sid"]);
check("付与されたスコープは同じ集合", sameScopeSet(first.scope, second.scope), true);
check("アクセストークンは別物になる", first.accessToken !== second.accessToken, true);

// 旧リフレッシュトークンの再利用。既定の realm では通ってしまう（＝ローテーションしていない）
const reused = await refreshAccessToken({ refreshToken: first.refreshToken });
check("旧リフレッシュトークンの再利用は成功してしまう", reused.token_type, "Bearer");
check("再利用で得たアクセストークンの寿命", reused.expires_in, ACCESS_TOKEN_LIFESPAN);

// 検証用ヘルパーのリフレッシュでも同じ形の応答になる（実装の答え合わせ）
const viaHelper = await refreshTokens(second.refreshToken);
check("検証用ヘルパーのリフレッシュの応答のキー", Object.keys(viaHelper).sort(), TOKEN_KEYS);

// API を呼ぶ直前に通す関数（期限前は何もせず、期限が来たら取り直す）
const kept = await ensureFreshAccessToken(second, { now: Date.now() });
check("期限前は更新しない", kept.refreshed, false);
const forced = await ensureFreshAccessToken(second, { now: second.accessExpiresAt });
check("期限が来たら更新する", forced.refreshed, true);
check("更新後のアクセストークンは別物になる", forced.set.accessToken !== second.accessToken, true);

// 使えないリフレッシュトークンを渡したとき
let refreshFailure = { status: -1, error: "", description: "" };
try {
  await refreshAccessToken({ refreshToken: "not-a-token" });
} catch (err) {
  if (!(err instanceof RefreshError)) throw err;
  refreshFailure = { status: err.status, error: err.error, description: err.errorDescription };
}
check("壊れたリフレッシュトークンの status", refreshFailure.status, 400);
check("壊れたリフレッシュトークンの error", refreshFailure.error, "invalid_grant");

// リフレッシュトークンも切れている状態では、リフレッシュを試さず再ログインを促す
let deadMessage = "";
try {
  await ensureFreshAccessToken(first, { now: first.refreshExpiresAt });
} catch (err) {
  deadMessage = err instanceof Error ? err.message : String(err);
}
check(
  "refresh も切れていたら再ログインを促す",
  deadMessage,
  "リフレッシュトークンも使えません。もう一度ログインしてもらってください",
);

// ----------------------------------------------------------------------------
// 4. offline_access は既定では使えない（realm の状態が元に戻っていることの確認でもある）
// ----------------------------------------------------------------------------
const offline = await captureLoginFailure(() =>
  loginHeadless({ scope: "openid profile email offline_access" }),
);
check("offline_access を要求したときの status", offline.status, 400);
check("offline_access を要求したときの error", offline.error, "not_allowed");
check(
  "offline_access を要求したときの error_description",
  offline.description,
  "Offline tokens not allowed for the user or client",
);

// ----------------------------------------------------------------------------
// 5. 利用者が居ないフローにはリフレッシュトークンが無い
// ----------------------------------------------------------------------------
const batch = await inspectClientCredentials();
check("Client Credentials の応答のキー（並べ替え）", batch.keys, [
  "access_token",
  "expires_in",
  "not-before-policy",
  "refresh_expires_in",
  "scope",
  "token_type",
]);
check("Client Credentials に refresh_token は無い", batch.hasRefreshToken, false);
check("Client Credentials の expires_in", batch.expiresIn, ACCESS_TOKEN_LIFESPAN);
check("Client Credentials の scope", batch.scope, "email profile");

// ----------------------------------------------------------------------------
// 6. 本文のデモの出力（章に載せた行と 1 字も違わないことを確かめる）
// ----------------------------------------------------------------------------
check("本文のデモの出力", await buildRefreshDemo(), [
  "=== リフレッシュの前後で何が変わるか ===",
  "ログイン直後: access 残り 300 秒 / refresh 残り 1800 秒",
  "すぐに更新が必要か: false",
  "期限の 20 秒前なら更新が必要か: true",
  "更新後の access / refresh の有効期間: 300 秒 / 1800 秒",
  "リフレッシュトークンの typ: Refresh",
  "jti は変わった: true",
  "sid は変わらない: true",
  "アクセストークンは別物になった: true",
  "付与されたスコープは同じ集合: true",
]);

console.log(
  failures === 0
    ? "\nセッション 7 のすべての検証に成功しました。"
    : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
