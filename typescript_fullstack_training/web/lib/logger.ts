// 構造化ログとリクエストID（セッション27）。
//
// ログは「あとから検索・集計できる形」で出す。文章として整形してしまうと、
// あとで「注文が作れなかったリクエストだけ集めたい」ができなくなる。
// そこで JSON を1行だけ出す（1行なら grep でも、ログ集約サービスでも扱える）。
//
// 何を出してはいけないか（パスワード・トークン・セッションID・カード番号）は
// 「セッション18：エラーハンドリングと型安全な失敗表現」で決めた方針を引き継ぎ、
// マスクの実装は「セッション26：Webアプリケーションのセキュリティ」で作った
// lib/security.ts のものをそのまま使う（同じ仕様を2か所に書かない）。
// 同じ実装を src/session27/verify.ts で検証している。

import { randomUUID } from 'node:crypto';
import { cache } from 'react';
import { maskSensitive, maskTextSecrets } from '@/lib/security';

/** ログの重要度。左から右へ重くなる */
export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

const LOG_LEVELS = ['debug', 'info', 'warn', 'error'] as const;

/** 重要度を数値にしておくと「これ以上だけ出す」の比較が1行で書ける */
const LEVEL_SEVERITY: Record<LogLevel, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
};

/** 環境変数の指定が無い・不正なときに使う重要度 */
export const DEFAULT_LOG_LEVEL: LogLevel = 'info';

/** 環境変数の文字列を LogLevel に変換する。知らない値は既定値に落とす */
export function parseLogLevel(raw: string | undefined): LogLevel {
  return LOG_LEVELS.find((level) => level === raw) ?? DEFAULT_LOG_LEVEL;
}

/** configured 以上の重要度なら出す（configured が 'info' なら 'debug' は出ない） */
export function shouldLog(configured: LogLevel, level: LogLevel): boolean {
  return LEVEL_SEVERITY[level] >= LEVEL_SEVERITY[configured];
}

// ---------------------------------------------------------------------------
// 機密のマスク（判定と置き換えは lib/security.ts に任せる）
// ---------------------------------------------------------------------------

/** ログの1行が必ず持つフィールド。追加の情報でこれを上書きさせない */
const RESERVED_KEYS = ['level', 'message', 'requestId', 'timestamp'] as const;

/** ログに添える追加情報 */
export type LogFields = Record<string, unknown>;

/**
 * 追加情報から「ログに出してよい形」を作る。
 * - 予約フィールドと同じ名前は捨てる（level などを壊されると集計できなくなる）
 * - 機密になりうるキーの値は maskSensitive が [REDACTED] に置き換える
 */
export function sanitizeFields(fields: LogFields): LogFields {
  const withoutReserved: LogFields = {};

  for (const [key, value] of Object.entries(fields)) {
    if ((RESERVED_KEYS as readonly string[]).includes(key)) {
      continue;
    }
    withoutReserved[key] = value;
  }

  return maskSensitive(withoutReserved);
}

// ---------------------------------------------------------------------------
// ログ1行の組み立て
// ---------------------------------------------------------------------------

export type LogEntry = {
  level: LogLevel;
  message: string;
  /** 同じリクエストから出たログを結びつけるための識別子 */
  requestId: string;
  /** ISO 8601 の文字列。時刻は外から渡す（テストで固定できるようにするため） */
  timestamp: string;
  fields?: LogFields;
};

/** JSON1行にする。フィールドの順番は固定（毎回同じ並びなら目でも読める） */
export function buildLogLine(entry: LogEntry): string {
  return JSON.stringify({
    level: entry.level,
    // 例外のメッセージをそのまま渡されても、文章に紛れた秘密は伏せる
    message: maskTextSecrets(entry.message),
    requestId: entry.requestId,
    timestamp: entry.timestamp,
    ...sanitizeFields(entry.fields ?? {}),
  });
}

// ---------------------------------------------------------------------------
// ロガー本体
// ---------------------------------------------------------------------------

export type Logger = {
  debug: (message: string, fields?: LogFields) => void;
  info: (message: string, fields?: LogFields) => void;
  warn: (message: string, fields?: LogFields) => void;
  error: (message: string, fields?: LogFields) => void;
};

export type LoggerOptions = {
  requestId: string;
  /** この重要度以上だけを出す */
  minLevel: LogLevel;
  /** 現在時刻を返す関数。実時間に依存させないため引数で受け取る */
  now: () => Date;
  /** 出力先。既定は標準出力／標準エラー出力 */
  write: (level: LogLevel, line: string) => void;
};

/** 標準の出力先。warn 以上は標準エラー出力に出す（本番の収集設定で分けやすい） */
function writeToConsole(level: LogLevel, line: string): void {
  if (LEVEL_SEVERITY[level] >= LEVEL_SEVERITY.warn) {
    console.error(line);
  } else {
    console.log(line);
  }
}

export function createLogger(options: LoggerOptions): Logger {
  const log = (level: LogLevel, message: string, fields?: LogFields): void => {
    if (!shouldLog(options.minLevel, level)) {
      return;
    }

    options.write(
      level,
      buildLogLine({
        level,
        message,
        requestId: options.requestId,
        timestamp: options.now().toISOString(),
        fields,
      })
    );
  };

  return {
    debug: (message, fields) => log('debug', message, fields),
    info: (message, fields) => log('info', message, fields),
    warn: (message, fields) => log('warn', message, fields),
    error: (message, fields) => log('error', message, fields),
  };
}

// ---------------------------------------------------------------------------
// リクエストIDの生成と伝播
// ---------------------------------------------------------------------------

/**
 * このリクエストのID。React の cache() は「同じリクエストの中では1回しか実行しない」
 * ので、どの部品から呼んでも同じ値が返る（＝リクエストメモ化）。
 */
export const getRequestId = cache((): string => randomUUID());

/** このリクエスト用のロガー。部品ごとに作り直さないよう、これも cache() で包む */
export const getLogger = cache(
  (): Logger =>
    createLogger({
      requestId: getRequestId(),
      minLevel: parseLogLevel(process.env['LOG_LEVEL']),
      now: () => new Date(),
      write: writeToConsole,
    })
);
