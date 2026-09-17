/**
 * ライブラリとしての公開面（package.json の exports が指す先）
 *
 * ここに書いたものだけが利用者から import できます。逆に言えば、
 * ここに無いファイルは「内部実装」なので、いつでも作り替えられます。
 */
export {
  createDocSearchServer,
  DOC_TEMPLATE,
  SERVER_NAME,
  SERVER_VERSION,
  type DocSearchServerOptions,
} from "./create-server.js";
export { resolveDocsRoot } from "./config.js";
