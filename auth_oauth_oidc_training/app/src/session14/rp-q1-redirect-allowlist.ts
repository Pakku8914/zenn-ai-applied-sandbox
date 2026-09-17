// 練習問題 1: リダイレクト URI をワイルドカード登録と完全一致で照合し、横取りに使えるものを洗い出す。
// 宛先 1 本ずつの判定（auditRedirectUri）と、登録値そのものの緩さの判定（auditRegistration）を分けて持ちます。
import { matchesRegistration } from "../session12/mobile-redirect.js";
import {
  EXACT_REDIRECT_URIS,
  WILDCARD_REGISTRATION,
  isAllowedRedirectUri,
  registrationIsLoose,
} from "./redirect-uri-guard.js";

export type UriVerdict = {
  readonly uri: string;
  readonly passesWildcard: boolean;
  readonly passesExactMatch: boolean;
  /** ワイルドカードは通すが完全一致は通さない ＝ 認可コード横取りの足がかりになる */
  readonly hijackRisk: boolean;
};

/** 1 本のリダイレクト先を、ワイルドカード登録・完全一致・横取りリスクの 3 点で判定します */
export function auditRedirectUri(
  uri: string,
  registered: string = WILDCARD_REGISTRATION,
  allowlist: readonly string[] = EXACT_REDIRECT_URIS,
): UriVerdict {
  const passesWildcard = matchesRegistration(registered, uri);
  const passesExactMatch = isAllowedRedirectUri(uri, allowlist);
  return { uri, passesWildcard, passesExactMatch, hijackRisk: passesWildcard && !passesExactMatch };
}

/** 複数のリダイレクト先をまとめて監査します */
export function auditRedirectUris(uris: readonly string[]): UriVerdict[] {
  return uris.map((uri) => auditRedirectUri(uri));
}

/** 横取りに使える（hijackRisk が true の）リダイレクト先だけを抜き出します */
export function hijackableUris(uris: readonly string[]): string[] {
  return auditRedirectUris(uris)
    .filter((v) => v.hijackRisk)
    .map((v) => v.uri);
}

export type RegistrationVerdict = {
  readonly registered: string;
  /** 登録値そのものが緩いか（末尾が /* のワイルドカード登録） */
  readonly loose: boolean;
  /** この登録値のもとで「ワイルドカードは通すが完全一致は通さない」宛先 */
  readonly hijackable: string[];
};

/**
 * 登録値 1 本を「緩さ」と「その緩さで余分に許される宛先」の両面から監査します。
 * loose が true でも hijackable が空なら、いま実際に狙える宛先は無い、という読み方ができます。
 */
export function auditRegistration(registered: string, uris: readonly string[]): RegistrationVerdict {
  return {
    registered,
    loose: registrationIsLoose(registered),
    hijackable: uris.filter((uri) => auditRedirectUri(uri, registered).hijackRisk),
  };
}

/** 複数の登録値を、余分に許す宛先が多いものから先に並べます（直す順番がそのまま出る） */
export function auditRegistrations(
  registrations: readonly string[],
  uris: readonly string[],
): RegistrationVerdict[] {
  return registrations
    .map((registered) => auditRegistration(registered, uris))
    .sort((a, b) => b.hijackable.length - a.hijackable.length);
}
