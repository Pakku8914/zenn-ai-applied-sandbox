// 問題1: URL を部品に分解し、「サーバーに届く部分」を取り出す。

export type UrlSummary = {
  origin: string;
  requestTarget: string;
  fragment: string;
};

/**
 * リクエストとして送られるのは「パス + クエリ」だけ。
 * フラグメント（#以降）はブラウザの中だけで使われ、サーバーには届かない。
 */
export function toRequestTarget(input: string): string {
  const url = new URL(input);
  return `${url.pathname}${url.search}`;
}

export function summarizeUrl(input: string): UrlSummary {
  const url = new URL(input);

  return {
    origin: url.origin,
    requestTarget: toRequestTarget(input),
    fragment: url.hash === '' ? '(なし)' : url.hash,
  };
}

export function formatUrlSummary(input: string): string {
  const summary = summarizeUrl(input);

  return [
    `origin: ${summary.origin}`,
    `サーバーに届く部分: ${summary.requestTarget}`,
    `ブラウザだけが使う部分: ${summary.fragment}`,
  ].join('\n');
}

/** クエリの page を読む。無い・整数でない・1未満のときは 1 にする */
export function readPageNumber(input: string): number {
  const url = new URL(input);
  const raw = url.searchParams.get('page');

  if (raw === null) {
    return 1;
  }
  const value = Number(raw);
  return Number.isInteger(value) && value >= 1 ? value : 1;
}
