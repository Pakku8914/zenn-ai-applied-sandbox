// セッション 17: WebAuthn の 2 つの儀式でやりとりするデータを、組み立てて読み戻す道具。
// 目的は「署名対象」（authenticatorData ‖ SHA-256(clientDataJSON)）を自分の手で作れるようにすることです。
import { createHash } from "node:crypto";
import type { JWK } from "jose";

/** RP ID。オリジンの「ホスト名」だけを使います（スキームもポートも含みません） */
export const RP_ID = "localhost";
/** 期待するオリジン。スキーム・ホスト・ポートまで含めて 1 文字も違ってはいけません */
export const EXPECTED_ORIGIN = "http://localhost:3100";

export function toBase64Url(bytes: Buffer): string {
  return bytes.toString("base64url");
}

export function fromBase64Url(value: string): Buffer {
  return Buffer.from(value, "base64url");
}

/** RP ID の SHA-256（32 バイト）。authenticatorData の先頭に入ります */
export function rpIdHash(rpId: string): Buffer {
  return createHash("sha256").update(rpId, "utf8").digest();
}

export const FLAG_USER_PRESENT = 0x01; // UP: その場に人がいて操作した
export const FLAG_USER_VERIFIED = 0x04; // UV: 本人だと認証器が確かめた（PIN・生体）

export type AuthenticatorDataInput = {
  readonly rpId: string;
  readonly signCount: number;
  readonly userPresent?: boolean; // 既定 true
  readonly userVerified?: boolean; // 既定 true
};

/**
 * authenticatorData を組み立てます。
 * 「RP ID のハッシュ 32 バイト ＋ フラグ 1 バイト ＋ サインカウント 4 バイト」= 37 バイト。
 * 本物の登録応答はこの後ろに attested credential data が続きますが、本章では扱いません。
 */
export function buildAuthenticatorData(input: AuthenticatorDataInput): Buffer {
  let flags = 0;
  if (input.userPresent ?? true) flags |= FLAG_USER_PRESENT;
  if (input.userVerified ?? true) flags |= FLAG_USER_VERIFIED;
  const counter = Buffer.alloc(4);
  counter.writeUInt32BE(input.signCount, 0); // 4 バイトのビッグエンディアン
  return Buffer.concat([rpIdHash(input.rpId), Buffer.from([flags]), counter]);
}

export type ParsedAuthenticatorData = {
  readonly rpIdHash: Buffer;
  readonly userPresent: boolean;
  readonly userVerified: boolean;
  readonly signCount: number;
};

/** authenticatorData を読み戻します。37 バイト未満は形が違うので undefined */
export function parseAuthenticatorData(data: Buffer): ParsedAuthenticatorData | undefined {
  if (data.length < 37) return undefined;
  const flags = data[32] ?? 0;
  return {
    rpIdHash: data.subarray(0, 32),
    userPresent: (flags & FLAG_USER_PRESENT) !== 0,
    userVerified: (flags & FLAG_USER_VERIFIED) !== 0,
    signCount: data.readUInt32BE(33),
  };
}

/** 儀式は 2 つだけ。登録が create、認証が get です */
export type CeremonyType = "webauthn.create" | "webauthn.get";

const CEREMONY_TYPES: readonly CeremonyType[] = ["webauthn.create", "webauthn.get"];

export function toCeremonyType(value: unknown): CeremonyType | undefined {
  return CEREMONY_TYPES.find((type) => type === value);
}

/** ブラウザが組み立てる clientDataJSON の中身。origin が入っているのが最重要です */
export type ClientData = {
  readonly type: CeremonyType;
  readonly challenge: string; // サーバーが出した使い捨ての値（base64url）
  readonly origin: string; // ブラウザが「いま自分がどこにいるか」を書き込む
  readonly crossOrigin: boolean;
};

export function buildClientDataJson(data: ClientData): Buffer {
  return Buffer.from(JSON.stringify(data), "utf8");
}

/** 受け取った clientDataJSON を読み取ります。形が違えば undefined */
export function parseClientDataJson(json: Buffer): ClientData | undefined {
  let decoded: unknown;
  try {
    decoded = JSON.parse(json.toString("utf8"));
  } catch {
    return undefined;
  }
  if (typeof decoded !== "object" || decoded === null) return undefined;
  const record = decoded as Record<string, unknown>;
  const type = toCeremonyType(record["type"]);
  const challenge = record["challenge"];
  const origin = record["origin"];
  if (type === undefined || typeof challenge !== "string" || typeof origin !== "string") return undefined;
  return { type, challenge, origin, crossOrigin: record["crossOrigin"] === true };
}

/**
 * 認証器が署名する対象。authenticatorData ‖ SHA-256(clientDataJSON) の 69 バイトです。
 * サーバーは「受け取ったバイト列」をそのままハッシュします（JSON を作り直してはいけません）。
 */
export function signatureBase(authenticatorData: Buffer, clientDataJson: Buffer): Buffer {
  return Buffer.concat([authenticatorData, createHash("sha256").update(clientDataJson).digest()]);
}

/** 登録済みのクレデンシャル 1 件。秘密鍵は届かないので、公開鍵とサインカウントだけを持ちます */
export type StoredCredential = {
  readonly credentialId: string;
  readonly userId: string; // トークンの sub と同じ役割（mid01 の AccountLinks と同じ結び付け方）
  readonly publicJwk: JWK;
  signCount: number; // 認証のたびに更新する、唯一の可変項目
  readonly deviceLabel: string;
  readonly synced: boolean; // 同期パスキーか、デバイス固定か
};

/** 1 人の利用者にぶら下がる認証手段。パスワードとクレデンシャルを併存させるための表です */
export type AccountAuthMethods = {
  readonly userId: string;
  readonly passwordHash: string | null; // null になったらパスワードレス
  readonly credentials: readonly StoredCredential[];
  readonly recoveryCodesLeft: number;
};
