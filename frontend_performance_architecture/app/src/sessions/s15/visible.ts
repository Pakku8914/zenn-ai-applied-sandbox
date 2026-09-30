/**
 * S15：描画結果の HTML から「利用者に見えるもの」だけを取り出す小さな道具。
 * クラス名・style・要素の入れ子といった実装の都合は見ずに、テキスト・役割・件数で検査するために使う。
 * 実務では Testing Library（getByRole / getByText）が同じ考え方をアクセシビリティツリーで正確に行う。
 */
export type Role = 'button' | 'heading' | 'listitem' | 'textbox';

// 役割ごとに、その役割を持つ要素のタグ名（本章の画面で使うものだけ）
const TAG: Record<Role, string> = {
  button: 'button',
  heading: 'h[1-6]',
  listitem: 'li',
  textbox: 'input',
};

/** タグとコメントを取り除き、空白をまとめた「見えている文字」 */
export function textOf(html: string): string {
  return html
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/** 指定した役割を持つ要素の数 */
export function countRole(html: string, role: Role): number {
  return (html.match(new RegExp(`<(?:${TAG[role]})(?=[\\s>/])`, 'g')) ?? []).length;
}

/** 指定した役割を持つ要素それぞれの「見えている文字」（入力欄は中身を持たないので対象外） */
export function textsOf(html: string, role: Exclude<Role, 'textbox'>): string[] {
  const pattern = new RegExp(`<(${TAG[role]})(?=[\\s>])[^>]*>([\\s\\S]*?)</\\1>`, 'g');
  return [...html.matchAll(pattern)].map((m) => textOf(m[2] ?? ''));
}
