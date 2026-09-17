// セッション20「WebとHTTPの基礎・Node.jsサーバー」
//
// レスポンスを「curl -i」と同じ形（ステータス行 → ヘッダ → 空行 → 本文）に整形する。
// ヘッダの並び順は環境で変わるので、名前で並べ替えて出力を安定させる。

/** ステータス行・ヘッダ・本文を1つの文字列にする */
export function formatResponse(
  status: number,
  statusText: string,
  headerLines: readonly string[],
  body: string
): string {
  return [`HTTP/1.1 ${status} ${statusText}`, ...[...headerLines].toSorted(), '', body].join('\n');
}
