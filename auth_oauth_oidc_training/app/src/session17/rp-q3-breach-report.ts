// セッション 17 練習問題 3: サーバーの保管物が漏れたときに何ができるかを、
// セッション 3 のパスワードハッシュと今章の公開鍵で並べて比べる。
import { createPublicKey, verify as verifySignature } from "node:crypto";
import { EXPECTED_ORIGIN, RP_ID, signatureBase } from "./bookstore-webauthn.js";
import { createAuthenticator } from "./authenticator-stub.js";
import {
  CredentialStore,
  WebAuthnChallengeStore,
  verifyAssertion,
  verifyRegistration,
} from "./rp-webauthn-verify.js";

export type SecretShape = "password-hash" | "public-key";

export type BreachImpact = {
  readonly shape: SecretShape;
  /** 盗んだものだけで、そのままログインできるか */
  readonly canImpersonateImmediately: boolean;
  /** 手元で当て続けられるか（オフライン攻撃） */
  readonly canGuessOffline: boolean;
  /** 同じ値が他サイトでも通用しうるか */
  readonly reusableOnOtherSites: boolean;
  /** 利用者から直接引き出せるか（フィッシング） */
  readonly phishable: boolean;
  readonly note: string;
};

export const BREACH_IMPACTS: Readonly<Record<SecretShape, BreachImpact>> = {
  "password-hash": {
    shape: "password-hash",
    canImpersonateImmediately: false,
    canGuessOffline: true,
    reusableOnOtherSites: true,
    phishable: true,
    note: "Argon2id は当てる速度を落とすだけで、当てられない保証はありません。当たった平文は他サイトでも試せます",
  },
  "public-key": {
    shape: "public-key",
    canImpersonateImmediately: false,
    canGuessOffline: false,
    reusableOnOtherSites: false,
    phishable: false,
    note: "公開鍵から秘密鍵は求められません。そもそも公開してよい値なので、漏れても認証の強度は変わりません",
  },
};

export function impactOf(shape: SecretShape): BreachImpact {
  return BREACH_IMPACTS[shape];
}

/** 人が読む 2 行。漏れたときの差を 1 行ずつにします */
export function breachReport(): string[] {
  return (["password-hash", "public-key"] as const).map((shape) => {
    const impact = impactOf(shape);
    const risks = [
      impact.canGuessOffline ? "手元で当てられる" : "手元で当てられない",
      impact.reusableOnOtherSites ? "他サイトでも試せる" : "他サイトでは使えない",
      impact.phishable ? "利用者から引き出せる" : "利用者から引き出せない",
    ];
    return `${shape}: ${risks.join(" / ")}`;
  });
}

export type ForgeryAttempt = {
  /** 検証が返した理由 */
  readonly reason: string;
  /** 攻撃者の署名が、盗んだ公開鍵で検証できたか */
  readonly signatureValidForStolenKey: boolean;
};

/**
 * 公開鍵とクレデンシャル ID を盗んだ攻撃者が assertion を作ってみる実験。
 * 同じ credentialId を名乗れるので検証は最後まで進みますが、署名で必ず落ちます。
 */
export function attemptForgery(): ForgeryAttempt {
  const challenges = new WebAuthnChallengeStore();
  const credentials = new CredentialStore();
  const alice = createAuthenticator({ deviceLabel: "alice-laptop" });

  const register = challenges.start("webauthn.create", "alice-sub");
  const registered = verifyRegistration(
    alice.register({ challenge: register.challenge, origin: EXPECTED_ORIGIN, rpId: RP_ID }),
    challenges,
    credentials,
    { deviceLabel: "alice-laptop" },
  );

  // 攻撃者が盗めるのは credentialId と公開鍵。秘密鍵は届いていないので自分の鍵で署名します
  const attacker = createAuthenticator({ credentialId: alice.credentialId, deviceLabel: "attacker" });
  const login = challenges.start("webauthn.get", "alice-sub");
  const forged = attacker.assert({ challenge: login.challenge, origin: EXPECTED_ORIGIN, rpId: RP_ID });
  const result = verifyAssertion(forged, challenges, credentials);

  // 盗んだ公開鍵で攻撃者の署名を確かめてみます。保管されているのは alice の公開鍵なので一致しません
  const signatureValidForStolenKey = registered.ok
    ? verifySignature(
        "sha256",
        signatureBase(forged.authenticatorData, forged.clientDataJson),
        createPublicKey({ key: registered.credential.publicJwk, format: "jwk" }),
        forged.signature,
      )
    : false;

  return { reason: result.ok ? "通ってしまった" : result.reason, signatureValidForStolenKey };
}

/** パスワード認証と公開鍵による認証で「サーバーが持つもの」を並べた表の行 */
export function compareWithPassword(): string[] {
  return [
    "パスワード認証: サーバーは検証に使える値（ハッシュ）を持つ。漏れたら当てられる",
    "公開鍵による認証: サーバーは検証にしか使えない値（公開鍵）を持つ。漏れても署名は作れない",
  ];
}
