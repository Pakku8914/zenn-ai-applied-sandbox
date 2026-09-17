// セッション28「テスト戦略・CI/CD・デプロイ」の検証スクリプト。
//
// この章で扱うテストのうち、コンポーネントテスト（React Testing Library）と
// E2E テスト（Playwright）は本書のサンドボックスに同梱していない。ブラウザの
// ダウンロードが数百MBになるためで、章では雛形の紹介に留めている。
//
// そこでここでは「テストの中身」ではなく、この章で下す判断と設定の正しさを検証する。
//
//   1. テストピラミッドの配分が健全か（E2E に偏っていないか）
//   2. CI のジョブ定義（必須ステップ・順序・キャッシュキー）
//   3. 環境変数の分類と、シークレットの漏れ（NEXT_PUBLIC_ とログ）
//   4. 本番用 Dockerfile の段（実物の web の Dockerfile を読んで検査する）
//   5. マイグレーションの適用順と、コマンド・段階デプロイの判断
//   6. ヘルスチェックの応答（web の lib/health.ts と同じ実装）
//
// 実行: docker compose exec ts npx tsx src/session28/verify.ts

import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// ---------------------------------------------------------------------------
// 検証ヘルパー（期待値と違えば失敗として記録する）
// ---------------------------------------------------------------------------
let failedCount = 0;

function checkString(label: string, actual: string, expected: string): void {
  if (actual !== expected) {
    console.error(`NG: ${label}\n--- 期待値 ---\n${expected}\n--- 実際 ---\n${actual}`);
    failedCount += 1;
  }
}

function checkNumber(label: string, actual: number, expected: number): void {
  if (actual !== expected) {
    console.error(`NG: ${label} — 期待値 ${expected} / 実際 ${actual}`);
    failedCount += 1;
  }
}

function checkBoolean(label: string, actual: boolean, expected: boolean): void {
  if (actual !== expected) {
    console.error(`NG: ${label} — 期待値 ${String(expected)} / 実際 ${String(actual)}`);
    failedCount += 1;
  }
}

function checkJson(label: string, actual: unknown, expected: unknown): void {
  checkString(label, JSON.stringify(actual), JSON.stringify(expected));
}

// ===========================================================================
// 本文1節：テストピラミッドの配分
// 「どこにどれだけ書くか」を数で表し、偏りを機械的に見つける。
// ===========================================================================
type TestCounts = {
  /** 関数1つを直接呼ぶテスト（速い・原因が分かる） */
  unit: number;
  /** データベースや複数の部品をまたぐテスト（中くらい） */
  integration: number;
  /** ブラウザを動かして画面から操作するテスト（遅い・壊れやすい） */
  e2e: number;
};

/** 判定の結果。判別タグは本書共通の kind */
type BalanceJudgement =
  | { kind: 'empty' }
  | { kind: 'ice-cream-cone'; e2ePercent: number }
  | { kind: 'unit-too-few'; unitPercent: number }
  | { kind: 'healthy'; unitPercent: number };

/** ユニットテストはこの割合以上にしたい */
const MIN_UNIT_PERCENT = 60;
/** E2E テストはこの割合までに抑えたい */
const MAX_E2E_PERCENT = 10;

function totalTestCount(counts: TestCounts): number {
  return counts.unit + counts.integration + counts.e2e;
}

function percentOf(part: number, total: number): number {
  return Math.round((part / total) * 100);
}

function judgeTestBalance(counts: TestCounts): BalanceJudgement {
  const total = totalTestCount(counts);

  if (total === 0) {
    return { kind: 'empty' };
  }

  const unitPercent = percentOf(counts.unit, total);
  const e2ePercent = percentOf(counts.e2e, total);

  // 先に E2E の偏りを見る。ここが太っているのが「アイスクリームコーン型」
  if (e2ePercent > MAX_E2E_PERCENT) {
    return { kind: 'ice-cream-cone', e2ePercent };
  }
  if (unitPercent < MIN_UNIT_PERCENT) {
    return { kind: 'unit-too-few', unitPercent };
  }

  return { kind: 'healthy', unitPercent };
}

function describeJudgement(judgement: BalanceJudgement): string {
  switch (judgement.kind) {
    case 'empty':
      return 'テストが1本もありません';
    case 'ice-cream-cone':
      return `E2E が ${judgement.e2ePercent}% です（アイスクリームコーン型）`;
    case 'unit-too-few':
      return `ユニットが ${judgement.unitPercent}% しかありません`;
    case 'healthy':
      return `健全です（ユニット ${judgement.unitPercent}%）`;
    default: {
      // 判定を増やしたらここで型エラーになる（セッション12の網羅性チェック）
      const unexpected: never = judgement;

      return unexpected;
    }
  }
}

const PYRAMID: TestCounts = { unit: 70, integration: 20, e2e: 10 };
const CONE: TestCounts = { unit: 10, integration: 20, e2e: 70 };

checkJson('本文1節: ピラミッド型は健全', judgeTestBalance(PYRAMID), {
  kind: 'healthy',
  unitPercent: 70,
});
checkJson('本文1節: E2E に偏るとアイスクリームコーン型', judgeTestBalance(CONE), {
  kind: 'ice-cream-cone',
  e2ePercent: 70,
});
checkJson('本文1節: E2E が11%でも多すぎ', judgeTestBalance({ unit: 70, integration: 19, e2e: 11 }), {
  kind: 'ice-cream-cone',
  e2ePercent: 11,
});
checkJson('本文1節: E2E ちょうど10%は許容', judgeTestBalance({ unit: 80, integration: 10, e2e: 10 }), {
  kind: 'healthy',
  unitPercent: 80,
});
checkJson(
  '本文1節: 統合テストばかりでも不健全',
  judgeTestBalance({ unit: 30, integration: 60, e2e: 10 }),
  { kind: 'unit-too-few', unitPercent: 30 }
);
checkJson('本文1節: ユニットちょうど60%は許容', judgeTestBalance({ unit: 60, integration: 35, e2e: 5 }), {
  kind: 'healthy',
  unitPercent: 60,
});
checkJson('本文1節: 1本も無い場合', judgeTestBalance({ unit: 0, integration: 0, e2e: 0 }), {
  kind: 'empty',
});
checkString(
  '本文1節: 判定の説明（健全）',
  describeJudgement(judgeTestBalance(PYRAMID)),
  '健全です（ユニット 70%）'
);
checkString(
  '本文1節: 判定の説明（偏り）',
  describeJudgement(judgeTestBalance(CONE)),
  'E2E が 70% です（アイスクリームコーン型）'
);

// --- 配分が実行時間にどう跳ね返るか -----------------------------------------
// 1本あたりの目安（この数字は「桁の感覚」をつかむための仮の値）。
const UNIT_MS = 10;
const INTEGRATION_MS = 500;
const E2E_MS = 8000;

function estimateSuiteMs(counts: TestCounts): number {
  return counts.unit * UNIT_MS + counts.integration * INTEGRATION_MS + counts.e2e * E2E_MS;
}

function toSeconds(milliseconds: number): number {
  return Math.round(milliseconds / 100) / 10;
}

const pyramidMs = estimateSuiteMs(PYRAMID);
const coneMs = estimateSuiteMs(CONE);

checkNumber('本文1節: ピラミッド型100本の所要（秒）', toSeconds(pyramidMs), 90.7);
checkNumber('本文1節: コーン型100本の所要（秒）', toSeconds(coneMs), 570.1);
checkNumber(
  '本文1節: 同じ100本でも何倍かかるか',
  Math.round((coneMs / pyramidMs) * 10) / 10,
  6.3
);
checkNumber('本文1節: テストが0本なら0秒', estimateSuiteMs({ unit: 0, integration: 0, e2e: 0 }), 0);

// ===========================================================================
// 本文6節：CI のジョブ定義の妥当性
// YAML を書く前に「何を・どの順で・どうキャッシュするか」を決める。
// ===========================================================================
type StepId =
  | 'checkout'
  | 'setup-node'
  | 'install'
  | 'generate'
  | 'migrate'
  | 'typecheck'
  | 'lint'
  | 'test'
  | 'build';

/** この7つが無い CI は検査として不完全 */
const REQUIRED_STEPS = [
  'checkout',
  'setup-node',
  'install',
  'typecheck',
  'lint',
  'test',
  'build',
] as const;

/** [先に置くもの, 後に置くもの] の組 */
const ORDER_RULES: readonly (readonly [StepId, StepId])[] = [
  ['checkout', 'setup-node'],
  ['setup-node', 'install'],
  ['install', 'typecheck'],
  ['install', 'lint'],
  ['install', 'test'],
  ['install', 'build'],
  ['typecheck', 'test'],
  ['test', 'build'],
];

type Workflow = {
  steps: readonly StepId[];
  /** 依存のキャッシュキー。無い場合は null */
  cacheKey: string | null;
};

type WorkflowCheck =
  | { kind: 'ok' }
  | { kind: 'missing-steps'; missing: StepId[] }
  | { kind: 'wrong-order'; problems: string[] }
  | { kind: 'weak-cache-key'; reason: string };

function checkWorkflow(workflow: Workflow): WorkflowCheck {
  const missing = REQUIRED_STEPS.filter((id) => !workflow.steps.includes(id));

  if (missing.length > 0) {
    return { kind: 'missing-steps', missing: [...missing] };
  }

  const problems: string[] = [];

  for (const [before, after] of ORDER_RULES) {
    const beforeIndex = workflow.steps.indexOf(before);
    const afterIndex = workflow.steps.indexOf(after);

    if (beforeIndex === -1 || afterIndex === -1) {
      continue;
    }
    if (beforeIndex > afterIndex) {
      problems.push(`${before} は ${after} より前に置く`);
    }
  }

  if (problems.length > 0) {
    return { kind: 'wrong-order', problems };
  }

  if (workflow.cacheKey === null) {
    return { kind: 'weak-cache-key', reason: 'キャッシュキーが無い' };
  }
  // ロックファイルの中身が変わったら別のキーになる必要がある。
  // 固定のキーだと、依存を更新しても古いキャッシュを使い続けてしまう。
  if (
    !workflow.cacheKey.includes('hashFiles(') ||
    !workflow.cacheKey.includes('package-lock.json')
  ) {
    return { kind: 'weak-cache-key', reason: 'ロックファイルのハッシュを含まない' };
  }

  return { kind: 'ok' };
}

// setup-node の cache: 'npm' が内部で作るキーと同じ考え方
const GOOD_CACHE_KEY = "node-24-${{ hashFiles('web/package-lock.json') }}";

const GOOD_WORKFLOW: Workflow = {
  steps: [
    'checkout',
    'setup-node',
    'install',
    'generate',
    'migrate',
    'typecheck',
    'lint',
    'test',
    'build',
  ],
  cacheKey: GOOD_CACHE_KEY,
};

checkJson('本文6節: 正しいワークフロー', checkWorkflow(GOOD_WORKFLOW), { kind: 'ok' });
checkJson(
  '本文6節: lint が無い',
  checkWorkflow({ ...GOOD_WORKFLOW, steps: ['checkout', 'setup-node', 'install', 'typecheck', 'test', 'build'] }),
  { kind: 'missing-steps', missing: ['lint'] }
);
checkJson(
  '本文6節: 型チェックとテストの両方が無い',
  checkWorkflow({ ...GOOD_WORKFLOW, steps: ['checkout', 'setup-node', 'install', 'lint', 'build'] }),
  { kind: 'missing-steps', missing: ['typecheck', 'test'] }
);
checkJson(
  '本文6節: インストールより先に型チェックしている',
  checkWorkflow({
    ...GOOD_WORKFLOW,
    steps: ['checkout', 'setup-node', 'typecheck', 'install', 'lint', 'test', 'build'],
  }),
  { kind: 'wrong-order', problems: ['install は typecheck より前に置く'] }
);
checkJson(
  '本文6節: テストより先にビルドしている',
  checkWorkflow({
    ...GOOD_WORKFLOW,
    steps: ['checkout', 'setup-node', 'install', 'typecheck', 'lint', 'build', 'test'],
  }),
  { kind: 'wrong-order', problems: ['test は build より前に置く'] }
);
checkJson('本文6節: キャッシュキーが無い', checkWorkflow({ ...GOOD_WORKFLOW, cacheKey: null }), {
  kind: 'weak-cache-key',
  reason: 'キャッシュキーが無い',
});
checkJson(
  '本文6節: 固定のキャッシュキーは危ない',
  checkWorkflow({ ...GOOD_WORKFLOW, cacheKey: 'node-modules-v1' }),
  { kind: 'weak-cache-key', reason: 'ロックファイルのハッシュを含まない' }
);

// ===========================================================================
// 本文7節：環境変数とシークレットの分類
// 同じ判定を「環境変数の置き場所」と「ログに出してよいか」の両方に使い回す。
// ===========================================================================
type EnvKind = 'public' | 'secret' | 'config';

/** この接頭辞が付いた値はビルド時にブラウザ向けのコードへ埋め込まれる（セッション26） */
const PUBLIC_ENV_PREFIX = 'NEXT_PUBLIC_';

/** 名前にこれを含むものは秘密として扱う */
const SECRET_NAME_PARTS = ['SECRET', 'TOKEN', 'PASSWORD', 'PRIVATE', 'KEY', 'CREDENTIAL'] as const;

/** 名前の部品からは分からない秘密。表に書いて明示する */
const KNOWN_SECRET_NAMES = ['DATABASE_URL', 'DIRECT_DATABASE_URL'] as const;

/** camelCase を SNAKE_CASE にそろえる（databaseUrl → DATABASE_URL） */
function normalizeName(name: string): string {
  return name.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toUpperCase();
}

function looksSecret(name: string): boolean {
  const upper = normalizeName(name);

  if ((KNOWN_SECRET_NAMES as readonly string[]).includes(upper)) {
    return true;
  }

  return SECRET_NAME_PARTS.some((part) => upper.includes(part));
}

/**
 * 環境変数の名前を3つに分ける。
 * NEXT_PUBLIC_ が付いていれば、中身が何であれ「公開」である（隠せない）。
 */
function classifyEnvName(name: string): EnvKind {
  if (name.startsWith(PUBLIC_ENV_PREFIX)) {
    return 'public';
  }

  return looksSecret(name) ? 'secret' : 'config';
}

/**
 * NEXT_PUBLIC_ が付いているのに、名前が秘密らしいものを挙げる。
 * 「公開」に分類されるからこそ危ない。ビルドした瞬間に全員へ配られる。
 */
function findPublicSecretLeaks(names: readonly string[]): string[] {
  return names
    .filter((name) => name.startsWith(PUBLIC_ENV_PREFIX))
    .filter((name) => looksSecret(name.slice(PUBLIC_ENV_PREFIX.length)))
    .sort();
}

type LoggedNamesCheck = { kind: 'ok' } | { kind: 'leaked'; names: string[] };

/** ログに出そうとしている名前のうち、秘密に分類されるものがあれば止める */
function checkLoggedNames(names: readonly string[]): LoggedNamesCheck {
  const leaked = names
    .filter((name) => classifyEnvName(normalizeName(name)) === 'secret')
    .map((name) => normalizeName(name))
    .sort();

  return leaked.length === 0 ? { kind: 'ok' } : { kind: 'leaked', names: leaked };
}

const envCases: { name: string; expected: EnvKind }[] = [
  { name: 'DATABASE_URL', expected: 'secret' },
  { name: 'SESSION_SECRET', expected: 'secret' },
  { name: 'PAYMENT_WEBHOOK_SECRET', expected: 'secret' },
  { name: 'ADMIN_API_TOKEN', expected: 'secret' },
  { name: 'SMTP_PASSWORD', expected: 'secret' },
  { name: 'NODE_ENV', expected: 'config' },
  { name: 'PORT', expected: 'config' },
  { name: 'LOG_LEVEL', expected: 'config' },
  { name: 'NEXT_TELEMETRY_DISABLED', expected: 'config' },
  { name: 'NEXT_PUBLIC_SITE_NAME', expected: 'public' },
  { name: 'NEXT_PUBLIC_API_BASE_URL', expected: 'public' },
  // 秘密を入れても「公開」に分類される。だから接頭辞は付ける前に考える
  { name: 'NEXT_PUBLIC_DATABASE_URL', expected: 'public' },
];

for (const { name, expected } of envCases) {
  checkString(`本文7節: classifyEnvName('${name}')`, classifyEnvName(name), expected);
}

checkJson(
  '本文7節: 公開接頭辞に混ざった秘密を見つける',
  findPublicSecretLeaks([
    'NEXT_PUBLIC_SITE_NAME',
    'NEXT_PUBLIC_DATABASE_URL',
    'NEXT_PUBLIC_API_TOKEN',
    'DATABASE_URL',
    'NODE_ENV',
  ]),
  ['NEXT_PUBLIC_API_TOKEN', 'NEXT_PUBLIC_DATABASE_URL']
);
checkJson(
  '本文7節: 公開してよいものだけなら0件',
  findPublicSecretLeaks(['NEXT_PUBLIC_SITE_NAME', 'NEXT_PUBLIC_API_BASE_URL']),
  []
);
checkJson('本文7節: ログに出してよい名前', checkLoggedNames(['requestId', 'productId', 'nodeEnv']), {
  kind: 'ok',
});
checkJson(
  '本文7節: ログに秘密が混ざっている',
  checkLoggedNames(['requestId', 'databaseUrl', 'sessionSecret']),
  { kind: 'leaked', names: ['DATABASE_URL', 'SESSION_SECRET'] }
);

// ===========================================================================
// 本文8節：本番用 Dockerfile の段
// 文字列として読み、段の構成と実行段の中身を検査する。
// ===========================================================================
type DockerStage = { name: string | null; base: string; lines: string[] };

function parseStages(dockerfile: string): DockerStage[] {
  const stages: DockerStage[] = [];

  for (const rawLine of dockerfile.split('\n')) {
    const line = rawLine.trim();

    // 空行とコメントは読み飛ばす（コメントアウトした COPY を数えないため）
    if (line === '' || line.startsWith('#')) {
      continue;
    }

    const from = /^FROM\s+(\S+)(?:\s+AS\s+(\S+))?$/i.exec(line);

    if (from !== null) {
      stages.push({ name: from[2] ?? null, base: from[1] ?? '', lines: [] });
      continue;
    }

    const current = stages[stages.length - 1];

    if (current !== undefined) {
      current.lines.push(line);
    }
  }

  return stages;
}

type DockerfileCheck =
  | { kind: 'ok'; stageNames: string[] }
  | { kind: 'not-multi-stage'; stageCount: number }
  | { kind: 'missing-stage'; missing: string[] }
  | { kind: 'fat-runner'; reason: string }
  | { kind: 'runs-as-root' };

/** 依存インストール → ビルド → 実行 の3段 */
const EXPECTED_STAGES = ['deps', 'builder', 'runner'] as const;

function checkProductionDockerfile(dockerfile: string): DockerfileCheck {
  const stages = parseStages(dockerfile);
  const stageNames = stages.map((stage) => stage.name ?? '(名前なし)');

  if (stages.length < EXPECTED_STAGES.length) {
    return { kind: 'not-multi-stage', stageCount: stages.length };
  }

  const missing = EXPECTED_STAGES.filter((name) => !stageNames.includes(name));

  if (missing.length > 0) {
    return { kind: 'missing-stage', missing: [...missing] };
  }

  const runner = stages[stages.length - 1];

  if (runner === undefined) {
    return { kind: 'not-multi-stage', stageCount: stages.length };
  }

  // 実行段で依存を入れ直すと、開発用の依存まで最終イメージに入る
  if (runner.lines.some((line) => /^RUN\s+npm\s+(ci|install)/i.test(line))) {
    return { kind: 'fat-runner', reason: '実行段で npm ci / npm install をしている' };
  }
  if (runner.lines.some((line) => /^COPY\s+.*node_modules/i.test(line))) {
    return { kind: 'fat-runner', reason: '実行段に node_modules を丸ごとコピーしている' };
  }
  if (!runner.lines.some((line) => line.includes('.next/standalone'))) {
    return { kind: 'fat-runner', reason: 'standalone の出力をコピーしていない' };
  }
  // root で動かさない（侵入されたときにできることを減らす）
  if (!runner.lines.some((line) => /^USER\s+node$/i.test(line))) {
    return { kind: 'runs-as-root' };
  }

  return { kind: 'ok', stageNames };
}

// --- 実物の Dockerfile を読む -----------------------------------------------
const here = dirname(fileURLToPath(import.meta.url));
const productionDockerfile = readFileSync(resolve(here, '..', '..', 'web', 'Dockerfile'), 'utf-8');

checkJson('本文8節: 実物の Dockerfile は deps / builder / runner の3段', checkProductionDockerfile(productionDockerfile), {
  kind: 'ok',
  stageNames: ['deps', 'builder', 'runner'],
});

// --- 悪い例（比較のために文字列で書く） -------------------------------------
const SINGLE_STAGE = [
  'FROM node:24-bookworm-slim',
  'WORKDIR /app',
  'COPY . .',
  'RUN npm ci',
  'RUN npx next build',
  'CMD ["npm", "start"]',
].join('\n');

const RUNNER_INSTALLS_AGAIN = [
  'FROM node:24-bookworm-slim AS deps',
  'RUN npm ci',
  'FROM node:24-bookworm-slim AS builder',
  'RUN npx next build',
  'FROM node:24-bookworm-slim AS runner',
  'COPY . .',
  'RUN npm ci',
  'USER node',
  'CMD ["node", "server.js"]',
].join('\n');

const RUNNER_COPIES_MODULES = [
  'FROM node:24-bookworm-slim AS deps',
  'RUN npm ci',
  'FROM node:24-bookworm-slim AS builder',
  'RUN npx next build',
  'FROM node:24-bookworm-slim AS runner',
  'COPY --from=builder /app/node_modules ./node_modules',
  'COPY --from=builder /app/.next/standalone ./',
  'USER node',
  'CMD ["node", "server.js"]',
].join('\n');

const RUNNER_AS_ROOT = [
  'FROM node:24-bookworm-slim AS deps',
  'RUN npm ci',
  'FROM node:24-bookworm-slim AS builder',
  'RUN npx next build',
  'FROM node:24-bookworm-slim AS runner',
  'COPY --from=builder /app/.next/standalone ./',
  'COPY --from=builder /app/.next/static ./.next/static',
  'CMD ["node", "server.js"]',
].join('\n');

const WRONG_STAGE_NAMES = [
  'FROM node:24-bookworm-slim AS install',
  'RUN npm ci',
  'FROM node:24-bookworm-slim AS compile',
  'RUN npx next build',
  'FROM node:24-bookworm-slim AS serve',
  'COPY --from=compile /app/.next/standalone ./',
  'USER node',
  'CMD ["node", "server.js"]',
].join('\n');

checkJson('本文8節: 1段だけなら多段ビルドではない', checkProductionDockerfile(SINGLE_STAGE), {
  kind: 'not-multi-stage',
  stageCount: 1,
});
checkJson('本文8節: 段の名前が違う', checkProductionDockerfile(WRONG_STAGE_NAMES), {
  kind: 'missing-stage',
  missing: ['deps', 'builder', 'runner'],
});
checkJson('本文8節: 実行段で入れ直している', checkProductionDockerfile(RUNNER_INSTALLS_AGAIN), {
  kind: 'fat-runner',
  reason: '実行段で npm ci / npm install をしている',
});
checkJson('本文8節: 実行段に node_modules を持ち込んでいる', checkProductionDockerfile(RUNNER_COPIES_MODULES), {
  kind: 'fat-runner',
  reason: '実行段に node_modules を丸ごとコピーしている',
});
checkJson('本文8節: root で動かしている', checkProductionDockerfile(RUNNER_AS_ROOT), {
  kind: 'runs-as-root',
});

// 段の中身の読み取りそのものも確かめる
const parsedStages = parseStages(productionDockerfile);

checkNumber('本文8節: 段は3つ', parsedStages.length, 3);
checkString('本文8節: 1段目の名前', parsedStages[0]?.name ?? '(なし)', 'deps');
checkString('本文8節: 3段目のベースイメージ', parsedStages[2]?.base ?? '(なし)', 'node:24-bookworm-slim');
checkBoolean(
  '本文8節: ベースイメージのタグが固定されている',
  parsedStages.every((stage) => stage.base.includes(':') && !stage.base.endsWith(':latest')),
  true
);
checkBoolean(
  '本文8節: 1段目でロックファイルどおりに入れている',
  (parsedStages[0]?.lines ?? []).some((line) => line.startsWith('RUN npm ci')),
  true
);

// ===========================================================================
// 本文9節：マイグレーションの適用状況とコマンドの使い分け
// ===========================================================================
type MigrationRecord = {
  /** Prisma が付ける名前。先頭が日時なので、名前順＝適用順になる */
  name: string;
  /** 適用済みなら日時、まだなら null */
  appliedAt: string | null;
};

type HistoryCheck =
  | { kind: 'up-to-date' }
  | { kind: 'pending'; names: string[] }
  | { kind: 'out-of-order'; names: string[] };

function pendingMigrations(records: readonly MigrationRecord[]): string[] {
  return records
    .filter((record) => record.appliedAt === null)
    .map((record) => record.name)
    .sort();
}

/**
 * 履歴を検査する。
 * 「古いものが未適用なのに新しいものが適用済み」は、環境ごとにスキーマが
 * ずれているサイン（誰かが手でデータベースをいじった、など）。
 */
function checkMigrationHistory(records: readonly MigrationRecord[]): HistoryCheck {
  const sorted = [...records].sort((left, right) => left.name.localeCompare(right.name));
  const pending = sorted.filter((record) => record.appliedAt === null);

  if (pending.length === 0) {
    return { kind: 'up-to-date' };
  }

  const lastAppliedIndex = sorted.findLastIndex((record) => record.appliedAt !== null);
  const outOfOrder = sorted
    .filter((record, index) => record.appliedAt === null && index < lastAppliedIndex)
    .map((record) => record.name);

  if (outOfOrder.length > 0) {
    return { kind: 'out-of-order', names: outOfOrder };
  }

  return { kind: 'pending', names: pending.map((record) => record.name) };
}

type DeployTarget = 'development' | 'test' | 'production';
type MigrateCommand = 'migrate dev' | 'migrate deploy';

/**
 * どのコマンドを使うか。
 * migrate dev は「スキーマを見て新しいマイグレーションを作る」開発専用の道具で、
 * 履歴が合わないと作り直し（＝全削除）を提案してくる。本番と CI では deploy だけ。
 */
function chooseMigrateCommand(target: DeployTarget): MigrateCommand {
  return target === 'development' ? 'migrate dev' : 'migrate deploy';
}

const MIGRATIONS: MigrationRecord[] = [
  { name: '20260828165322_init', appliedAt: '2026-08-29T00:00:00.000Z' },
  { name: '20260901093000_add_order_items', appliedAt: null },
  { name: '20260902101500_add_payment_idempotency_key', appliedAt: null },
];

checkJson('本文9節: 未適用のマイグレーション', pendingMigrations(MIGRATIONS), [
  '20260901093000_add_order_items',
  '20260902101500_add_payment_idempotency_key',
]);
checkJson('本文9節: 未適用が2件ある', checkMigrationHistory(MIGRATIONS), {
  kind: 'pending',
  names: ['20260901093000_add_order_items', '20260902101500_add_payment_idempotency_key'],
});
checkJson(
  '本文9節: すべて適用済み',
  checkMigrationHistory([{ name: '20260828165322_init', appliedAt: '2026-08-29T00:00:00.000Z' }]),
  { kind: 'up-to-date' }
);
checkJson(
  '本文9節: 順番が飛んでいる（危険な状態）',
  checkMigrationHistory([
    { name: '20260828165322_init', appliedAt: null },
    { name: '20260901093000_add_order_items', appliedAt: '2026-09-01T00:00:00.000Z' },
  ]),
  { kind: 'out-of-order', names: ['20260828165322_init'] }
);
checkJson('本文9節: 記録が空なら最新扱い', checkMigrationHistory([]), { kind: 'up-to-date' });
checkString('本文9節: 開発では migrate dev', chooseMigrateCommand('development'), 'migrate dev');
checkString('本文9節: CI では migrate deploy', chooseMigrateCommand('test'), 'migrate deploy');
checkString('本文9節: 本番では migrate deploy', chooseMigrateCommand('production'), 'migrate deploy');

// --- 前進のみ：危ない変更は段階に分ける -------------------------------------
type SchemaChange =
  | { kind: 'add-nullable-column'; table: string; column: string }
  | { kind: 'add-required-column'; table: string; column: string }
  | { kind: 'drop-column'; table: string; column: string }
  | { kind: 'rename-column'; table: string; from: string; to: string };

type DeploySafety = { kind: 'safe' } | { kind: 'staged'; steps: string[] };

/**
 * 「アプリの新旧が同時に動いている瞬間があっても壊れないか」で判断する。
 * デプロイは一瞬では終わらないので、この前提を外すと必ず落ちる。
 */
function planSchemaChange(change: SchemaChange): DeploySafety {
  switch (change.kind) {
    case 'add-nullable-column':
      // 古いアプリはこの列を知らないが、NULL を許すので書き込みは通る
      return { kind: 'safe' };
    case 'add-required-column':
      return {
        kind: 'staged',
        steps: [
          `${change.table}.${change.column} を NULL 許容で追加する`,
          '既存の行に値を入れ、新しいアプリをデプロイする',
          `${change.table}.${change.column} を NOT NULL に変更する`,
        ],
      };
    case 'drop-column':
      return {
        kind: 'staged',
        steps: [
          `アプリから ${change.table}.${change.column} を読み書きするコードを消してデプロイする`,
          `${change.table}.${change.column} を削除するマイグレーションを適用する`,
        ],
      };
    case 'rename-column':
      return {
        kind: 'staged',
        steps: [
          `${change.table}.${change.to} を追加して両方に書き込む`,
          `読み取りを ${change.table}.${change.to} に切り替えてデプロイする`,
          `${change.table}.${change.from} を削除する`,
        ],
      };
    default: {
      const unexpected: never = change;

      return unexpected;
    }
  }
}

checkJson(
  '本文9節: NULL 許容の列追加はそのまま出せる',
  planSchemaChange({ kind: 'add-nullable-column', table: 'products', column: 'imageUrl' }),
  { kind: 'safe' }
);
checkJson(
  '本文9節: 列の削除は2段階',
  planSchemaChange({ kind: 'drop-column', table: 'products', column: 'description' }),
  {
    kind: 'staged',
    steps: [
      'アプリから products.description を読み書きするコードを消してデプロイする',
      'products.description を削除するマイグレーションを適用する',
    ],
  }
);
// 判別可能なユニオンなので、kind を確かめてから steps を読む（セッション12）
const requiredColumnPlan = planSchemaChange({
  kind: 'add-required-column',
  table: 'orders',
  column: 'shippingFee',
});
const renamePlan = planSchemaChange({
  kind: 'rename-column',
  table: 'orders',
  from: 'total',
  to: 'totalAmount',
});

checkNumber(
  '本文9節: 必須列の追加は3段階',
  requiredColumnPlan.kind === 'staged' ? requiredColumnPlan.steps.length : 0,
  3
);
checkNumber('本文9節: 改名も3段階', renamePlan.kind === 'staged' ? renamePlan.steps.length : 0, 3);
checkString(
  '本文9節: 改名の1段目',
  renamePlan.kind === 'staged' ? (renamePlan.steps[0] ?? '(なし)') : '(safe)',
  'orders.totalAmount を追加して両方に書き込む'
);

// ===========================================================================
// 本文10節：ヘルスチェックの応答（web の lib/health.ts と同じ実装）
// src から web は import できないため、同じ仕様を書き写して検証する。
// ===========================================================================
type HealthProbe =
  | { kind: 'ready'; appliedMigrationCount: number }
  | { kind: 'database-unreachable' }
  | { kind: 'migrations-pending'; pending: readonly string[] }
  | { kind: 'config-invalid'; missing: readonly string[] };

type HealthStatusCode = 200 | 503;

type HealthBody = {
  status: 'ok' | 'unavailable';
  reason: 'ready' | 'database_unreachable' | 'migrations_pending' | 'config_invalid';
  detail: string[];
};

function toHealthStatus(probe: HealthProbe): HealthStatusCode {
  return probe.kind === 'ready' ? 200 : 503;
}

function buildHealthBody(probe: HealthProbe): HealthBody {
  switch (probe.kind) {
    case 'ready':
      return { status: 'ok', reason: 'ready', detail: [] };
    case 'database-unreachable':
      return { status: 'unavailable', reason: 'database_unreachable', detail: [] };
    case 'migrations-pending':
      return { status: 'unavailable', reason: 'migrations_pending', detail: [...probe.pending] };
    case 'config-invalid':
      return { status: 'unavailable', reason: 'config_invalid', detail: [...probe.missing] };
    default: {
      const unexpected: never = probe;

      return unexpected;
    }
  }
}

const healthCases: { probe: HealthProbe; expected: HealthStatusCode }[] = [
  { probe: { kind: 'ready', appliedMigrationCount: 1 }, expected: 200 },
  { probe: { kind: 'database-unreachable' }, expected: 503 },
  { probe: { kind: 'migrations-pending', pending: ['20260901093000_add_order_items'] }, expected: 503 },
  { probe: { kind: 'config-invalid', missing: ['DATABASE_URL'] }, expected: 503 },
];

for (const { probe, expected } of healthCases) {
  checkNumber(`本文10節: ${probe.kind} のステータス`, toHealthStatus(probe), expected);
}

checkJson('本文10節: 準備できているときの本文', buildHealthBody({ kind: 'ready', appliedMigrationCount: 3 }), {
  status: 'ok',
  reason: 'ready',
  detail: [],
});
checkJson(
  '本文10節: 未適用のマイグレーションがあるときの本文',
  buildHealthBody({
    kind: 'migrations-pending',
    pending: pendingMigrations(MIGRATIONS),
  }),
  {
    status: 'unavailable',
    reason: 'migrations_pending',
    detail: ['20260901093000_add_order_items', '20260902101500_add_payment_idempotency_key'],
  }
);
checkJson(
  '本文10節: データベースに繋がらないときは理由だけ返す',
  buildHealthBody({ kind: 'database-unreachable' }),
  { status: 'unavailable', reason: 'database_unreachable', detail: [] }
);

// 応答に「値」が混ざっていないことを確かめる（ヘルスチェックは公開されがち）
const leakyProbe: HealthProbe = { kind: 'config-invalid', missing: ['DATABASE_URL'] };
const leakyBody = JSON.stringify(buildHealthBody(leakyProbe));

checkBoolean('本文10節: 応答に接続文字列が含まれない', leakyBody.includes('postgresql://'), false);
checkBoolean('本文10節: 応答には名前だけが含まれる', leakyBody.includes('DATABASE_URL'), true);

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failedCount > 0) {
  console.error(`session28: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('session28: ok');
