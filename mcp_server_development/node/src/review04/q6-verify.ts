/**
 * 横断復習4 問題6 ―― HS256 アクセストークンの検証と 10 ケースの固定
 *
 * 実行: docker compose exec node npx tsx src/review04/q6-verify.ts
 *
 * 検証の順序（順序に理由があります）
 *   ① Authorization ヘッダーの形式（Bearer か）
 *   ② 3 パートに分解できるか
 *   ③ alg が許可リストに入っているか（受け取る側がアルゴリズムを決める）
 *   ④ 署名（★ クレームを読むより先に。中身は「本物と分かってから」読む）
 *   ⑤ iss（発行者）の完全一致
 *   ⑥ exp（時刻。時計ずれを許容する）
 *   ⑦ aud（★ このリソース向けのトークンか）
 */
import { base64UrlEncode, decodeJwt, mintToken, signatureMatches } from "./hs256.js";

export type VerifyFailure =
  | "missing_token"
  | "malformed_header"
  | "malformed_token"
  | "unsupported_alg"
  | "bad_signature"
  | "issuer_mismatch"
  | "expired"
  | "audience_mismatch";

export type VerifyOutcome =
  | { ok: true; subject: string; scopes: string[]; expiresAt: number }
  | { ok: false; reason: VerifyFailure };

export type VerifyOptions = {
  secret: string;
  issuer: string;
  /** このリソースの識別子。トークンの aud と完全一致を要求する */
  audience: string;
  /** 基準時刻（UNIX 秒）。テストから固定値を渡せるようにする */
  now: number;
  clockSkewSeconds?: number;
};

/** aud は文字列でも配列でもありうる。どちらでも「完全一致が 1 つあるか」で判定する */
export function audienceMatches(aud: unknown, expected: string): boolean {
  if (typeof aud === "string") return aud === expected;
  if (Array.isArray(aud)) return aud.some((value) => value === expected);
  return false;
}

export function verifyAccessToken(
  authorization: string | undefined,
  options: VerifyOptions,
): VerifyOutcome {
  const skew = options.clockSkewSeconds ?? 60;

  // ① ヘッダーの形式。Bearer スキームは大文字小文字を区別しない
  if (authorization === undefined || authorization.trim() === "") {
    return { ok: false, reason: "missing_token" };
  }
  const token = /^Bearer +([A-Za-z0-9._-]+)$/i.exec(authorization.trim())?.[1];
  if (token === undefined) return { ok: false, reason: "malformed_header" };

  // ② 分解。ここでは検証していない（decode は誰でもできる）
  const decoded = decodeJwt(token);
  if (decoded === undefined) return { ok: false, reason: "malformed_token" };

  // ③ alg は許可リスト方式。トークンの言い値を信じると署名検証が無意味になる
  if (decoded.header["alg"] !== "HS256") return { ok: false, reason: "unsupported_alg" };

  // ④ 署名。ここを通るまでクレームは読まない・ログにも出さない
  if (!signatureMatches(decoded, options.secret)) return { ok: false, reason: "bad_signature" };

  const claims = decoded.payload;
  // ⑤ 発行者。署名が正しくても、信頼していない発行者のトークンは受け取らない
  if (claims["iss"] !== options.issuer) return { ok: false, reason: "issuer_mismatch" };

  // ⑥ 時刻。時計ずれを許容しないと、正しいトークンが弾かれる事故が起きる
  const exp = claims["exp"];
  if (typeof exp !== "number" || exp + skew < options.now) {
    return { ok: false, reason: "expired" };
  }

  // ⑦ オーディエンス。「このトークンは私宛か」
  if (!audienceMatches(claims["aud"], options.audience)) {
    return { ok: false, reason: "audience_mismatch" };
  }

  const sub = claims["sub"];
  const scope = claims["scope"];
  return {
    ok: true,
    subject: typeof sub === "string" ? sub : "(unknown)",
    // scope は「空白区切りの 1 本の文字列」。配列ではない（RFC 6749）
    scopes: typeof scope === "string" ? scope.split(" ").filter((value) => value.length > 0) : [],
    expiresAt: exp,
  };
}

// ── 検証 ────────────────────────────────────────────────────────────────
const SECRET = "review04-shared-secret-0123456789abcdef";
const ISSUER = "http://127.0.0.1:9100";
const AUDIENCE = "https://workflow.example.internal/mcp";
const NOW = 1_777_000_000;
const SCOPE = "requests:read requests:approve";

const options: VerifyOptions = {
  secret: SECRET,
  issuer: ISSUER,
  audience: AUDIENCE,
  now: NOW,
};

function mint(overrides: Partial<Parameters<typeof mintToken>[0]> = {}): string {
  return mintToken({
    secret: SECRET,
    issuer: ISSUER,
    audience: AUDIENCE,
    subject: "u-001",
    scope: SCOPE,
    now: NOW,
    ...overrides,
  });
}

/** 署名の最後の 1 文字を必ず別の文字に置き換える */
function tamper(token: string): string {
  const last = token.at(-1) ?? "A";
  return `${token.slice(0, -1)}${last === "A" ? "B" : "A"}`;
}

/** alg を none にし、3 パート目を空にしたトークンを組み立てる */
function algNoneToken(): string {
  const header = base64UrlEncode(JSON.stringify({ alg: "none", typ: "JWT" }));
  const payload = base64UrlEncode(
    JSON.stringify({
      iss: ISSUER,
      sub: "admin",
      aud: AUDIENCE,
      exp: NOW + 300,
      iat: NOW,
      scope: "requests:approve",
    }),
  );
  return `${header}.${payload}.`;
}

function describe(outcome: VerifyOutcome): string {
  return outcome.ok
    ? `ok=true / subject=${outcome.subject} / scopes=${outcome.scopes.join(",")}`
    : `reason=${outcome.reason}`;
}

let failures = 0;

function check(index: number, label: string, outcome: VerifyOutcome, expected: string): void {
  const actual = describe(outcome);
  const ok = actual === expected;
  if (!ok) failures += 1;
  console.log(`[${index}/10] ${label}: ${actual}${ok ? "" : ` ← 期待は ${expected}`}`);
}

check(1, "ヘッダーなし", verifyAccessToken(undefined, options), "reason=missing_token");
check(
  2,
  "Basic スキーム",
  verifyAccessToken("Basic dXNlcjpwYXNz", options),
  "reason=malformed_header",
);
check(3, "3 パートでない", verifyAccessToken("Bearer abc.def", options), "reason=malformed_token");
check(
  4,
  "署名の改ざん",
  verifyAccessToken(`Bearer ${tamper(mint())}`, options),
  "reason=bad_signature",
);
check(5, "alg=none", verifyAccessToken(`Bearer ${algNoneToken()}`, options), "reason=unsupported_alg");
check(
  6,
  "alg=HS512",
  verifyAccessToken(`Bearer ${mint({ header: { alg: "HS512", typ: "JWT" } })}`, options),
  "reason=unsupported_alg",
);
check(
  7,
  "期限切れ",
  verifyAccessToken(`Bearer ${mint({ ttlSeconds: -600 })}`, options),
  "reason=expired",
);
check(
  8,
  "aud 不一致",
  verifyAccessToken(
    `Bearer ${mint({ audience: "https://kintai.example.internal/api" })}`,
    options,
  ),
  "reason=audience_mismatch",
);
check(
  9,
  "iss 不一致",
  verifyAccessToken(`Bearer ${mint({ issuer: "http://127.0.0.1:9999" })}`, options),
  "reason=issuer_mismatch",
);
check(
  10,
  "正常（aud が配列）",
  verifyAccessToken(
    `Bearer ${mint({ audience: ["https://kintai.example.internal/api", AUDIENCE] })}`,
    options,
  ),
  `ok=true / subject=u-001 / scopes=${SCOPE.split(" ").join(",")}`,
);

// 検証順序の確認 ―― 署名が壊れたトークンのクレームがログに出ていないこと
const captured: string[] = [];
const originalError = console.error;
console.error = (...args: unknown[]): void => {
  captured.push(args.map((value) => String(value)).join(" "));
};
try {
  const evil = tamper(mint({ subject: "admin", scope: "requests:approve" }));
  const outcome = verifyAccessToken(`Bearer ${evil}`, options);
  // 実運用のミドルウェアで出すログ。理由コードだけを出し、クレームは出さない
  console.error(`[auth] 認証失敗（${outcome.ok ? "-" : outcome.reason}）`);
} finally {
  console.error = originalError;
}
const leaked = captured.some((line) => line.includes("admin"));
console.log(`検証順序: 署名が壊れたトークンの sub がログに出ていない=${!leaked}`);

if (failures > 0) {
  console.log(`NG: ${failures} 件が期待と違いました`);
  process.exit(1);
}
console.log("OK: 10/10");
