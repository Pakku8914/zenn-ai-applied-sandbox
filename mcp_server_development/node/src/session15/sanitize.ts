/**
 * 外部データの無害化（サニタイズ）と信頼境界の明示
 *
 * このモジュールは MCP を知りません（SDK を import しません）。
 * 「文字列を受け取って文字列を返す」だけなので、テストが速く、HTTP API からも
 * 同じ関数を使えます。中間プロジェクト1 で守った「ドメイン層は MCP を知らない」
 * という方針を、セキュリティ部品にも適用しています。
 */
import { randomBytes } from "node:crypto";

/** 指示の上書きを狙うイディオムの識別子。監査ログにはこの値を残す */
export type DirectiveId =
  | "override_instructions"
  | "override_instructions_en"
  | "system_prompt_probe"
  | "credential_exfiltration"
  | "tool_invocation";

export type DirectivePattern = { readonly id: DirectiveId; readonly pattern: RegExp };

/**
 * 検出パターン。すべて g フラグ付きで定義しています。
 *
 * g 付きの正規表現は test() / exec() を呼ぶと lastIndex が進み、次回の結果が
 * 変わります（同じ入力で結果が違う、という最悪のバグになる）。このモジュールでは
 * matchAll() と replace() だけを使います。どちらも lastIndex を汚しません。
 */
export const DIRECTIVE_PATTERNS: readonly DirectivePattern[] = [
  {
    id: "override_instructions",
    pattern:
      /(?:これまで|今まで|以前|上記|先ほど)の(?:指示|命令|ルール|プロンプト)[^。\n]{0,24}?(?:無視|忘れ|破棄|上書き)/g,
  },
  {
    id: "override_instructions_en",
    pattern:
      /ignore\s+(?:all\s+)?(?:previous|prior|above|earlier)\s+(?:instructions?|prompts?|rules?)/gi,
  },
  {
    id: "system_prompt_probe",
    pattern:
      /(?:システムプロンプト|初期プロンプト|system\s*prompt)[^。\n]{0,24}?(?:出力|表示|教え|返し|reveal|print|repeat)/gi,
  },
  {
    id: "credential_exfiltration",
    pattern:
      /(?:トークン|APIキー|API\s*キー|認証情報|パスワード|credentials?|secrets?)[^。\n]{0,24}?(?:送信|送って|貼り付け|投稿|アップロード|send|post)/gi,
  },
  {
    id: "tool_invocation",
    pattern:
      /(?:ツール|tool)[^。\n]{0,24}?(?:必ず呼び出|かならず呼び出|呼び出してください|実行してください|call\s+this)/gi,
  },
];

export const DIRECTIVE_PLACEHOLDER = "[指示文を除去]";

/** 命令形の文末。サニタイズでは消せない「残余」を数えるために使う */
const IMPERATIVE_PATTERN = /(?:ください|下さい|しなさい)/g;

/**
 * 見えない文字（ゼロ幅・双方向制御・BOM）のコードポイント。
 * 正規表現の文字クラスに書くと、ソースコードに「見えない文字」が紛れ込んで
 * レビューできなくなります。だからコードポイントの集合として持ちます。
 */
const INVISIBLE_CODE_POINTS: ReadonlySet<number> = new Set([
  0x00ad, // SOFT HYPHEN
  ...range(0x200b, 0x200f), // ZERO WIDTH SPACE 〜 RIGHT-TO-LEFT MARK
  ...range(0x202a, 0x202e), // 双方向制御（表示順を入れ替えられる）
  ...range(0x2060, 0x2064), // WORD JOINER 〜 INVISIBLE PLUS
  ...range(0x2066, 0x2069), // 双方向分離
  0xfeff, // BOM
]);

/** 境界マーカーやコードフェンスの偽装に使える記号の連続 */
const MARKER_PATTERN = /[<>]{2,}|`{3,}/g;

function range(from: number, to: number): number[] {
  return Array.from({ length: to - from + 1 }, (_, index) => from + index);
}

/** 制御文字か（タブ・改行・復帰は別に処理するので除く） */
function isControlCodePoint(codePoint: number): boolean {
  if (codePoint === 0x09 || codePoint === 0x0a || codePoint === 0x0d) {
    return false;
  }
  return codePoint <= 0x1f || codePoint === 0x7f;
}

/** 見えない文字と制御文字を落とす。落とした数も返す（監査ログに残すため） */
export function stripInvisible(text: string): { text: string; removed: number } {
  let out = "";
  let removed = 0;
  for (const character of text) {
    const codePoint = character.codePointAt(0) ?? 0;
    if (isControlCodePoint(codePoint) || INVISIBLE_CODE_POINTS.has(codePoint)) {
      removed += 1;
      continue;
    }
    out += character;
  }
  return { text: out, removed };
}

export type Finding = { readonly id: DirectiveId; readonly index: number; readonly text: string };

/** 検出だけを行う（置き換えはしない）。index はサニタイズ前の位置 */
export function detectDirectives(text: string): Finding[] {
  const findings: Finding[] = [];
  for (const { id, pattern } of DIRECTIVE_PATTERNS) {
    for (const match of text.matchAll(pattern)) {
      findings.push({ id, index: match.index ?? 0, text: match[0] });
    }
  }
  return findings.sort(
    (a, b) => a.index - b.index || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0),
  );
}

export type SanitizeOptions = {
  /** 上限（コードポイント数）。既定 400 */
  readonly maxLength?: number;
  /** 改行を保持するか。既定 false（1 行に畳む） */
  readonly keepNewlines?: boolean;
};

export type SanitizeReport = {
  readonly text: string;
  readonly findings: readonly Finding[];
  readonly removedInvisible: number;
  readonly neutralizedMarkers: number;
  readonly truncated: boolean;
};

export const DEFAULT_MAX_LENGTH = 400;

export function sanitizeExternalText(
  raw: string,
  options: SanitizeOptions = {},
): SanitizeReport {
  const maxLength = options.maxLength ?? DEFAULT_MAX_LENGTH;
  const keepNewlines = options.keepNewlines ?? false;

  // ① 見えない文字と制御文字を落とす。人間には見えないがモデルには読める文字を消す
  const stripped = stripInvisible(raw);
  const removedInvisible = stripped.removed;
  let text = stripped.text;

  // ② 改行の扱い。1 行に畳むと「疑似システムメッセージ」を組み立てられなくなる
  text = keepNewlines ? text.replace(/\r\n?/g, "\n") : text.replace(/[\r\n\t]+/g, " ");

  // ③ 境界マーカーの偽装に使える記号の連続を無効化する（境界を閉じられないようにする）
  const neutralizedMarkers = text.match(MARKER_PATTERN)?.length ?? 0;
  text = text.replace(MARKER_PATTERN, "");

  // ④ 空白を詰める（改行を保持する場合は改行を残す）
  text = keepNewlines ? text.replace(/[^\S\n]{2,}/g, " ") : text.replace(/\s{2,}/g, " ");
  text = text.trim();

  // ⑤ 指示文を検出してから置き換える。検出結果は監査ログに残すので先に取る
  const findings = detectDirectives(text);
  for (const { pattern } of DIRECTIVE_PATTERNS) {
    text = text.replace(pattern, DIRECTIVE_PLACEHOLDER);
  }

  // ⑥ 長さの上限。巨大な文書を丸ごとコンテキストへ流し込まれないようにする
  const points = [...text];
  const truncated = points.length > maxLength;
  if (truncated) {
    text = `${points.slice(0, maxLength).join("")}…`;
  }

  return { text, findings, removedInvisible, neutralizedMarkers, truncated };
}

export type UntrustedBoundary = {
  readonly nonce: string;
  readonly begin: string;
  readonly end: string;
};

/** 応答ごとに作り直す 1 回限りの識別子。事前に用意された文書には書けない */
export function newNonce(): string {
  return randomBytes(8).toString("hex");
}

export function createUntrustedBoundary(nonce: string): UntrustedBoundary {
  return {
    nonce,
    begin: `<<<UNTRUSTED-DATA ${nonce} BEGIN>>>`,
    end: `<<<UNTRUSTED-DATA ${nonce} END>>>`,
  };
}

export type TrustLabel = {
  readonly source: string;
  readonly level: "low" | "medium";
  readonly note: string;
};

/** 外部データを境界で囲み、出所と信頼レベルを添える */
export function wrapUntrusted(
  boundary: UntrustedBoundary,
  label: TrustLabel,
  body: string,
): string {
  return [
    boundary.begin,
    `出所: ${label.source}`,
    `信頼レベル: ${label.level === "low" ? "低" : "中"}（${label.note}）`,
    body,
    boundary.end,
  ].join("\n");
}

/** 境界で囲まれた部分だけを取り出す（検証・テスト用） */
export function extractUntrusted(text: string, boundary: UntrustedBoundary): string[] {
  const segments: string[] = [];
  let cursor = 0;
  for (;;) {
    const start = text.indexOf(boundary.begin, cursor);
    if (start === -1) {
      break;
    }
    const bodyStart = start + boundary.begin.length;
    const end = text.indexOf(boundary.end, bodyStart);
    if (end === -1) {
      break;
    }
    segments.push(text.slice(bodyStart, end));
    cursor = end + boundary.end.length;
  }
  return segments;
}

export type OutputInspection = {
  readonly directives: readonly Finding[];
  readonly untrustedBlocks: number;
  readonly imperativesInUntrusted: number;
};

/**
 * サーバーの応答（JSON 文字列でよい）を機械的に検査する。
 * 「指示文が残っているか」「外部データが境界の内側にあるか」を決定的に判定できる。
 */
export function inspectOutput(text: string, boundary?: UntrustedBoundary): OutputInspection {
  const untrusted = boundary === undefined ? [] : extractUntrusted(text, boundary);
  const imperativesInUntrusted = untrusted.reduce(
    (sum, segment) => sum + (segment.match(IMPERATIVE_PATTERN)?.length ?? 0),
    0,
  );
  return {
    directives: detectDirectives(text),
    untrustedBlocks: untrusted.length,
    imperativesInUntrusted,
  };
}
