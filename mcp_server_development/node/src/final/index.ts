/**
 * ライブラリとしての入口（package.json の exports が指す先）
 *
 * ここから import されているものだけが配布物に入ります。
 * 検証スクリプトやテストは import しないので、dist に含まれません。
 */
export { createWorkflowServer } from "./create-server.js";
export type { ScanReport, WorkflowServerOptions } from "./create-server.js";
export { startProtectedServer } from "./serve-core.js";
export type { RunningServer, ServeOptions } from "./serve-core.js";
export { createStore } from "./domain/workflow.js";
export type { Store, WorkflowRequest } from "./domain/workflow.js";
export {
  SCOPE_APPROVE,
  SCOPE_READ,
  SCOPE_WRITE,
  SUPPORTED_SCOPES,
  TOOL_SCOPES,
  runWithAuth,
} from "./auth/scopes.js";
export type { AuthContext, ToolName } from "./auth/scopes.js";
export { PACKAGE_NAME, SERVER_NAME, SERVER_VERSION } from "./version.js";
