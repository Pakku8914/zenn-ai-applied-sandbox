/**
 * 横断復習2 問題6 ― ファイルを読むリソーステンプレート（定義）
 *
 * 公開するもの
 *   テンプレート: notice-file://{name}（公開ディレクトリの Markdown を返す）
 *
 * 読み取りは必ず resolveNoticeFile() を通します。ハンドラの中に
 * fs.readFile を直接書かないのが、検証を迂回させないための作法です。
 */
import fs from "node:fs/promises";
import path from "node:path";

import { McpServer, ResourceTemplate } from "@modelcontextprotocol/sdk/server/mcp.js";
import { ErrorCode, McpError } from "@modelcontextprotocol/sdk/types.js";

import { PUBLIC_FILES } from "./q6-fixture.js";
import { resolveNoticeFile } from "./q6-resolve.js";

export const NOTICE_FILE_TEMPLATE = "notice-file://{name}";

export function createNoticeFileServer(): McpServer {
  const server = new McpServer({ name: "notice-files", version: "0.1.0" });

  server.registerResource(
    "notice_file",
    new ResourceTemplate(NOTICE_FILE_TEMPLATE, {
      list: undefined,
      complete: {
        // 補完は「読めるもの」だけを出す。symlink の staff-only.md は候補に入れない
        name: (value) => PUBLIC_FILES.filter((file) => file.startsWith(value)),
      },
    }),
    {
      title: "お知らせファイル（1 件）",
      description:
        "公開ディレクトリに置かれた Markdown ファイル 1 件を返します。" +
        "name には英小文字・数字・ハイフンからなるファイル名（拡張子 .md）を指定します。" +
        "指定できる値は completion/complete で取得できます。",
      mimeType: "text/markdown",
    },
    async (_uri, variables) => {
      const resolved = await resolveNoticeFile(firstValue(variables["name"]));
      if (!resolved.ok) {
        // 受け取った値もサーバー内部のパスもエラー文に含めない。
        // 攻撃文字列をそのまま返すと、ログや上位の表示経路に流れていく
        throw new McpError(
          ErrorCode.InvalidParams,
          `お知らせファイルを読み取れません（${resolved.reason}）。` +
            "指定できる名前は completion/complete で取得できます。",
        );
      }

      const text = await fs.readFile(resolved.realPath, "utf8");
      return {
        contents: [
          {
            // 正規形の URI を返す（受け取った URI をそのまま返さない）
            uri: `notice-file://${path.basename(resolved.realPath)}`,
            mimeType: "text/markdown",
            text,
          },
        ],
      };
    },
  );

  return server;
}

function firstValue(value: string | string[] | undefined): string {
  if (Array.isArray(value)) {
    return value[0] ?? "";
  }
  return value ?? "";
}
