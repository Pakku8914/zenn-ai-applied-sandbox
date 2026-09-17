/**
 * ツール定義の「正規化ダイジェスト」
 *
 * 生の tools/list をそのまま比較すると、SDK が自動で足すフィールドやキーの並び順で
 * 落ちます。そこで壊れたら困る約束（名前・引数名・必須かどうか・注釈）だけを抜き出し、
 * 配列の順序まで固定します。この形なら期待値をテストに手で書けます。
 *
 * ★ Python 版（python/src/session13/schema_digest.py）と同じ形・同じキー名で出します。
 *   同じ期待値を 2 つの言語のテストに書けるようにするためです。
 */
export type ArgumentDigest = {
  readonly name: string;
  readonly required: boolean;
  readonly hasDescription: boolean;
};

export type ToolDigest = {
  readonly name: string;
  readonly title: string | null;
  readonly annotations: {
    readonly readOnlyHint: boolean | null;
    readonly destructiveHint: boolean | null;
    readonly idempotentHint: boolean | null;
    readonly openWorldHint: boolean | null;
  };
  readonly args: readonly ArgumentDigest[];
};

/** 文字列比較はコードポイント順に固定する（localeCompare は ICU の版で結果が変わる） */
export function compareStrings(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

export function digestTools(tools: readonly unknown[]): ToolDigest[] {
  return tools
    .map(toDigest)
    .sort((left, right) => compareStrings(left.name, right.name));
}

function toDigest(tool: unknown): ToolDigest {
  const record = asRecord(tool);
  const inputSchema = asRecord(record["inputSchema"]);
  const properties = asRecord(inputSchema["properties"]);
  const required = new Set(asStringArray(inputSchema["required"]));
  const annotations = asRecord(record["annotations"]);

  return {
    name: typeof record["name"] === "string" ? record["name"] : "(unknown)",
    title: typeof record["title"] === "string" ? record["title"] : null,
    annotations: {
      readOnlyHint: asBooleanOrNull(annotations["readOnlyHint"]),
      destructiveHint: asBooleanOrNull(annotations["destructiveHint"]),
      idempotentHint: asBooleanOrNull(annotations["idempotentHint"]),
      openWorldHint: asBooleanOrNull(annotations["openWorldHint"]),
    },
    args: Object.keys(properties)
      .sort(compareStrings)
      .map((name) => ({
        name,
        required: required.has(name),
        // 文面そのものは比較しない（推敲で落ちないように）。「説明があるか」だけを固定する
        hasDescription: typeof asRecord(properties[name])["description"] === "string",
      })),
  };
}

/** 出力スキーマの必須キー（宣言していなければ空配列） */
export function outputRequiredOf(tool: unknown): string[] {
  const outputSchema = asRecord(asRecord(tool)["outputSchema"]);
  return asStringArray(outputSchema["required"]).slice().sort(compareStrings);
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function asBooleanOrNull(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}
