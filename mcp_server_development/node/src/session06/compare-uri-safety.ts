/**
 * Good サーバーと Bad サーバーに同じ入力を投げて、URI 設計の差を確認する
 *
 *   docker compose exec node npx tsx src/session06/compare-uri-safety.ts
 *
 * 投げるのは 3 つです。
 *   ① 正常な用語スラッグ
 *   ② パーセントエンコードしたパストラバーサル（テンプレートの形としては正当）
 *   ③ 購読ケイパビリティの宣言の有無
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const ATTACK_URI = "glossary://..%2f..%2f..%2f..%2fetc%2fpasswd";

type ContentsLike = { uri: string; text?: string };

async function inspect(label: string, entry: string): Promise<void> {
  const transport = new StdioClientTransport({ command: "npx", args: ["tsx", entry] });
  const client = new Client({ name: "uri-safety", version: "1.0.0" });
  await client.connect(transport);

  console.log(`=== ${label}（${entry}）===`);

  try {
    const result = await client.readResource({ uri: "glossary://sprint" });
    const head = (result.contents as ContentsLike[])[0];
    console.log(`glossary://sprint : 読めた（${(head?.text ?? "").split("\n")[0]}）`);
  } catch (error) {
    const message = (error as Error).message;
    console.log(
      `glossary://sprint : 失敗 / メッセージにサーバー内部のパスが含まれる=${message.includes("src/session06/glossary")}`,
    );
  }

  try {
    const result = await client.readResource({ uri: ATTACK_URI });
    const head = (result.contents as ContentsLike[])[0];
    const text = head?.text ?? "";
    console.log(`traversal         : 読めた=true / 先頭=${text.slice(0, 6)} / 文字数>0=${text.length > 0}`);
  } catch (error) {
    const message = (error as Error).message;
    console.log(
      `traversal         : 拒否 code=${(error as { code?: number }).code}` +
        ` / メッセージに入力を含まない=${!message.includes("etc")}`,
    );
  }

  const subscribe = client.getServerCapabilities()?.resources?.subscribe === true;
  console.log(`subscribe の宣言  : ${subscribe}`);

  await client.close();
}

await inspect("Good サーバー", "src/session06/server.ts");
await inspect("Bad サーバー", "src/session06/bad-server.ts");
console.log("判定: 許可リストで検証しない URI 設計は、テンプレートの形が合っているだけで任意のファイルを読ませます");
