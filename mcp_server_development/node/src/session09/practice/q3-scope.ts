/**
 * 問題3: roots のスコープ解決の判定表
 *
 * MCP を通しません。resolveScopeFromRoots() は MCP を知らない純粋な関数なので、
 * 接続もプロセス起動もせずに全ケースを 1 秒で確認できます。
 * 「境界の判定ロジック」をドメイン層に置くと、こういう検証が安くなります。
 */
import { resolveDocsRoot } from "../../mid01/config.js";
import { describeScope, resolveScopeFromRoots } from "../domain/doc-scope.js";

const docsRoot = resolveDocsRoot();

/** 公開ディレクトリからの相対パスを file:// URI にする */
function uri(relative: string): string {
  return relative === "" ? `file://${docsRoot}` : `file://${docsRoot}/${relative}`;
}

const cases: { label: string; roots: { uri: string }[] }[] = [
  { label: "公開ディレクトリ自身", roots: [{ uri: uri("") }] },
  { label: "faq のみ", roots: [{ uri: uri("faq") }] },
  // 渡す順は guides → faq。出力が faq, guides なら昇順に並べ替えられている
  { label: "guides と faq", roots: [{ uri: uri("guides") }, { uri: uri("faq") }] },
  { label: "全体と faq", roots: [{ uri: uri("") }, { uri: uri("faq") }] },
  { label: "/tmp のみ", roots: [{ uri: "file:///tmp" }] },
  { label: "https のみ", roots: [{ uri: "https://example.com/docs" }] },
  // 文字列の前方一致で判定していたら通ってしまうケース
  { label: "docs-secret", roots: [{ uri: `file://${docsRoot}-secret` }] },
  { label: "空の配列", roots: [] },
];

cases.forEach((testCase, index) => {
  const outcome = resolveScopeFromRoots(docsRoot, testCase.roots);
  const detail = outcome.ok
    ? `ok=true / scope=${describeScope(outcome.scope)} / ignored=${outcome.scope.ignoredRoots.length}`
    : `ok=false / ignored=${outcome.ignoredRoots.length}`;
  console.log(`[${index + 1}/8] ${testCase.label}: ${detail}`);
});

console.log("OK: 問題3 の条件を満たしています");
