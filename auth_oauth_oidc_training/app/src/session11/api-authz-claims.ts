// セッション 11: 検証済みトークンから「認可の判断材料」だけを取り出します。
// 署名・iss・aud・exp の検証はセッション 10 で終わっている前提です。
// ここから先は「何を許すか」だけを考えます。
import { parseScope } from "../session07/rp-scope.js";

/** api-service が「自分に対するクライアントロール」を探すときのキー */
export const RESOURCE_CLIENT_ID = "api-service";

/** 認可の判断に使う材料。トークンに書かれていたことだけが入ります */
export type TokenFacts = {
  /** 本人：認可サーバーが発行した不変の識別子。所有者チェックはこれで行います */
  readonly sub: string;
  /** 表示用の名前。変わりうるので判定には使いません */
  readonly username: string;
  /** クライアントが要求した権限の範囲。集合として扱います（セッション 7） */
  readonly scopes: readonly string[];
  /** 利用者が持つ realm ロール */
  readonly realmRoles: readonly string[];
  /** 利用者が持つ、この API に対するクライアントロール */
  readonly clientRoles: readonly string[];
  /** 発行時刻（epoch 秒）。ここに載った権限は「この時刻の状態」です */
  readonly issuedAt: number;
  /** 失効時刻（epoch 秒）。権限を取り上げても、ここまではこのトークンが通ります */
  readonly expiresAt: number;
};

/** 入れ子のクレームを、型を確かめながら文字列配列として取り出します */
function stringsAt(payload: Record<string, unknown>, path: readonly string[]): string[] {
  let current: unknown = payload;
  for (const key of path) {
    if (typeof current !== "object" || current === null) return [];
    current = (current as Record<string, unknown>)[key];
  }
  if (!Array.isArray(current)) return [];
  return current.filter((item): item is string => typeof item === "string").sort();
}

function stringAt(payload: Record<string, unknown>, key: string): string {
  const value = payload[key];
  return typeof value === "string" ? value : "";
}

function numberAt(payload: Record<string, unknown>, key: string): number {
  const value = payload[key];
  return typeof value === "number" ? value : 0;
}

/**
 * 検証済みのペイロードから TokenFacts を作ります。
 * クレームが欠けていても例外にせず「空」として扱うのが要点です
 * （欠けているクレームは「その権限は無い」と同じ意味になります）。
 */
export function extractFacts(
  payload: Record<string, unknown>,
  clientId: string = RESOURCE_CLIENT_ID,
): TokenFacts {
  return {
    sub: stringAt(payload, "sub"),
    username: stringAt(payload, "preferred_username"),
    scopes: parseScope(stringAt(payload, "scope")),
    realmRoles: stringsAt(payload, ["realm_access", "roles"]),
    clientRoles: stringsAt(payload, ["resource_access", clientId, "roles"]),
    issuedAt: numberAt(payload, "iat"),
    expiresAt: numberAt(payload, "exp"),
  };
}

/** 1 行の要約。scope とロールを並べて見比べるために使います */
export function factsLine(name: string, facts: TokenFacts): string {
  const scopes = [...facts.scopes].sort().join(" ");
  return `${name}: scope=[${scopes}] realmRoles=[${facts.realmRoles.join(" ")}] clientRoles=[${facts.clientRoles.join(" ")}]`;
}
