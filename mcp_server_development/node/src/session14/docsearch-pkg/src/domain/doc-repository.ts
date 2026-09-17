/**
 * 社内ドキュメント検索 ― 文書の走査と読み取り（ドメイン層）
 *
 * 決定的な結果を返すことを最優先に設計しています。
 *   ① 走査の順序を名前順に固定する（readdirSync の返り順に依存しない）
 *   ② 文字列比較をコードポイント順に固定する（localeCompare は ICU の版差がある）
 *   ③ シンボリックリンクを辿らない（公開対象の外を索引に載せない）
 *
 * このファイルも MCP を知りません。失敗は DocAccessError（reason 付き）で表します。
 */
import fs from "node:fs";
import path from "node:path";

import { MAX_DEPTH, REJECT_MESSAGES, type RejectReason, resolveSafeDocPath } from "./safe-path.js";

export const URI_SCHEME = "docs";
/** 索引に載せる文書数の上限（暴走を防ぐための安全弁） */
export const MAX_DOCUMENTS = 500;

export type DocumentMeta = {
  /** 公開ディレクトリからの相対パス（例: "guides/vpn-setup.md"） */
  readonly relativePath: string;
  /** 本文を読み取るための URI（例: "docs://guides/vpn-setup.md"） */
  readonly uri: string;
  /** 最初の "# " 見出し。無ければ相対パス */
  readonly title: string;
  readonly byteSize: number;
  readonly lineCount: number;
};

export type DocumentContent = DocumentMeta & { readonly text: string };

/**
 * ドメイン層のエラー。MCP に依存しないので、テストからそのまま検証できます。
 * reason を持たせているのは、上位で HTTP ステータスや JSON-RPC エラーへ
 * 機械的に翻訳できるようにするためです。
 */
export class DocAccessError extends Error {
  constructor(readonly reason: RejectReason) {
    super(REJECT_MESSAGES[reason]);
    this.name = "DocAccessError";
  }
}

export type DocRepository = {
  readonly root: string;
  toUri(relativePath: string): string;
  listDocuments(): DocumentMeta[];
  listDirectories(): string[];
  /** 外部入力を受け取る唯一の入口。必ず検証を通す */
  readDocument(rawPath: string): DocumentContent;
};

export function createDocRepository(root: string): DocRepository {
  const absoluteRoot = path.resolve(root);

  function toUri(relativePath: string): string {
    return `${URI_SCHEME}://${relativePath}`;
  }

  function walk(currentRelative: string, out: string[]): void {
    const depth = currentRelative === "" ? 0 : currentRelative.split("/").length;
    // これ以上潜るとファイルの区間数が MAX_DEPTH を超える
    if (depth >= MAX_DEPTH) {
      return;
    }

    const currentAbsolute =
      currentRelative === "" ? absoluteRoot : path.join(absoluteRoot, currentRelative);

    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(currentAbsolute, { withFileTypes: true });
    } catch {
      // 権限が無い・途中で消えた、などは黙って読み飛ばす（一覧が壊れないようにする）
      return;
    }
    // 返り順はファイルシステム依存。必ず並べ替える
    entries.sort((a, b) => compareStrings(a.name, b.name));

    for (const entry of entries) {
      // シンボリックリンクは辿らない。公開対象の外にあるファイルを索引に載せないため
      if (entry.isSymbolicLink()) {
        continue;
      }
      if (entry.name.startsWith(".")) {
        continue;
      }
      const relative =
        currentRelative === "" ? entry.name : `${currentRelative}/${entry.name}`;
      if (entry.isDirectory()) {
        walk(relative, out);
      } else if (entry.isFile() && entry.name.toLowerCase().endsWith(".md")) {
        out.push(relative);
        if (out.length >= MAX_DOCUMENTS) {
          return;
        }
      }
    }
  }

  function listDocuments(): DocumentMeta[] {
    const relatives: string[] = [];
    walk("", relatives);
    relatives.sort(compareStrings);
    return relatives.map((relative) => {
      const text = fs.readFileSync(path.join(absoluteRoot, relative), "utf8");
      return buildMeta(relative, text, toUri(relative));
    });
  }

  function listDirectories(): string[] {
    const found = new Set<string>();
    for (const meta of listDocuments()) {
      const segments = meta.relativePath.split("/");
      segments.pop();
      if (segments.length > 0) {
        found.add(segments.join("/"));
      }
    }
    return [...found].sort(compareStrings);
  }

  function readDocument(rawPath: string): DocumentContent {
    // 索引から来たパスであっても検証を通す。入口を 1 つに絞ると穴が空きにくい
    const resolved = resolveSafeDocPath(absoluteRoot, rawPath);
    if (!resolved.ok) {
      throw new DocAccessError(resolved.reason);
    }
    const text = fs.readFileSync(resolved.absolutePath, "utf8");
    return {
      ...buildMeta(resolved.relativePath, text, toUri(resolved.relativePath)),
      text,
    };
  }

  return { root: absoluteRoot, toUri, listDocuments, listDirectories, readDocument };
}

/** コードポイント順の比較。localeCompare は ICU の版で結果が変わりうるため使わない */
export function compareStrings(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

export function extractTitle(text: string, fallback: string): string {
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    // "# " （シャープ＋半角空白）で判定する。"##" を誤って拾わない
    if (trimmed.startsWith("# ")) {
      return trimmed.slice(2).trim();
    }
  }
  return fallback;
}

function buildMeta(relativePath: string, text: string, uri: string): DocumentMeta {
  return {
    relativePath,
    uri,
    title: extractTitle(text, relativePath),
    byteSize: Buffer.byteLength(text, "utf8"),
    // 末尾の改行で 1 増えるのを防ぐ
    lineCount: text.trimEnd().split("\n").length,
  };
}
