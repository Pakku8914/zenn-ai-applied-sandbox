import { SETUPS, decide } from "./q9-flow-choice.js";
import type { FlowId } from "../session05/web-app-flow-chooser.js";

const expected: readonly FlowId[] = [
  "authorization-code+pkce",
  "device-code",
  "client-credentials",
  "authorization-code+pkce",
  "authorization-code+pkce",
];

let failed = 0;
SETUPS.forEach((setup, index) => {
  const d = decide(setup);
  const ok = d.flow === expected[index];
  if (!ok) failed += 1;
  console.log(`${ok ? "OK" : "NG"} ${setup.label}: ${d.flow}\n  当時: ${d.legacy.flow}（${d.legacy.note}）\n  守り: ${d.guards.join(" / ")}`);
});
if (failed > 0) process.exit(1);
console.log("5 つの構成すべてが期待どおりです");
