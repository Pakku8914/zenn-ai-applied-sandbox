// 横断復習③ 問題 8 の確認スクリプト。3 つの構成の観測値を成立表に翻訳し、成立する攻撃の一覧を比べます。
// 外部には 1 度も接続しません（認可リクエストの URL を組み立てるだけで、送信はしません）。
// 実行: docker compose exec app npx tsx src/review03/q8-check.ts
import { ISSUER_PUBLIC } from "../session06/bookstore-client.js";
import { buildAuthorizationUrl } from "../session06/rp-authorize.js";
import { createPkcePair } from "../session06/rp-pkce.js";
import { attackMatrix, observePkceS256, succeedingAttacks } from "./q8-attack-matrix.js";
import type { AttackName, GivenObservations } from "./q8-attack-matrix.js";

// ── 認可リクエストの URL 2 種。plain は override で作ります（S256 の側は既定のまま）──────
const { codeVerifier, codeChallenge } = createPkcePair();
const s256Url = buildAuthorizationUrl({ issuer: ISSUER_PUBLIC, state: "probe-state", codeChallenge });
const plainUrl = buildAuthorizationUrl({
  issuer: ISSUER_PUBLIC,
  state: "probe-state",
  codeChallenge: codeVerifier, // plain では割符の現物がそのままブラウザを通る
  override: { code_challenge_method: "plain" },
});

// ── 問題文で与えられた 5 項目の観測値 ──────────────────────────────────
const hardened: GivenObservations = { acceptsOwnCallback: true, verifiesState: true, verifiesIssuer: true, exactRedirect: true, verifiesAudience: true };
const middle: GivenObservations = { acceptsOwnCallback: true, verifiesState: true, verifiesIssuer: false, exactRedirect: false, verifiesAudience: false };
const blind: GivenObservations = { acceptsOwnCallback: true, verifiesState: false, verifiesIssuer: false, exactRedirect: false, verifiesAudience: false };

type Setup = {
  readonly label: string;
  readonly given: GivenObservations;
  readonly authorizationUrl: string;
  readonly expected: readonly AttackName[];
};

const setups: readonly Setup[] = [
  { label: "硬い構成", given: hardened, authorizationUrl: s256Url, expected: [] },
  { label: "中間の構成", given: middle, authorizationUrl: plainUrl, expected: ["認可コード横取り", "混乱した代理", "トークン置換"] },
  { label: "何も見ない構成", given: blind, authorizationUrl: plainUrl, expected: ["認可コード横取り", "ログイン CSRF", "混乱した代理", "トークン置換"] },
];

let failed = 0;
for (const setup of setups) {
  const observed = { ...setup.given, pkceS256: observePkceS256(setup.authorizationUrl) };
  const succeeding = succeedingAttacks(attackMatrix(observed));
  // 対照が通っていなければ、state と iss の観測は当てにできません
  const ok = observed.acceptsOwnCallback && JSON.stringify(succeeding) === JSON.stringify(setup.expected);
  if (!ok) failed += 1;
  console.log(`${ok ? "OK" : "NG"} ${setup.label}`);
  console.log(`  観測: 対照=${observed.acceptsOwnCallback} state=${observed.verifiesState} iss=${observed.verifiesIssuer} redirect=${observed.exactRedirect} aud=${observed.verifiesAudience} pkce=${observed.pkceS256}`);
  console.log(`  成立する攻撃: ${succeeding.length === 0 ? "（なし）" : succeeding.join("、")}`);
}

// 止めた層の内訳も確かめます（succeeds が false の行に、生きている層の名前が並ぶこと）
const hijack = attackMatrix({ ...hardened, pkceS256: observePkceS256(s256Url) })[0];
const layers = hijack?.stoppedBy ?? [];
const layersOk = JSON.stringify(layers) === JSON.stringify(["redirect_uri 完全一致", "PKCE(S256)"]);
if (!layersOk) failed += 1;
console.log(`${layersOk ? "OK" : "NG"} 硬い構成で認可コード横取りを止めた層: ${layers.join("、")}`);

if (failed > 0) process.exit(1);
console.log("3 構成と層の内訳が期待どおりです");
