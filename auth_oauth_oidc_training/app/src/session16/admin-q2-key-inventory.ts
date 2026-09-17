// 問題 2 の解答: いま鍵が何本あるかを、外からの見え方と内側の見え方の両方で棚卸しします。
// 「外から見ると、回す前と回し終えた後の区別が付かない」ことが分かるのが要点です。
import {
  activeSigningKeys,
  fetchAdminToken,
  fetchManagedKeys,
  fetchPublishedKeys,
  kidsOf,
  signingKeys,
} from "./bookstore-keys.js";
import type { ManagedKey, PublishedKey } from "./bookstore-keys.js";

/** 外から観察できる段階。single と retired は外からは区別できません */
export type ObservedStage = "no-key" | "single" | "overlap";

export function observedStage(publishedSigningKids: readonly string[]): ObservedStage {
  if (publishedSigningKids.length === 0) return "no-key";
  return publishedSigningKids.length === 1 ? "single" : "overlap";
}

export type Inventory = {
  /** JWKS に載っている RS256 の署名鍵 */
  readonly publishedSigningKids: readonly string[];
  /** 内部で ACTIVE な署名鍵（対称鍵も含む） */
  readonly internalActiveSigKids: readonly string[];
  /** 内部にはあるのに JWKS に出ない鍵の方式（対称鍵はここに出ます） */
  readonly internalOnlyAlgorithms: readonly string[];
  readonly stage: ObservedStage;
};

/** 外からの一覧と内側の一覧を突き合わせます */
export function buildInventory(published: readonly PublishedKey[], managed: readonly ManagedKey[]): Inventory {
  const publishedSigningKids = kidsOf(signingKeys(published));
  const activeSig = activeSigningKeys(managed);
  const publishedKids = new Set(kidsOf(published));
  const internalOnly = activeSig.filter((key) => !publishedKids.has(key.kid));
  return {
    publishedSigningKids,
    internalActiveSigKids: activeSig.map((key) => key.kid),
    internalOnlyAlgorithms: [...new Set(internalOnly.map((key) => key.algorithm))].sort(),
    stage: observedStage(publishedSigningKids),
  };
}

/** 段階ごとに「いま何をしてはいけないか」を言い当てます */
export function nextAction(stage: ObservedStage): string {
  if (stage === "no-key") return "検証できる鍵が 1 本も無い。まず鍵を載せる";
  if (stage === "single") {
    return "鍵は 1 本。いま消すとすべてのトークンが検証できなくなるので、足すことしかできない";
  }
  return "鍵が 2 本以上ある。古い kid のトークンが切れるまで待ってから、古い鍵を外す";
}

/** 実際の認可サーバーを 2 通りの目で見ます */
export async function fetchInventory(): Promise<Inventory> {
  const published = await fetchPublishedKeys();
  const managed = await fetchManagedKeys(await fetchAdminToken());
  return buildInventory(published, managed);
}
