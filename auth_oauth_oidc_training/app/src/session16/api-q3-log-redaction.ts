// 問題 3 の解答: すでに出力されてしまったログ 1 行を点検し、秘密が混ざっていたら落とします。
// 組み立てる側（redact）で防ぐのが本筋ですが、
// 昔からあるログ出力を全部直せないので「出口の網」も要ります。
import { FORBIDDEN_KEYS, REDACTED, maskSecret } from "./api-service-audit-log.js";

export type LeakKind = "jwt" | "basic-credentials" | "forbidden-field" | "url-secret";

export type Leak = {
  readonly kind: LeakKind;
  /** 何にひっかかったか（秘密そのものは入れません） */
  readonly hint: string;
};

/** JWT らしい 3 部構成の文字列 */
const JWT_PATTERN = /eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}/g;
/** Basic 認証のヘッダ（client_secret が base64 で入っています） */
const BASIC_PATTERN = /Basic\s+[A-Za-z0-9+/]{8,}={0,2}/g;

/**
 * key=value / "key":"value" / key: value のどの形でも拾えるようにします。
 * すでに伏せた値（<redacted>）は指摘しません。伏せた行をもう一度点検しても安全と出るようにするためです。
 */
function forbiddenFieldPattern(key: string): RegExp {
  return new RegExp(`"?${key}"?\\s*[:=]\\s*"?(?!${REDACTED})[^"\\s,&}]+`, "i");
}

/** URL のクエリに秘密が付いている（リダイレクト先の記録でよく起きます） */
const URL_SECRET_KEYS: readonly string[] = ["code", "access_token", "id_token", "refresh_token"];

/** 1 行を点検します。指摘の順序は種類の順に固定です */
export function findLeaks(line: string): Leak[] {
  const leaks: Leak[] = [];
  // g 付きの正規表現に test() を使うと lastIndex が進んで次回の判定がずれます。match() で数えます
  const jwtCount = line.match(JWT_PATTERN)?.length ?? 0;
  if (jwtCount > 0) leaks.push({ kind: "jwt", hint: `JWT らしい文字列が ${jwtCount} 個` });
  if (line.match(BASIC_PATTERN) !== null) leaks.push({ kind: "basic-credentials", hint: "Basic 認証の資格情報" });
  for (const key of FORBIDDEN_KEYS) {
    if (forbiddenFieldPattern(key).test(line)) leaks.push({ kind: "forbidden-field", hint: key });
  }
  for (const key of URL_SECRET_KEYS) {
    if (new RegExp(`[?&]${key}=(?!${REDACTED})`, "i").test(line)) {
      leaks.push({ kind: "url-secret", hint: key });
    }
  }
  return leaks;
}

export function isSafeLine(line: string): boolean {
  return findLeaks(line).length === 0;
}

/** 見つけた秘密を伏せます。行の構造は壊さないので、あとから読めます */
export function sanitizeLine(line: string): string {
  let safe = line.replace(JWT_PATTERN, (match) => maskSecret(match));
  safe = safe.replace(BASIC_PATTERN, `Basic ${REDACTED}`);
  for (const key of FORBIDDEN_KEYS) {
    // key=値 / "key":"値" の「値」だけを置き換えます
    safe = safe.replace(new RegExp(`("?${key}"?\\s*[:=]\\s*)"?[^"\\s,&}]+"?`, "gi"), `$1${REDACTED}`);
  }
  for (const key of URL_SECRET_KEYS) {
    safe = safe.replace(new RegExp(`([?&]${key}=)[^&\\s]+`, "gi"), `$1${REDACTED}`);
  }
  return safe;
}
