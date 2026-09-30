/**
 * 中間プロジェクトの擬似タグ（計測タグと検索ログ SDK の代わり）。
 * 本物のタグは読み込まない（外部サイトへのアクセスを前提にしないため）。
 * 中身の処理の代わりに、決まった時間だけメインスレッドを占有する。
 * 教材用の再現コードなので、本番のコードでこのような待ち方をしてはいけない。
 */

/** ページ全体の計測タグが占有する時間。出題版では同じ処理が HTML の <head> にインラインで書いてある */
export const PAGE_TAG_MS = 300;
/** 検索ログ SDK が 1 回の送信で占有する時間（送信データを同期で組み立てる想定） */
export const SEARCH_LOG_MS = 250;

function occupy(ms: number): void {
  const end = performance.now() + ms;
  while (performance.now() < end) {
    // 何もしない（メインスレッドを占有することだけが目的）
  }
}

export function runPageTag(): void {
  occupy(PAGE_TAG_MS);
}

declare global {
  interface Window {
    /** 検証用：送信した検索ログのキーワードを順に記録する（measure 側が読む） */
    __mid01?: { searchLogs: string[] };
  }
}

export function sendSearchLog(keyword: string): void {
  occupy(SEARCH_LOG_MS);
  const state = (window.__mid01 ??= { searchLogs: [] });
  state.searchLogs.push(keyword);
}
