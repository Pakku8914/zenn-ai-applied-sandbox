// セッション18「エラーハンドリングと型安全な失敗表現」で使う
// カスタムエラークラスと、unknown を安全に扱うための変換関数。
//
// この章の方針:
//   - 呼び出し側にできることが無い失敗（設定不備・バグ・外部の障害）は throw する
//   - 呼び出し側が必ず対処すべき失敗は Result で返す（result.ts / shop.ts）

/** 設定不備など「呼び出し側にできることが無い」失敗。これは throw する */
export class ConfigError extends Error {
  // Error を継承しただけでは name が 'Error' のままなので、明示的に上書きする
  override readonly name = 'ConfigError';

  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
  }
}

/** 「起きないはず」の状態に到達したことを表す。バグの通知なので throw する */
export class InvariantError extends Error {
  override readonly name = 'InvariantError';

  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
  }
}

/** 外部（ファイル・API）からの読み込みに失敗した。cause に元のエラーを残す */
export class FixtureReadError extends Error {
  override readonly name = 'FixtureReadError';
  readonly fileName: string;

  constructor(fileName: string, options?: ErrorOptions) {
    super(`データの読み込みに失敗しました: ${fileName}`, options);
    this.fileName = fileName;
  }
}

/** 投げられた値を必ず Error に正規化する（Error 以外も投げられるため） */
export function toError(value: unknown): Error {
  if (value instanceof Error) {
    return value;
  }
  return new Error(`Error ではない値が投げられました: ${String(value)}`, { cause: value });
}

/** 表示・ログ用の1文にする。Error でない値も落ちずに文字列化する */
export function toMessage(value: unknown): string {
  if (value instanceof Error) {
    return value.message;
  }
  if (typeof value === 'string') {
    return value;
  }
  return String(value);
}

/** cause をたどって「原因の連鎖」を1行にする */
export function describeErrorChain(value: unknown): string {
  const parts: string[] = [];
  let current: unknown = value;

  // cause が循環していても止まるように、たどる深さに上限を設けている
  for (let depth = 0; depth < 5; depth += 1) {
    if (current === undefined || current === null) {
      break;
    }
    parts.push(current instanceof Error ? `${current.name}: ${current.message}` : String(current));
    current = current instanceof Error ? current.cause : undefined;
  }
  return parts.join(' <- ');
}

/**
 * ログに出してはいけないキーの部分文字列。
 * passwordHash は 'password' に、sessionId は 'session' に部分一致する。
 */
const SENSITIVE_KEY_PARTS = [
  'password',
  'token',
  'secret',
  'authorization',
  'session',
  'card',
  'cvv',
] as const;

/** そのキーの値をログに出してよいかを判定する */
export function isSensitiveKey(key: string): boolean {
  const lower = key.toLowerCase();
  return SENSITIVE_KEY_PARTS.some((part) => lower.includes(part));
}

/** 機密になりうる値を伏せた、ログに出してよいオブジェクトを作る（1階層だけ） */
export function maskSensitive(input: Record<string, unknown>): Record<string, unknown> {
  const masked: Record<string, unknown> = {};

  for (const [key, value] of Object.entries(input)) {
    masked[key] = isSensitiveKey(key) ? '[REDACTED]' : value;
  }
  return masked;
}

export type LogSafeError = { name: string; message: string; chain: string };

/** エラーから「ログに出してよい部分」だけを取り出す */
export function toLogSafeError(value: unknown): LogSafeError {
  const error = toError(value);

  return {
    name: error.name,
    message: error.message,
    chain: describeErrorChain(error),
  };
}
