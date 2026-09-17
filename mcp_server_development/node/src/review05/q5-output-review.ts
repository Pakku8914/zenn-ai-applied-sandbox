/**
 * 応答レビュー ―― ツール結果を機械的に検査する（問題5）
 *
 * ネットワークにも LLM にも触れません。文字列検査だけで判定するので、
 * CI で毎回走らせても数ミリ秒で終わります。
 */
import {
  countSecrets,
  countUntrustedBlocks,
  detectDirectives,
  type DirectiveId,
} from "./guard-lite.js";

export const DEFAULT_MAX_CHARS = 2000;

export type OutputReviewOptions = {
  readonly maxChars?: number;
  /** 外部データを含まない応答（一覧など）を検査するときは false にする */
  readonly requireBoundary?: boolean;
};

export type OutputReview = {
  readonly ok: boolean;
  readonly chars: number;
  readonly untrustedBlocks: number;
  readonly directives: readonly DirectiveId[];
  readonly secretHits: number;
  readonly problems: readonly string[];
};

export function reviewToolResult(
  payload: string,
  options: OutputReviewOptions = {},
): OutputReview {
  const maxChars = options.maxChars ?? DEFAULT_MAX_CHARS;
  const requireBoundary = options.requireBoundary ?? true;

  const chars = [...payload].length;
  const untrustedBlocks = countUntrustedBlocks(payload);
  const directives = [...new Set(detectDirectives(payload).map((finding) => finding.id))].sort();
  const secretHits = countSecrets(payload);

  // 並び順は「検査した順」に固定する（辞書順に並べ替えない）。
  // 読む人が毎回同じ順序で読めることのほうが、並びの美しさより価値がある
  const problems: string[] = [];
  if (requireBoundary && untrustedBlocks === 0) {
    problems.push("外部データが信頼境界で囲まれていません");
  }
  if (directives.length > 0) {
    problems.push(`指示文が残っています: ${directives.join(", ")}`);
  }
  if (secretHits > 0) {
    problems.push(`秘密情報らしき文字列が ${secretHits} 件あります`);
  }
  if (chars > maxChars) {
    problems.push(`応答が上限 ${maxChars} 文字を超えています`);
  }

  return { ok: problems.length === 0, chars, untrustedBlocks, directives, secretHits, problems };
}
