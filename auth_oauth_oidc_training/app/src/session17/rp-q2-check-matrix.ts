// セッション 17 練習問題 2: 検証の順序を仕様として書き、実機の結果と突き合わせる。
import { randomBytes } from "node:crypto";
import { EXPECTED_ORIGIN, RP_ID, toBase64Url } from "./bookstore-webauthn.js";
import { createAuthenticator } from "./authenticator-stub.js";
import {
  CredentialStore,
  WebAuthnChallengeStore,
  verifyAssertion,
  verifyRegistration,
} from "./rp-webauthn-verify.js";
import type { AssertionInput } from "./rp-webauthn-verify.js";

export type CheckId =
  | "client-data-readable"
  | "ceremony-type"
  | "challenge-known"
  | "origin-match"
  | "rp-id-match"
  | "user-verified"
  | "sign-count-increasing"
  | "signature";

export type CheckSpec = {
  readonly id: CheckId;
  /** 落ちたときに返る理由コード */
  readonly reason: string;
  /** この検査が止める攻撃 */
  readonly stops: string;
};

/** 検査の順序。verifyAssertion の中の並びと 1 対 1 に対応させます */
export const CHECK_ORDER: readonly CheckSpec[] = [
  { id: "client-data-readable", reason: "client_data_malformed", stops: "壊れた入力でサーバーを落とす" },
  { id: "ceremony-type", reason: "wrong_ceremony_type", stops: "登録の応答をログインに流し込む" },
  { id: "challenge-known", reason: "unknown_challenge", stops: "盗んだ assertion の使い回し（リプレイ）" },
  { id: "origin-match", reason: "origin_mismatch", stops: "偽サイトで集めた署名の持ち込み（フィッシング）" },
  { id: "rp-id-match", reason: "rp_id_mismatch", stops: "別サイト向けの鍵の流用" },
  { id: "user-verified", reason: "user_not_verified", stops: "拾った端末でそのままログインされる" },
  { id: "sign-count-increasing", reason: "sign_count_not_increasing", stops: "コピーされた鍵の使用（気づく手がかり）" },
  { id: "signature", reason: "bad_signature", stops: "公開鍵だけを盗んだ相手のなりすまし" },
];

export type BrokenPart =
  | "ceremony-type"
  | "challenge"
  | "origin"
  | "rp-id"
  | "user-verification"
  | "sign-count"
  | "signature";

/** 壊した場所 → どの検査で落ちるか */
const BROKEN_TO_CHECK: Readonly<Record<BrokenPart, CheckId>> = {
  "ceremony-type": "ceremony-type",
  challenge: "challenge-known",
  origin: "origin-match",
  "rp-id": "rp-id-match",
  "user-verification": "user-verified",
  "sign-count": "sign-count-increasing",
  signature: "signature",
};

/** 検査の順序から「最初に落ちる検査」を求めます。どこも落ちなければ "ok" */
export function predictReason(broken: readonly BrokenPart[]): string {
  const ids = broken.map((part) => BROKEN_TO_CHECK[part]);
  const first = CHECK_ORDER.find((spec) => ids.includes(spec.id));
  return first === undefined ? "ok" : first.reason;
}

export type MatrixRow = {
  readonly broken: readonly BrokenPart[];
  readonly predicted: string;
  readonly actual: string;
  readonly agree: boolean;
};

const FAKE_ORIGIN = "http://localhost:3999";
const FAKE_RP_ID = "evil.example";

/** 署名を 1 バイトだけ壊します（鍵は本物のまま、署名だけが合わなくなる状態） */
function flipByte(signature: Buffer): Buffer {
  const copy = Buffer.from(signature);
  copy[10] = (copy[10] ?? 0) ^ 0xff;
  return copy;
}

/** 予測どおりに落ちるかを実機で確かめます */
export function runMatrix(cases: readonly (readonly BrokenPart[])[]): MatrixRow[] {
  const challenges = new WebAuthnChallengeStore();
  const credentials = new CredentialStore();
  const key = createAuthenticator({ deviceLabel: "matrix-key" });
  const register = challenges.start("webauthn.create", "alice-sub");
  verifyRegistration(
    key.register({ challenge: register.challenge, origin: EXPECTED_ORIGIN, rpId: RP_ID }),
    challenges,
    credentials,
    { deviceLabel: "matrix-key" },
  );
  const credential = credentials.find(key.credentialId);

  return cases.map((broken) => {
    const has = (part: BrokenPart): boolean => broken.includes(part);
    // 儀式の取り違えを試すときは、challenge も登録用として出しておきます
    const pending = challenges.start(has("ceremony-type") ? "webauthn.create" : "webauthn.get", "alice-sub");
    const ceremonyInput = {
      challenge: has("challenge") ? toBase64Url(randomBytes(32)) : pending.challenge,
      origin: has("origin") ? FAKE_ORIGIN : EXPECTED_ORIGIN,
      rpId: has("rp-id") ? FAKE_RP_ID : RP_ID,
      userVerified: !has("user-verification"),
    };

    let input: AssertionInput;
    if (has("ceremony-type")) {
      const response = key.register(ceremonyInput);
      input = {
        credentialId: response.credentialId,
        clientDataJson: response.clientDataJson,
        authenticatorData: response.authenticatorData,
        signature: Buffer.alloc(64), // 登録の応答に署名はありません
      };
    } else {
      const response = key.assert(ceremonyInput);
      input = { ...response, signature: has("signature") ? flipByte(response.signature) : response.signature };
    }

    // サインカウントは「サーバー側の記録を進めておく」ことで壊します（認証器は戻せません）
    const saved = credential?.signCount ?? 0;
    if (has("sign-count") && credential !== undefined) credential.signCount = 10_000;
    const result = verifyAssertion(input, challenges, credentials);
    if (has("sign-count") && credential !== undefined) credential.signCount = saved;

    const predicted = predictReason(broken);
    const actual = result.ok ? "ok" : result.reason;
    return { broken, predicted, actual, agree: predicted === actual };
  });
}

/** すべての行で予測と実測が一致したか */
export function allAgree(rows: readonly MatrixRow[]): boolean {
  return rows.every((row) => row.agree);
}
