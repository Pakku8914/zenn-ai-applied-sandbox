// 環境変数（アプリの外から与える設定）の検証（セッション26）。
//
// 環境変数は「型が付いていない外から来た値」の代表である。process.env の
// 型は string | undefined なので、書き間違いや設定漏れをコンパイラは
// 見つけてくれない。だから Zod で1か所にまとめて検証する（セッション24と同じ発想）。
//
// この章の要点は、失敗の伝え方にある。エラーメッセージに値を載せると、
// 接続文字列（利用者名とパスワードを含む）がログや画面に出てしまう。
// だからここで作るメッセージには「変数の名前」しか入れない。

import { z } from 'zod';

/**
 * このアプリが動くために必要な設定。
 * 増やすときは必ずここに足す（コードの中で process.env を直接読まない）。
 */
export const envSchema = z.object({
  DATABASE_URL: z
    .string({ error: 'DATABASE_URL を設定してください' })
    .min(1, { error: 'DATABASE_URL を設定してください' })
    .refine((value) => value.startsWith('postgresql://'), {
      error: 'DATABASE_URL は postgresql:// で始まる接続文字列にしてください',
    }),
  // 指定が無いときは開発扱いにする。安全側（機能を絞る側）に寄せる
  NODE_ENV: z.enum(['development', 'test', 'production']).default('development'),
});

export type AppEnv = z.infer<typeof envSchema>;

/** 検証の結果。失敗は「不足」と「不正」に分ける（直し方が違うため） */
export type EnvCheck =
  | { kind: 'ok'; env: AppEnv }
  | { kind: 'invalid'; missing: string[]; invalid: string[] };

/** 環境変数の名前だけを取り出す。値は絶対に持ち出さない */
function uniqueNames(names: string[]): string[] {
  return [...new Set(names)].sort();
}

/**
 * 環境変数の入れ物を検証する。process.env をそのまま渡せるが、
 * 引数で受け取る形にしてあるのでテストから好きな組み合わせを試せる。
 */
export function parseEnv(source: Record<string, string | undefined>): EnvCheck {
  const result = envSchema.safeParse({
    DATABASE_URL: source['DATABASE_URL'],
    NODE_ENV: source['NODE_ENV'],
  });

  if (result.success) {
    return { kind: 'ok', env: result.data };
  }

  const missing: string[] = [];
  const invalid: string[] = [];

  for (const issue of result.error.issues) {
    const name = issue.path.map((segment) => String(segment)).join('.');

    // 値が無い（undefined）と、値はあるが形が違うのは別の失敗として扱う
    if (issue.code === 'invalid_type') {
      missing.push(name);
    } else {
      invalid.push(name);
    }
  }

  return { kind: 'invalid', missing: uniqueNames(missing), invalid: uniqueNames(invalid) };
}

/** 失敗を1行の説明にする。ここに値を混ぜないことが重要 */
export function describeEnvFailure(check: Extract<EnvCheck, { kind: 'invalid' }>): string {
  const missing = check.missing.length === 0 ? 'なし' : check.missing.join(', ');
  const invalid = check.invalid.length === 0 ? 'なし' : check.invalid.join(', ');

  return `環境変数の設定に問題があります（不足: ${missing} / 形式が不正: ${invalid}）`;
}

let cachedEnv: AppEnv | undefined;

/**
 * 検証済みの設定を取り出す。最初に呼ばれたときに1度だけ検証し、
 * 失敗していれば例外を投げる（＝設定漏れのまま動き続けるのを防ぐ）。
 */
export function getEnv(): AppEnv {
  if (cachedEnv !== undefined) {
    return cachedEnv;
  }

  const check = parseEnv(process.env);

  if (check.kind === 'invalid') {
    throw new Error(describeEnvFailure(check));
  }

  cachedEnv = check.env;

  return cachedEnv;
}

/** 設定の状態を外に見せる形。値は含めない（名前と可否だけ） */
export type EnvStatus = {
  ok: boolean;
  missing: string[];
  invalid: string[];
  nodeEnv: string;
  /** NEXT_PUBLIC_ が付いているのに秘密らしい名前の変数（ブラウザに埋まる） */
  suspiciousPublicNames: string[];
};

/** ブラウザに埋め込まれる変数の目印。Next.js の決まり */
export const PUBLIC_ENV_PREFIX = 'NEXT_PUBLIC_';

/** 名前にこれを含む変数は秘密の可能性が高い */
const SECRET_NAME_PARTS = ['SECRET', 'TOKEN', 'PASSWORD', 'PRIVATE', 'KEY', 'CREDENTIAL'] as const;

/**
 * NEXT_PUBLIC_ が付いた変数のうち、名前が秘密らしいものを挙げる。
 * この接頭辞が付いた値はビルド時にブラウザ向けのコードへ埋め込まれるので、
 * 秘密を入れると全員に配ってしまう。
 */
export function findLeakedPublicSecrets(source: Record<string, string | undefined>): string[] {
  return Object.keys(source)
    .filter((name) => name.startsWith(PUBLIC_ENV_PREFIX))
    .filter((name) => {
      const upper = name.toUpperCase();

      return SECRET_NAME_PARTS.some((part) => upper.includes(part));
    })
    .sort();
}

// ---------------------------------------------------------------------------
// 最終プロジェクト：Webhook の署名に使う共有の秘密
//
// PAYMENT_WEBHOOK_SECRET は「決済サービスとこのアプリだけが知っている文字列」で、
// これが漏れると誰でも「支払い成功」の通知を偽造できる。つまり DATABASE_URL と
// 同じ重さの秘密である。
//
// ただし開発のたびに設定を求めると学習が止まるので、開発（と test）に限って
// 既定値を使う。本番（NODE_ENV=production）では必ず設定させ、無ければ起動時に
// 例外を投げて落とす。「設定漏れのまま動き続ける」のがいちばん危ない状態だからである。
//
// envSchema には足していない。足すと /api/health が「不足」と報告してしまい、
// 開発中のヘルスチェックが赤くなるためで、代わりに専用の判定を用意する。
// ---------------------------------------------------------------------------

/** 開発でだけ使う既定値。この値が本番に出ることは絶対に許さない */
export const DEV_PAYMENT_WEBHOOK_SECRET = 'dev-only-webhook-secret';

/** 秘密の最低の長さ。短い秘密は総当たりで当てられる */
export const MIN_WEBHOOK_SECRET_LENGTH = 16;

export type WebhookSecretCheck =
  | { kind: 'ok'; secret: string; source: 'env' | 'development-default' }
  | { kind: 'missing' }
  | { kind: 'too_short'; length: number };

/**
 * 秘密を検証する。引数で受け取る形にしてあるので、
 * 「本番で未設定」「短すぎる」といった組み合わせをテストから再現できる。
 */
export function checkWebhookSecret(
  raw: string | undefined,
  nodeEnv: string
): WebhookSecretCheck {
  if (raw === undefined || raw === '') {
    return nodeEnv === 'production'
      ? { kind: 'missing' }
      : { kind: 'ok', secret: DEV_PAYMENT_WEBHOOK_SECRET, source: 'development-default' };
  }

  if (raw.length < MIN_WEBHOOK_SECRET_LENGTH) {
    return { kind: 'too_short', length: raw.length };
  }

  return { kind: 'ok', secret: raw, source: 'env' };
}

export function describeWebhookSecretFailure(
  check: Exclude<WebhookSecretCheck, { kind: 'ok' }>
): string {
  switch (check.kind) {
    case 'missing':
      return '本番では PAYMENT_WEBHOOK_SECRET を設定してください';
    case 'too_short':
      return `PAYMENT_WEBHOOK_SECRET は${MIN_WEBHOOK_SECRET_LENGTH}文字以上にしてください`;
    default: {
      const unreachable: never = check;

      throw new Error(`未知の失敗です: ${JSON.stringify(unreachable)}`);
    }
  }
}

/**
 * 検証済みの秘密を取り出す。
 * 設定ミスは Result で返さず throw する（利用者が直せないので、
 * 画面にメッセージを出しても意味がない — セッション18の判断基準）。
 */
export function getWebhookSecret(): string {
  const check = checkWebhookSecret(
    process.env['PAYMENT_WEBHOOK_SECRET'],
    process.env['NODE_ENV'] ?? 'development'
  );

  if (check.kind === 'ok') {
    return check.secret;
  }

  // メッセージに値を混ぜない。混ぜると秘密がログに出る
  throw new Error(describeWebhookSecretFailure(check));
}

/** 例外を投げずに状態を返す。動作確認用の口（/api/health）から使う */
export function describeEnvStatus(source: Record<string, string | undefined>): EnvStatus {
  const check = parseEnv(source);
  const suspiciousPublicNames = findLeakedPublicSecrets(source);

  if (check.kind === 'ok') {
    return {
      ok: suspiciousPublicNames.length === 0,
      missing: [],
      invalid: [],
      nodeEnv: check.env.NODE_ENV,
      suspiciousPublicNames,
    };
  }

  return {
    ok: false,
    missing: check.missing,
    invalid: check.invalid,
    nodeEnv: source['NODE_ENV'] ?? 'unknown',
    suspiciousPublicNames,
  };
}
