// 署名鍵のローテーションを「順序」と「待ち時間」に分けて持ちます。
// 手順書の本質はこの 2 つなので、文章ではなくコードにして間違いを検出できるようにします。
import { verifyOptions } from "../session04/api-service-verify-jwt.js";
import { ACCESS_TOKEN_LIFESPAN, REFRESH_IDLE_TIMEOUT } from "../session07/bookstore-tokens.js";

/**
 * その時点で JWKS に載っている kid の集合で、このトークンを検証できるか。
 * 検証側の判断はこれだけです。鍵が何本あっても、コードは kid を照らし合わせるだけで済みます。
 */
export function canVerify(publishedKids: readonly string[], tokenKid: string): boolean {
  return publishedKids.includes(tokenKid);
}

export type LifespanInput = {
  /** アクセストークンの寿命（秒） */
  readonly accessTokenLifespan: number;
  /** リフレッシュトークンが使える上限（秒）。これも同じ鍵で署名されています */
  readonly refreshIdleTimeout: number;
  /** 検証側が JWKS を取り直す最短間隔（秒）。認可サーバーではなく自分の設定です */
  readonly jwksCacheSeconds: number;
  /** 検証側が許している時計のずれ（秒） */
  readonly clockToleranceSeconds: number;
};

/** 本書のサンドボックスの値。寿命は realm 定義が正、キャッシュは検証側の設定が正です */
export const BOOKSTORE_LIFESPANS: LifespanInput = {
  accessTokenLifespan: ACCESS_TOKEN_LIFESPAN,
  refreshIdleTimeout: REFRESH_IDLE_TIMEOUT,
  // セッション 10 の練習問題で作った JwksCache の既定値（30 秒）
  jwksCacheSeconds: 30,
  clockToleranceSeconds: verifyOptions.clockTolerance,
};

/** 鍵を足してから署名を切り替えるまでに待つ秒数（新しい kid が検証側に届くまで） */
export function propagationWaitSeconds(input: LifespanInput): number {
  return input.jwksCacheSeconds + input.clockToleranceSeconds;
}

/**
 * 署名を切り替えてから古い鍵を消すまでに待つ秒数。
 * アクセストークンだけでなくリフレッシュトークンも同じ鍵で署名されているので、
 * 寿命の長いほうが消えるまで待ちます。
 */
export function retirementWaitSeconds(input: LifespanInput): number {
  return Math.max(input.accessTokenLifespan, input.refreshIdleTimeout) + input.clockToleranceSeconds;
}

/** 2 本の鍵が JWKS に並んでいなければならない合計時間 */
export function overlapWindowSeconds(input: LifespanInput): number {
  return propagationWaitSeconds(input) + retirementWaitSeconds(input);
}

/** 手順書に書く 1 手 */
export type Step = "add-key" | "wait-propagation" | "switch-signing" | "wait-retirement" | "remove-old-key";

/** 安全な順序。1 つでも入れ替えると、落ちる相手と落ち方が変わります */
export const SAFE_RUNBOOK: readonly Step[] = [
  "add-key",
  "wait-propagation",
  "switch-signing",
  "wait-retirement",
  "remove-old-key",
];

/** 各手でやること。手順書に添える説明の元データです */
export const STEP_LABELS: Readonly<Record<Step, string>> = {
  "add-key": "新しい鍵を JWKS に載せる（まだ署名には使わない）",
  "wait-propagation": "検証側が新しい kid を知るまで待つ",
  "switch-signing": "新しいトークンの署名を新しい鍵に切り替える",
  "wait-retirement": "古い kid で署名されたトークンが全部切れるまで待つ",
  "remove-old-key": "古い鍵を JWKS から外す",
};
