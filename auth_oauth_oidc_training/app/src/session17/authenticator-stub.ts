// セッション 17: 認証器（authenticator）の役をするコード。
// 本物は指紋センサーの付いた小さなコンピュータですが、儀式の中でやることは 2 つだけです。
//   1. 鍵ペアを作る（秘密鍵は外に出さない）
//   2. authenticatorData ‖ SHA-256(clientDataJSON) に署名する
// この 2 つは Node.js だけで再現できます。だからブラウザが無くても儀式を実機で通せます。
import { createPrivateKey, createPublicKey, generateKeyPairSync, randomBytes, sign } from "node:crypto";
import type { JWK } from "jose";
import { buildAuthenticatorData, buildClientDataJson, signatureBase, toBase64Url } from "./bookstore-webauthn.js";
import type { CeremonyType } from "./bookstore-webauthn.js";

/** 儀式 1 回分の入力。origin と rpId をわざと変えられるようにしてあります（第 5 節の実験用） */
export type CeremonyInput = {
  readonly challenge: string;
  readonly origin: string;
  readonly rpId: string;
  readonly userPresent?: boolean;
  readonly userVerified?: boolean;
  readonly crossOrigin?: boolean;
  /** サインカウントをいくつ進めるか（既定 1）。0 にすると「増えない認証器」になります */
  readonly countStep?: number;
};

/** 認証の儀式で返るもの。登録の儀式ではここから signature が無くなり publicJwk が増えます */
export type AssertionResponse = {
  readonly credentialId: string;
  readonly clientDataJson: Buffer;
  readonly authenticatorData: Buffer;
  readonly signature: Buffer;
};

export type AuthenticatorOptions = {
  /** 既存の秘密鍵から作り直す（同期パスキーの再現に使います。練習問題 6） */
  readonly privateJwk?: JWK;
  readonly credentialId?: string;
  readonly signCount?: number;
  readonly deviceLabel?: string;
};

export function createAuthenticator(options: AuthenticatorOptions = {}) {
  // 鍵ペアはこの関数の中で作り、privateKey は戻り値に含めません（本物の認証器と同じ性質）
  const privateKey =
    options.privateJwk === undefined
      ? generateKeyPairSync("ec", { namedCurve: "P-256" }).privateKey
      : createPrivateKey({ key: options.privateJwk, format: "jwk" });
  const publicKey = createPublicKey(privateKey);
  const publicJwk: JWK = publicKey.export({ format: "jwk" });
  const credentialId = options.credentialId ?? toBase64Url(randomBytes(16));
  let signCount = options.signCount ?? 0;

  const ceremony = (type: CeremonyType, input: CeremonyInput) => ({
    clientDataJson: buildClientDataJson({
      type,
      challenge: input.challenge,
      origin: input.origin, // ブラウザが入れる値。これが署名対象に入ります
      crossOrigin: input.crossOrigin ?? false,
    }),
    authenticatorData: buildAuthenticatorData({
      rpId: input.rpId,
      signCount,
      userPresent: input.userPresent,
      userVerified: input.userVerified,
    }),
  });

  return {
    credentialId,
    publicJwk,
    deviceLabel: options.deviceLabel ?? "stub-authenticator",
    get signCount(): number {
      return signCount;
    },
    /** 登録の儀式。署名はしません（本物は attestation を付けますが、本章では扱いません） */
    register(input: CeremonyInput) {
      return { credentialId, publicJwk, ...ceremony("webauthn.create", input) };
    },
    /** 認証の儀式。署名対象は 69 バイトだけで、URL やヘッダは入りません */
    assert(input: CeremonyInput): AssertionResponse {
      signCount += input.countStep ?? 1; // 認証のたびに増える。本来は戻りません
      const { clientDataJson, authenticatorData } = ceremony("webauthn.get", input);
      return {
        credentialId,
        clientDataJson,
        authenticatorData,
        signature: sign("sha256", signatureBase(authenticatorData, clientDataJson), privateKey),
      };
    },
    /**
     * 秘密鍵を書き出します。本物のセキュリティキーにこの口はありません。
     * 同期パスキーでは OS とクラウドアカウントがこの役を務めます（練習問題 6 で使います）。
     */
    exportPrivateJwk(): JWK {
      return privateKey.export({ format: "jwk" });
    },
  };
}
