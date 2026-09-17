/**
 * 対策の有無を数字で比較する（問題5(b)）
 *
 *   docker compose exec node npx tsx src/review05/q5-review.ts
 */
import { createGateServer } from "./gate-server.js";
import { callTool, connectInMemory } from "./harness.js";
import { reviewToolResult } from "./q5-output-review.js";

const TARGETS = ["req-1004", "req-1006"] as const;

async function reviewAll(sanitize: boolean): Promise<void> {
  const client = await connectInMemory(
    createGateServer({ sanitize, audit: () => {}, nonce: () => "deadbeefdeadbeef" }),
  );
  console.log(`=== ${sanitize ? "対策あり（sanitize: true）" : "対策なし（sanitize: false）"} ===`);

  for (const id of TARGETS) {
    const review = reviewToolResult(JSON.stringify(await callTool(client, "get_request", { id })));
    const directives = review.directives.length === 0 ? "-" : review.directives.join(",");
    console.log(
      `${id}  ${review.ok ? "OK" : "NG"}  boundary=${review.untrustedBlocks}` +
        ` directives=${directives} secrets=${review.secretHits}`,
    );
    for (const problem of review.problems) console.log(`    - ${problem}`);
  }

  await client.close();
}

await reviewAll(false);
await reviewAll(true);
