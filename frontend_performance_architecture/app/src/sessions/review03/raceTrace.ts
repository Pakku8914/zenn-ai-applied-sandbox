import { createLatestOnly } from '../s10/latest';

/** 横断復習③ 問題3：1回の取得（開始時刻と、応答が返るまでの時間） */
export type FetchCall = { keyword: string; startMs: number; durationMs: number };

/** 画面の表示が変わった瞬間 */
export type ShownChange = { atMs: number; keyword: string };

/**
 * 取得の開始と応答の到着を時刻順に再生し、画面に表示されたキーワードの移り変わりを返す。
 * guard が true なら S10 の createLatestOnly で「最後に始めた取得」だけを採用する。
 */
export function traceShown(calls: readonly FetchCall[], guard: boolean): ShownChange[] {
  type Event = { atMs: number; type: 'start' | 'arrive'; index: number };
  const events: Event[] = calls.flatMap((c, index) => [
    { atMs: c.startMs, type: 'start' as const, index },
    { atMs: c.startMs + c.durationMs, type: 'arrive' as const, index },
  ]);
  events.sort((a, b) => a.atMs - b.atMs);

  const latest = createLatestOnly();
  const isLatest = new Map<number, () => boolean>();
  const shown: ShownChange[] = [];
  for (const e of events) {
    const call = calls[e.index];
    if (call === undefined) continue;
    if (e.type === 'start') {
      isLatest.set(e.index, latest.begin());
      continue;
    }
    if (guard && !(isLatest.get(e.index)?.() ?? false)) continue; // 古い応答は捨てる
    shown.push({ atMs: e.atMs, keyword: call.keyword });
  }
  return shown;
}
