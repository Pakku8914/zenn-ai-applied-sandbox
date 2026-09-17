// セッション 17 練習問題 1: 署名対象（69 バイト）の内訳と、そこに入らないものを一覧にする。
import { signatureBase } from "./bookstore-webauthn.js";

export type PartSource = "authenticatorData" | "clientDataJSON";

export type SignedPart = {
  readonly name: string;
  readonly bytes: number;
  readonly from: PartSource;
  readonly meaning: string;
};

/** 署名対象の内訳。合計 69 バイトになります */
export const BYTE_LAYOUT: readonly SignedPart[] = [
  { name: "rpIdHash", bytes: 32, from: "authenticatorData", meaning: "どのサイト向けの鍵か" },
  { name: "flags", bytes: 1, from: "authenticatorData", meaning: "その場に人がいたか・本人を確かめたか" },
  { name: "signCount", bytes: 4, from: "authenticatorData", meaning: "この認証器が署名した回数" },
  { name: "clientDataHash", bytes: 32, from: "clientDataJSON", meaning: "type・challenge・origin をまとめたハッシュ" },
];

export type SignedInputReport = {
  readonly totalBytes: number;
  readonly parts: readonly SignedPart[];
  /** 実物の長さが内訳の合計と一致するか */
  readonly matchesLayout: boolean;
};

/** 実物の署名対象を作って、内訳の合計と突き合わせます */
export function describeSignedInput(authenticatorData: Buffer, clientDataJson: Buffer): SignedInputReport {
  const totalBytes = signatureBase(authenticatorData, clientDataJson).length;
  const expected = BYTE_LAYOUT.reduce((sum, part) => sum + part.bytes, 0);
  return { totalBytes, parts: BYTE_LAYOUT, matchesLayout: totalBytes === expected };
}

export type FieldName =
  | "origin"
  | "challenge"
  | "rpId"
  | "userVerified"
  | "signCount"
  | "credentialId"
  | "userAgent"
  | "cookie"
  | "requestPath";

/** 並び順を固定します（報告の行がいつでも同じ順に出るように） */
export const FIELDS: readonly FieldName[] = [
  "origin",
  "challenge",
  "rpId",
  "userVerified",
  "signCount",
  "credentialId",
  "userAgent",
  "cookie",
  "requestPath",
];

/** 署名対象に入っている項目（入っていれば、後から書き換えると署名が合わなくなります） */
const COVERED: readonly FieldName[] = ["origin", "challenge", "rpId", "userVerified", "signCount"];

export function isCovered(field: FieldName): boolean {
  return COVERED.includes(field);
}

/** 人が読む 9 行。「入る／入らない」を並べると、守られている範囲がそのまま見えます */
export function coverageReport(): string[] {
  return FIELDS.map((field) => `${field}: ${isCovered(field) ? "署名対象に入る" : "署名対象に入らない"}`);
}

/** なぜ偽サイトで得た署名が本物のサイトで通らないのか（1 文で） */
export function whyPhishingFails(): string {
  return "origin が署名対象に入っているので、偽サイトで作られた署名は本物のサイトの期待値と一致しません";
}
