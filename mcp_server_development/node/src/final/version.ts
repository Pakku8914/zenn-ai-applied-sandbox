/**
 * サーバーとパッケージの識別子。1 か所で決めて配ります。
 *
 * pkg/package.json の version との一致は pkg-metadata.test.ts が保証します
 * （版をコードと package.json の 2 か所に書くと、必ずどちらかがずれます）。
 */
export const SERVER_NAME = "workflow-requests";
export const SERVER_VERSION = "1.0.0";
export const PACKAGE_NAME = "workflow-requests-mcp";
export const RESOURCE_NAME = "社内申請ワークフロー MCP サーバー";
