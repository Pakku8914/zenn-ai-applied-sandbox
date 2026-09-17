// パスワードのハッシュ化と照合（セッション25）。
//
// 使うのは Node.js 組み込みの node:crypto の scrypt。bcrypt / argon2 は
// ネイティブのビルドを伴うため、Docker イメージやデプロイ先で詰まりやすい。
// scrypt は追加インストール無しで同じ目的（時間のかかる一方向の変換）を果たせる。
//
// 保存する形は「<ソルト(hex)>:<ハッシュ(hex)>」。prisma/seed.ts が入れる形と同じ。

import { randomBytes, scrypt, timingSafeEqual } from 'node:crypto';
import { promisify } from 'node:util';

/** ソルトの長さ（バイト）。16バイト＝128ビットあれば重複は現実的に起きない */
const SALT_BYTES = 16;

/** 導き出す鍵（ハッシュ）の長さ（バイト） */
const KEY_BYTES = 64;

/** パスワードの最低文字数 */
export const PASSWORD_MIN_LENGTH = 8;

/**
 * scrypt はコールバックを受け取る関数で、引数の組み合わせが2通りある（オーバーロード）。
 * promisify の戻り値の型はそのうちの1つに決まってしまうため、使う形を型で宣言して受け取る。
 */
type ScryptAsync = (password: string, salt: Buffer, keyBytes: number) => Promise<Buffer>;

// 同期版の scryptSync ではなく非同期版を使う。scrypt はわざと時間のかかる計算なので、
// 同期版を Server Action の中で呼ぶと、その間サーバーが他の要求を1つも処理できなくなる。
const scryptAsync = promisify(scrypt) as ScryptAsync;

/**
 * パスワードから「ソルト:ハッシュ」の文字列を作る。
 * ソルトが毎回変わるので、同じパスワードでも毎回違う値になる。
 */
export async function hashPassword(password: string): Promise<string> {
  const salt = randomBytes(SALT_BYTES);
  const derivedKey = await scryptAsync(password, salt, KEY_BYTES);

  return `${salt.toString('hex')}:${derivedKey.toString('hex')}`;
}

/**
 * 保存してある「ソルト:ハッシュ」と、入力されたパスワードが一致するか。
 * 保存側の形が壊れていても例外にせず「一致しない」として扱う。
 */
export async function verifyPassword(password: string, stored: string): Promise<boolean> {
  const parts = stored.split(':');
  const saltHex = parts[0];
  const keyHex = parts[1];

  if (parts.length !== 2 || saltHex === undefined || keyHex === undefined) {
    return false;
  }

  const expected = Buffer.from(keyHex, 'hex');

  if (expected.length !== KEY_BYTES) {
    return false;
  }

  const actual = await scryptAsync(password, Buffer.from(saltHex, 'hex'), KEY_BYTES);

  // timingSafeEqual は長さが違うと例外を投げる。先に長さをそろえたことを確かめる
  if (actual.length !== expected.length) {
    return false;
  }

  // 1バイト目から違っていても最後まで比べる（比較にかかる時間から答えを推測されないため）
  return timingSafeEqual(actual, expected);
}

/**
 * 存在しないメールアドレスでログインを試されたときに、
 * 実在する場合と同じだけ計算するためのダミー。どのパスワードにも一致しない。
 */
export const DUMMY_PASSWORD_HASH = `00112233445566778899aabbccddeeff:${'0123456789abcdef'.repeat(8)}`;

/** パスワードの決まりを満たさない理由 */
export type PasswordPolicyFailure =
  | { kind: 'too_short'; minLength: number }
  | { kind: 'no_letter' }
  | { kind: 'no_digit' };

/** パスワードの決まりを確かめる。問題が無ければ null */
export function checkPasswordPolicy(password: string): PasswordPolicyFailure | null {
  if (password.length < PASSWORD_MIN_LENGTH) {
    return { kind: 'too_short', minLength: PASSWORD_MIN_LENGTH };
  }

  if (!/[A-Za-z]/.test(password)) {
    return { kind: 'no_letter' };
  }

  if (!/[0-9]/.test(password)) {
    return { kind: 'no_digit' };
  }

  return null;
}

/** 決まりを満たさない理由を、画面に出す日本語にする */
export function describePasswordPolicyFailure(failure: PasswordPolicyFailure): string {
  switch (failure.kind) {
    case 'too_short':
      return `パスワードは${failure.minLength}文字以上にしてください`;
    case 'no_letter':
      return 'パスワードに英字を1文字以上入れてください';
    case 'no_digit':
      return 'パスワードに数字を1文字以上入れてください';
    default: {
      const unreachable: never = failure;

      throw new Error(`未知の失敗です: ${JSON.stringify(unreachable)}`);
    }
  }
}
