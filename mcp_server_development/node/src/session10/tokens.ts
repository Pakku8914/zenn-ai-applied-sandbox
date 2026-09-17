/**
 * ツール定義のサイズを測るヘルパー
 *
 * 追加の依存を入れずに再現できる方法だけを使います。
 *   - chars  : JSON.stringify した文字数（正確で、何度測っても同じ値）
 *   - tokens : 概算トークン数（下記の近似モデルによる目安）
 */

/**
 * 概算トークン数。
 *
 * ASCII は「4 文字 ≒ 1 トークン」、日本語などの非 ASCII は「1 文字 ≒ 1 トークン」として数えます。
 * 実際のトークナイザとは必ずずれます（この近似の限界は本文で説明します）。
 * 目的は絶対値を当てることではなく、Bad と Good を同じ尺度で比べることです。
 */
export function estimateTokens(text: string): number {
  let ascii = 0;
  let wide = 0;
  for (const ch of text) {
    if ((ch.codePointAt(0) ?? 0) < 128) ascii++;
    else wide++;
  }
  return Math.ceil(ascii / 4) + wide;
}

export type ToolSize = { name: string; chars: number; tokens: number };

export type Measured = { rows: ToolSize[]; totalChars: number; totalTokens: number };

export function measureTools(tools: Array<{ name: string }>): Measured {
  const rows = tools
    .map((tool) => {
      const json = JSON.stringify(tool);
      return { name: tool.name, chars: json.length, tokens: estimateTokens(json) };
    })
    .sort((a, b) => (a.name < b.name ? -1 : 1));
  return {
    rows,
    totalChars: rows.reduce((sum, row) => sum + row.chars, 0),
    totalTokens: rows.reduce((sum, row) => sum + row.tokens, 0),
  };
}

/** ツール定義 1 本を部位ごとに分解する。どこが太っているかを特定するために使います */
export function breakdown(tool: Record<string, unknown>): Record<string, number> {
  const parts: Record<string, number> = {};
  for (const [key, value] of Object.entries(tool)) {
    // JSON.stringify(undefined) は文字列ではなく undefined を返すので、
    // 値が undefined のキー（SDK が付ける任意フィールド）は 0 として数える
    parts[key] = JSON.stringify(value)?.length ?? 0;
  }
  return parts;
}
