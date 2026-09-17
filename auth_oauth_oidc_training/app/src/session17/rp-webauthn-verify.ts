// セッション 17: サーバー（RP）側の検証。認証器が署名した 69 バイトを、こちらの期待値と突き合わせます。
// challenge の扱いはセッション 6 の PendingLoginStore と同じ構造で、
// 「覚えのないものは拒む・一度使ったら捨てる」はセッション 14 の HardenedPendingLoginStore を引き継ぎます。
import { createPublicKey, randomBytes, verify as verifySignature } from "node:crypto";
import type { JWK } from "jose";
import {
  EXPECTED_ORIGIN,
  RP_ID,
  parseAuthenticatorData,
  parseClientDataJson,
  rpIdHash,
  signatureBase,
  toBase64Url,
} from "./bookstore-webauthn.js";
import type { CeremonyType, ParsedAuthenticatorData, StoredCredential } from "./bookstore-webauthn.js";

/** ブラウザから届く登録応答（本章が扱う 4 項目）。認証器役が返す形とは別の型にしてあります */
export type RegistrationInput = {
  readonly credentialId: string;
  readonly publicJwk: JWK;
  readonly clientDataJson: Buffer;
  readonly authenticatorData: Buffer;
};

/** ブラウザから届く認証応答 */
export type AssertionInput = {
  readonly credentialId: string;
  readonly clientDataJson: Buffer;
  readonly authenticatorData: Buffer;
  readonly signature: Buffer;
};

/** 始めたけれど終わっていない儀式 1 件。challenge は state と同じ役割を果たします */
export type PendingCeremony = {
  readonly challenge: string;
  readonly type: CeremonyType;
  readonly userId: string;
  readonly origin: string;
  readonly rpId: string;
};

/** 出した challenge を覚えておく入れ物（セッション 6 の PendingLoginStore の state を challenge にしたもの） */
export class WebAuthnChallengeStore {
  private readonly pending = new Map<string, PendingCeremony>();

  /** 儀式を始めます。challenge は 32 バイトの乱数（当てられないことが唯一の防御） */
  start(type: CeremonyType, userId: string, options: { origin?: string; rpId?: string } = {}): PendingCeremony {
    const entry: PendingCeremony = {
      challenge: toBase64Url(randomBytes(32)),
      type,
      userId,
      origin: options.origin ?? EXPECTED_ORIGIN,
      rpId: options.rpId ?? RP_ID,
    };
    this.pending.set(entry.challenge, entry);
    return entry;
  }

  /** 覚えのある challenge だけを返し、同時に捨てます（2 回目は必ず失敗します） */
  consume(challenge: string): PendingCeremony | undefined {
    const entry = this.pending.get(challenge);
    if (entry !== undefined) this.pending.delete(challenge);
    return entry;
  }

  get size(): number {
    return this.pending.size;
  }
}

/** 登録済みのクレデンシャルの置き場所。本番では DB のテーブル 1 つです */
export class CredentialStore {
  private readonly byId = new Map<string, StoredCredential>();

  add(credential: StoredCredential): void {
    this.byId.set(credential.credentialId, credential);
  }

  find(credentialId: string): StoredCredential | undefined {
    return this.byId.get(credentialId);
  }

  /** その利用者のクレデンシャル（認証の開始で allowCredentials として返します） */
  forUser(userId: string): StoredCredential[] {
    return [...this.byId.values()].filter((credential) => credential.userId === userId);
  }

  get size(): number {
    return this.byId.size;
  }
}

/** 登録と認証に共通する検査で落ちた理由 */
export type CommonFailureReason =
  | "client_data_malformed"
  | "wrong_ceremony_type"
  | "unknown_challenge"
  | "origin_mismatch"
  | "authenticator_data_malformed"
  | "rp_id_mismatch"
  | "user_not_verified";

export type RegistrationFailureReason = CommonFailureReason | "duplicate_credential";

export type AssertionFailureReason =
  | CommonFailureReason
  | "unknown_credential"
  | "sign_count_not_increasing"
  | "bad_signature";

export type VerifyOptions = {
  /** ユーザー検証（UV）を必須にするか。パスワードレスでは必須です（既定 true） */
  readonly requireUserVerification?: boolean;
};

export type RegistrationOptions = VerifyOptions & {
  readonly deviceLabel?: string;
  readonly synced?: boolean;
};

type CommonResult =
  | { readonly ok: true; readonly pending: PendingCeremony; readonly parsed: ParsedAuthenticatorData }
  | { readonly ok: false; readonly reason: CommonFailureReason };

/** 登録と認証に共通する検査。この順序に意味があります */
function checkCommon(
  expected: CeremonyType,
  input: { readonly clientDataJson: Buffer; readonly authenticatorData: Buffer },
  challenges: WebAuthnChallengeStore,
  options: VerifyOptions,
): CommonResult {
  // 1. 形が読めるか
  const clientData = parseClientDataJson(input.clientDataJson);
  if (clientData === undefined) return { ok: false, reason: "client_data_malformed" };
  // 2. どちらの儀式の応答か（登録の応答を認証として受け取ってはいけません）
  if (clientData.type !== expected) return { ok: false, reason: "wrong_ceremony_type" };
  // 3. 自分が出した challenge か。ここで捨てるので、同じ応答は 2 回使えません
  const pending = challenges.consume(clientData.challenge);
  if (pending === undefined) return { ok: false, reason: "unknown_challenge" };
  if (pending.type !== expected) return { ok: false, reason: "wrong_ceremony_type" };
  // 4. origin の一致。フィッシング耐性はこの 1 行に宿ります
  if (clientData.origin !== pending.origin) return { ok: false, reason: "origin_mismatch" };
  // 5. authenticatorData が読めるか・どのサイト向けの鍵か
  const parsed = parseAuthenticatorData(input.authenticatorData);
  if (parsed === undefined) return { ok: false, reason: "authenticator_data_malformed" };
  if (!parsed.rpIdHash.equals(rpIdHash(pending.rpId))) return { ok: false, reason: "rp_id_mismatch" };
  // 6. 本人だと認証器が確かめたか（UV のフラグ）
  if ((options.requireUserVerification ?? true) && !parsed.userVerified) {
    return { ok: false, reason: "user_not_verified" };
  }
  return { ok: true, pending, parsed };
}

export type RegistrationResult =
  | { readonly ok: true; readonly credential: StoredCredential }
  | { readonly ok: false; readonly reason: RegistrationFailureReason };

/**
 * 登録の儀式を検証します。署名の検証はありません（登録の応答に署名は入っていません）。
 * 「届いた公開鍵が本物の認証器のものか」を確かめるのが attestation で、本章では扱いません。
 */
export function verifyRegistration(
  input: RegistrationInput,
  challenges: WebAuthnChallengeStore,
  credentials: CredentialStore,
  options: RegistrationOptions = {},
): RegistrationResult {
  if (credentials.find(input.credentialId) !== undefined) {
    return { ok: false, reason: "duplicate_credential" };
  }
  const common = checkCommon("webauthn.create", input, challenges, options);
  if (!common.ok) return { ok: false, reason: common.reason };

  const credential: StoredCredential = {
    credentialId: input.credentialId,
    userId: common.pending.userId, // 誰の鍵かは challenge 側が知っています（応答を信じません）
    publicJwk: input.publicJwk,
    signCount: common.parsed.signCount,
    deviceLabel: options.deviceLabel ?? "unknown-device",
    synced: options.synced ?? false,
  };
  credentials.add(credential);
  return { ok: true, credential };
}

export type AssertionResult =
  | { readonly ok: true; readonly userId: string; readonly signCount: number; readonly userVerified: boolean }
  | { readonly ok: false; readonly reason: AssertionFailureReason };

/** 認証の儀式を検証します。すべての検査を通ったものだけをログインとして認めます */
export function verifyAssertion(
  input: AssertionInput,
  challenges: WebAuthnChallengeStore,
  credentials: CredentialStore,
  options: VerifyOptions = {},
): AssertionResult {
  // 1. 知らないクレデンシャル ID はここで終わり（公開鍵が引けないので署名も確かめられません）
  const credential = credentials.find(input.credentialId);
  if (credential === undefined) return { ok: false, reason: "unknown_credential" };

  // 2〜7. 共通の検査
  const common = checkCommon("webauthn.get", input, challenges, options);
  if (!common.ok) return { ok: false, reason: common.reason };

  // 8. サインカウントが前回より増えているか（鍵がコピーされたことに気づく手がかり）
  if (common.parsed.signCount <= credential.signCount) {
    return { ok: false, reason: "sign_count_not_increasing" };
  }

  // 9. 最後に署名。ここまでの検査を全部通った 69 バイトに対してだけ確かめます
  let verified = false;
  try {
    verified = verifySignature(
      "sha256",
      signatureBase(input.authenticatorData, input.clientDataJson),
      createPublicKey({ key: credential.publicJwk, format: "jwk" }),
      input.signature,
    );
  } catch {
    verified = false; // 署名の形が壊れていても「検証に失敗」に寄せます（500 にしない）
  }
  if (!verified) return { ok: false, reason: "bad_signature" };

  credential.signCount = common.parsed.signCount; // 通ってから更新する
  return {
    ok: true,
    userId: credential.userId,
    signCount: credential.signCount,
    userVerified: common.parsed.userVerified,
  };
}
