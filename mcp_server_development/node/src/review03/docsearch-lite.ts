/**
 * 横断復習3 の共通題材 ―― 社内ドキュメント検索（ドメイン層の縮小版）
 *
 * 中間プロジェクト1 の domain/ 配下を、ファイルシステムなしで再現しています。
 * MCP には依存しません（プロトコルの機構とドメインロジックを分ける、の実践）。
 *
 * スコアリングは省いています（本章の主題ではないため）。並び順はパスの昇順で固定し、
 * 同じ入力なら必ず同じ順序で返します ―― ページネーションの前提条件です。
 */

export type DocEntry = {
  readonly path: string;
  readonly title: string;
  readonly body: string;
};

/** 公開する文書 5 件。パスの昇順で保持する（一覧・検索・ページの順序を決定的にするため） */
export const DOCS: readonly DocEntry[] = [
  {
    path: "faq/account-lock.md",
    title: "アカウントロックのよくある質問",
    body: [
      "パスワードを 5 回連続で間違えるとアカウントがロックされます。",
      "ロックは 30 分で自動的に解除されます。",
      "急ぎの場合はヘルプデスクへ連絡してください。",
    ].join("\n"),
  },
  {
    path: "guides/vpn-setup.md",
    title: "VPN 接続手順",
    body: [
      "社外から社内システムへ接続するための手順です。",
      "VPN クライアントは情報システム部の配布ページから取得します。",
      "認証には社内アカウントの ID とパスワードを使用します。",
    ].join("\n"),
  },
  {
    path: "onboarding.md",
    title: "入社時セットアップ手順",
    body: [
      "初日に社内アカウントを受け取り、初期パスワードを当日中に変更します。",
      "社外から社内システムへ接続する場合は VPN が必要です。",
    ].join("\n"),
  },
  {
    path: "remote-work.md",
    title: "リモートワーク規程",
    body: [
      "リモートワークは上長の承認を受けた社員が利用できます。",
      "VPN に接続していない状態では社内システムへアクセスできません。",
      "公衆無線 LAN での業務は禁止です。",
    ].join("\n"),
  },
  {
    path: "security-policy.md",
    title: "情報セキュリティ基本方針",
    body: [
      "パスワードは 12 文字以上とし、他のサービスと使い回さないでください。",
      "社外ネットワークから社内システムへ接続する場合は必ず VPN を使用します。",
    ].join("\n"),
  },
];

export const DEFAULT_LIMIT = 5;
export const MAX_LIMIT = 20;
export const MAX_QUERY_LENGTH = 100;
export const URI_SCHEME = "docs";

export function toUri(path: string): string {
  return `${URI_SCHEME}://${path}`;
}

export function listPaths(): string[] {
  return DOCS.map((doc) => doc.path);
}

/** 補完の候補（前方一致）。絞り込みはサーバー側の責務なのでここで行う */
export function completePaths(prefix: string): string[] {
  const needle = prefix.trim().toLowerCase();
  return listPaths().filter((path) => path.toLowerCase().startsWith(needle));
}

export type SearchHit = { path: string; uri: string; title: string };

export type SearchOutcome = {
  query: string;
  directory?: string;
  totalMatched: number;
  returned: number;
  truncated: boolean;
  results: SearchHit[];
};

/** タイトルと本文の部分一致で検索する（大文字小文字を区別しない） */
export function searchDocuments(params: {
  query: string;
  limit?: number;
  directory?: string;
}): SearchOutcome {
  const query = params.query.trim();
  const limit = params.limit ?? DEFAULT_LIMIT;
  const needle = query.toLowerCase();
  const scoped =
    params.directory === undefined
      ? DOCS
      : DOCS.filter((doc) => doc.path.startsWith(`${params.directory}/`));
  // 空文字は includes() が常に true になり全件ヒットするので、ここで止める
  const matched =
    needle.length === 0
      ? []
      : scoped.filter((doc) => `${doc.title}\n${doc.body}`.toLowerCase().includes(needle));
  const page = matched.slice(0, limit);
  return {
    query,
    // undefined を入れると outputSchema の検証に落ちる。キー自体を作らない
    ...(params.directory === undefined ? {} : { directory: params.directory }),
    totalMatched: matched.length,
    returned: page.length,
    truncated: matched.length > page.length,
    results: page.map((doc) => ({ path: doc.path, uri: toUri(doc.path), title: doc.title })),
  };
}

/**
 * URI 変数から受け取った path の許可リスト。
 * 「1 階層までのディレクトリ ＋ .md」だけを許します。実ファイルを触らないので
 * realpath の検査はありませんが、考え方は中間プロジェクト1 と同じです。
 */
const PATH_PATTERN = /^(?:[a-z0-9][a-z0-9-]{0,39}\/)?[a-z0-9][a-z0-9-]{0,39}\.md$/;

export type RejectReason = "decode_failed" | "invalid_pattern" | "not_found";

/** 拒否の文面は固定。受け取った値やサーバー内部の情報を含めない */
export const REJECT_MESSAGES: Record<RejectReason, string> = {
  decode_failed: "path をデコードできません。docs://guides/vpn-setup.md の形式で指定してください。",
  invalid_pattern:
    "許可されていない path です。docs://guides/vpn-setup.md の形式で指定してください。",
  not_found: "その path の文書はありません。search_documents で候補を確認してください。",
};

export type ResolveResult =
  | { readonly ok: true; readonly doc: DocEntry }
  | { readonly ok: false; readonly reason: RejectReason };

export function resolveDoc(raw: string): ResolveResult {
  let decoded: string;
  try {
    // パーセントデコードは 1 回だけ。2 回行うと %252f のような二重エンコードを通してしまう
    decoded = decodeURIComponent(raw);
  } catch {
    return { ok: false, reason: "decode_failed" };
  }
  if (!PATH_PATTERN.test(decoded)) {
    return { ok: false, reason: "invalid_pattern" };
  }
  const doc = DOCS.find((entry) => entry.path === decoded);
  return doc === undefined ? { ok: false, reason: "not_found" } : { ok: true, doc };
}

/** 文書 1 件を Markdown にする（常に 5 行以上） */
export function renderDocMarkdown(doc: DocEntry): string {
  return [`# ${doc.title}`, "", `- パス: ${doc.path}`, "", doc.body].join("\n");
}
