import {
  DEFAULT_QUERY,
  decideHistoryMode,
  type CatalogQuery,
  type CategoryOption,
} from '../s09/catalogQuery';

/** 横断復習③ 問題3：絞り込み画面での利用者の操作 */
export type CatalogOp =
  | { kind: 'typing'; keyword: string }
  | { kind: 'commit'; category: CategoryOption }
  | { kind: 'blur' };

/**
 * 操作の列を S09 の規則（decideHistoryMode・同じ URL は積まない）で再生し、
 * 最後に残る履歴の並び（古い順）を返す。URL を DOM なしで確かめるための純粋関数。
 */
export function traceHistory(ops: readonly CatalogOp[]): CatalogQuery[] {
  const entries: CatalogQuery[] = [{ ...DEFAULT_QUERY }];
  let typing = false;
  for (const op of ops) {
    if (op.kind === 'blur') {
      typing = false; // 入力の確定。次の1文字は新しい履歴になる
      continue;
    }
    const current = entries[entries.length - 1] ?? DEFAULT_QUERY;
    const next: CatalogQuery =
      op.kind === 'typing' ? { ...current, keyword: op.keyword } : { ...current, category: op.category };
    const mode = decideHistoryMode(typing, op.kind);
    typing = op.kind === 'typing';
    if (next.keyword === current.keyword && next.category === current.category) continue;
    if (mode === 'push') entries.push(next);
    else entries[entries.length - 1] = next;
  }
  return entries;
}

/** 履歴の1件を読みやすい文字列にする（例：「商品1｜文具」） */
export function labelOf(query: CatalogQuery): string {
  return `${query.keyword === '' ? '（空）' : query.keyword}｜${query.category}`;
}
