// JWT を「読む」ための道具箱。このファイルには検証が 1 つも入っていません。
// デコードは鍵を持たない誰でもできる操作であり、正しさの確認にはならないことを確かめるために使います。

/** ピリオドで 3 つに割り、ヘッダとペイロードを JSON に戻します（署名は文字列のまま） */
export function decodeParts(token: string): {
  header: Record<string, unknown>;
  payload: Record<string, unknown>;
  signature: string;
} {
  const [headerPart, payloadPart, signaturePart, ...rest] = token.split(".");
  if (
    headerPart === undefined ||
    payloadPart === undefined ||
    signaturePart === undefined ||
    rest.length > 0
  ) {
    throw new Error("JWS 形式（ピリオド区切りの 3 部構成）ではありません");
  }
  return {
    header: decodeJsonSegment(headerPart),
    payload: decodeJsonSegment(payloadPart),
    signature: signaturePart,
  };
}

/** Base64URL の 1 区画を UTF-8 の JSON として読み直します */
function decodeJsonSegment(segment: string): Record<string, unknown> {
  return JSON.parse(Buffer.from(segment, "base64url").toString("utf8")) as Record<string, unknown>;
}

/** aud は文字列でも配列でもよい仕様なので、必ず配列に正規化してから扱います */
export function audienceList(payload: Record<string, unknown>): string[] {
  const aud = payload["aud"];
  if (typeof aud === "string") {
    return [aud];
  }
  if (Array.isArray(aud)) {
    return aud.filter((value): value is string => typeof value === "string");
  }
  return [];
}

/** exp と iat の差から有効期間（秒）を求めます。どちらか欠けていれば undefined */
export function lifetimeSeconds(payload: Record<string, unknown>): number | undefined {
  const exp = payload["exp"];
  const iat = payload["iat"];
  if (typeof exp !== "number" || typeof iat !== "number") {
    return undefined;
  }
  return exp - iat;
}
