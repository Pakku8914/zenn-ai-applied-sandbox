/**
 * roots（クライアントが許可した作業ディレクトリ）から検索スコープを決める
 *
 * このファイルは MCP を知りません（@modelcontextprotocol/sdk を import しない）。
 * 受け取るのは「file:// の URI 文字列の配列」という素のデータだけです。
 * 中間プロジェクト1 のドメイン層（safe-path / doc-repository）は書き換えず、
 * 外側から包むことで境界を足します。
 */
import path from "node:path";
import { fileURLToPath } from "node:url";

import { DocAccessError, type DocRepository } from "../../mid01/domain/doc-repository.js";
import { isInside, normalizeDocPath } from "../../mid01/domain/safe-path.js";

export type ScopeSource = "server-config" | "roots";

export type DocScope = {
  readonly source: ScopeSource;
  /** 許可された相対ディレクトリ。[""] は「公開ディレクトリ全体」を意味する */
  readonly directories: readonly string[];
  /** 公開ディレクトリの外を指していたため無視した roots */
  readonly ignoredRoots: readonly string[];
};

/** roots が使えないときの既定。サーバー設定の境界だけを使う */
export const WHOLE_SCOPE: DocScope = {
  source: "server-config",
  directories: [""],
  ignoredRoots: [],
};

/**
 * roots からスコープを作る。公開ディレクトリの中を指す root だけを採用する。
 *
 * 1 つも採用できなかった場合は ok: false を返し、呼び出し側でツールを失敗させます。
 * 「roots が noise だったので全体を検索する」に倒すと、境界の指定が
 * 効かなかったことに誰も気付けません（安全側に倒すとは、止まることです）。
 */
export function resolveScopeFromRoots(
  docsRoot: string,
  roots: readonly { readonly uri: string }[],
): { ok: true; scope: DocScope } | { ok: false; ignoredRoots: readonly string[] } {
  const base = path.resolve(docsRoot);
  const directories = new Set<string>();
  const ignored: string[] = [];

  for (const root of roots) {
    const local = toLocalPath(root.uri);
    if (local === undefined) {
      // file:// 以外（http:// など）は扱えない
      ignored.push(root.uri);
      continue;
    }
    if (local === base) {
      directories.add("");
      continue;
    }
    if (!isInside(base, local)) {
      // ここが要点：外を指す root は無視する。境界は広げない
      ignored.push(root.uri);
      continue;
    }
    directories.add(path.relative(base, local).split(path.sep).join("/"));
  }

  if (directories.size === 0) {
    return { ok: false, ignoredRoots: ignored };
  }
  // 全体が含まれるなら部分指定は冗長なので捨てる
  const list = directories.has("") ? [""] : [...directories].sort();
  return { ok: true, scope: { source: "roots", directories: list, ignoredRoots: ignored } };
}

function toLocalPath(uri: string): string | undefined {
  if (!uri.startsWith("file://")) {
    return undefined;
  }
  try {
    return path.resolve(fileURLToPath(uri));
  } catch {
    // ホスト名付き（file://server/share）などは変換できない
    return undefined;
  }
}

export function describeScope(scope: DocScope): string {
  return scope.directories.includes("")
    ? "(公開ディレクトリ全体)"
    : scope.directories.join(", ");
}

export function isPathInScope(scope: DocScope, relativePath: string): boolean {
  return scope.directories.some(
    (directory) =>
      directory === "" || relativePath === directory || relativePath.startsWith(`${directory}/`),
  );
}

/**
 * リポジトリをスコープで包む（デコレーター）。
 *
 * 検索も読み取りも同じ境界を通るので、境界の実装が 1 か所で済みます。
 * mid01 の searchDocuments() は repository の 3 つのメソッドしか使わないため、
 * 検索側のコードを 1 行も変えずにスコープが効きます。
 */
export function scopeRepository(base: DocRepository, scope: DocScope): DocRepository {
  return {
    root: base.root,
    toUri: (relativePath) => base.toUri(relativePath),
    listDocuments: () =>
      base.listDocuments().filter((meta) => isPathInScope(scope, meta.relativePath)),
    listDirectories: () =>
      base.listDirectories().filter((directory) => isPathInScope(scope, `${directory}/`)),
    readDocument: (rawPath) => {
      const normalized = normalizeDocPath(rawPath);
      // 範囲外なら「読む前に」落とす。ファイルを開いてから捨てるのでは遅い
      if (normalized.ok && !isPathInScope(scope, normalized.relativePath)) {
        throw new DocAccessError("outside_root");
      }
      return base.readDocument(rawPath);
    },
  };
}
