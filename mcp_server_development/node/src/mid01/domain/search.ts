/**
 * 社内ドキュメント検索 ― 全文検索とスコアリング（ドメイン層）
 *
 * 検索ライブラリを使わず、標準の文字列操作だけで実装しています。理由は 3 つです。
 *   ① 数千件までは素朴な実装で十分に速い
 *   ② 依存が増えると配布時（セッション14）に利用者へ要求するものが増える
 *   ③ スコアリングを自分で書くと「並び順を自分で制御できる」
 *
 * 失敗は例外ではなく { ok: false, message } で返します。呼び出し側（MCP 層）が
 * ツールの isError に翻訳するため、例外にする必要がありません。
 */
import { type DocRepository, compareStrings } from "./doc-repository.js";

/** 一致した場所ごとの重み。タイトル＞見出し＞本文 */
export const SCORE_TITLE = 5;
export const SCORE_HEADING = 3;
export const SCORE_BODY = 1;

export const DEFAULT_LIMIT = 5;
export const MAX_LIMIT = 20;
export const MAX_QUERY_LENGTH = 100;
/** 空白区切りで受け付ける語数の上限 */
export const MAX_TERMS = 5;
/** 抜粋の最大文字数（コードポイント数） */
export const SNIPPET_LENGTH = 60;

export type SearchHit = {
  readonly path: string;
  readonly uri: string;
  readonly title: string;
  readonly score: number;
  readonly matchCount: number;
  readonly snippet: string;
};

export type SearchResult = {
  readonly query: string;
  readonly terms: string[];
  readonly directory: string | undefined;
  /** 上限を適用する前の一致件数 */
  readonly totalMatched: number;
  readonly returned: number;
  readonly truncated: boolean;
  readonly hits: SearchHit[];
};

export type SearchOutcome =
  | { readonly ok: true; readonly result: SearchResult }
  | { readonly ok: false; readonly message: string };

export function searchDocuments(
  repository: DocRepository,
  params: { query: string; limit?: number; directory?: string },
): SearchOutcome {
  const parsed = parseQuery(params.query);
  if (!parsed.ok) {
    return { ok: false, message: parsed.message };
  }
  const limit = clampLimit(params.limit);

  // ディレクトリの検証。存在しない値なら「指定できる値」を添えて返す
  const requested = params.directory?.trim() ?? "";
  let scope: string | undefined;
  if (requested.length > 0) {
    const known = repository.listDirectories();
    if (!known.includes(requested)) {
      return {
        ok: false,
        message:
          `directory に指定できるのは ${known.join(" / ")} のいずれかです` +
          "（省略すると公開ディレクトリ全体を検索します）。",
      };
    }
    scope = requested;
  }

  const hits: SearchHit[] = [];
  for (const meta of repository.listDocuments()) {
    if (scope !== undefined && !meta.relativePath.startsWith(`${scope}/`)) {
      continue;
    }
    // 索引に載っていても検証で落ちる名前のファイル（例: 日本語名）は検索対象外
    let text: string;
    try {
      text = repository.readDocument(meta.relativePath).text;
    } catch {
      continue;
    }

    const { score, matchCount } = scoreDocument(text, parsed.terms);
    if (score === 0) {
      continue;
    }
    hits.push({
      path: meta.relativePath,
      uri: meta.uri,
      title: meta.title,
      score,
      matchCount,
      snippet: buildSnippet(text, parsed.terms[0] ?? ""),
    });
  }

  // スコア降順 → パス昇順。第 2 キーが無いと同点の並びが実行環境で揺れる
  hits.sort((a, b) => b.score - a.score || compareStrings(a.path, b.path));

  const limited = hits.slice(0, limit);
  return {
    ok: true,
    result: {
      query: parsed.terms.join(" "),
      terms: parsed.terms,
      directory: scope,
      totalMatched: hits.length,
      returned: limited.length,
      truncated: hits.length > limited.length,
      hits: limited,
    },
  };
}

export function parseQuery(
  raw: string,
): { ok: true; terms: string[] } | { ok: false; message: string } {
  // JavaScript の \s は全角空白（U+3000）も含む
  const normalized = raw.trim().replace(/\s+/g, " ");
  if (normalized.length === 0) {
    return { ok: false, message: "検索語を 1 文字以上で指定してください。" };
  }
  if (normalized.length > MAX_QUERY_LENGTH) {
    return {
      ok: false,
      message: `検索語は ${MAX_QUERY_LENGTH} 文字以内で指定してください。`,
    };
  }
  return { ok: true, terms: normalized.split(" ").slice(0, MAX_TERMS) };
}

export function clampLimit(limit: number | undefined): number {
  if (limit === undefined || !Number.isFinite(limit)) {
    return DEFAULT_LIMIT;
  }
  return Math.min(MAX_LIMIT, Math.max(1, Math.trunc(limit)));
}

export type DocumentParts = { title: string; headings: string; body: string };

/** 文書をタイトル・見出し・本文の 3 つに分ける（重み付けの単位） */
export function splitDocument(text: string): DocumentParts {
  const titleLines: string[] = [];
  const headingLines: string[] = [];
  const bodyLines: string[] = [];
  let titleFound = false;

  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!titleFound && trimmed.startsWith("# ")) {
      titleLines.push(trimmed.slice(2));
      titleFound = true;
    } else if (trimmed.startsWith("#")) {
      headingLines.push(trimmed.replace(/^#+\s*/, ""));
    } else {
      bodyLines.push(line);
    }
  }
  return {
    title: titleLines.join("\n"),
    headings: headingLines.join("\n"),
    body: bodyLines.join("\n"),
  };
}

/** 重なりを数えない出現回数。次の探索開始位置を「一致位置 + 語の長さ」にする */
export function countOccurrences(haystack: string, needle: string): number {
  if (needle.length === 0) {
    return 0;
  }
  let count = 0;
  let index = haystack.indexOf(needle);
  while (index !== -1) {
    count += 1;
    index = haystack.indexOf(needle, index + needle.length);
  }
  return count;
}

/** AND 検索。1 語でも含まない文書はスコア 0（結果に含めない） */
export function scoreDocument(
  text: string,
  terms: readonly string[],
): { score: number; matchCount: number } {
  const parts = splitDocument(text);
  const title = parts.title.toLowerCase();
  const headings = parts.headings.toLowerCase();
  const body = parts.body.toLowerCase();

  let score = 0;
  let matchCount = 0;
  for (const term of terms) {
    const needle = term.toLowerCase();
    const inTitle = countOccurrences(title, needle);
    const inHeadings = countOccurrences(headings, needle);
    const inBody = countOccurrences(body, needle);
    const hits = inTitle + inHeadings + inBody;
    if (hits === 0) {
      return { score: 0, matchCount: 0 };
    }
    score += inTitle * SCORE_TITLE + inHeadings * SCORE_HEADING + inBody * SCORE_BODY;
    matchCount += hits;
  }
  return { score, matchCount };
}

/**
 * 抜粋を作る。タイトル行を除いて最初に一致した行を使う。
 * 「前後 N 文字を切り出す」方式にしないのは、行の途中で切れて読みにくくなり、
 * さらに出力が予測しにくくなる（テストが書けなくなる）ためです。
 */
export function buildSnippet(text: string, term: string): string {
  const needle = term.toLowerCase();
  let titleSeen = false;
  let fallback = "";

  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    const isTitle = !titleSeen && trimmed.startsWith("# ");
    if (isTitle) {
      titleSeen = true;
    }
    // 見出し記号と箇条書き記号を落として本文だけにする
    const plain = trimmed.replace(/^#+\s*/, "").replace(/^[-*]\s+/, "").trim();
    if (plain.length === 0 || !plain.toLowerCase().includes(needle)) {
      continue;
    }
    if (isTitle) {
      if (fallback === "") {
        fallback = plain;
      }
      continue;
    }
    return truncate(plain);
  }
  return truncate(fallback);
}

/** コードポイント単位で切る（サロゲートペアを割らない） */
function truncate(text: string): string {
  const points = [...text];
  return points.length <= SNIPPET_LENGTH
    ? text
    : `${points.slice(0, SNIPPET_LENGTH).join("")}…`;
}
