// セッションの作成・取得・破棄（セッション25）。
//
// Cookie に入れるのはセッションIDだけ。「誰のセッションか」「いつまで有効か」は
// サーバー側に持つ。だからログアウトはサーバー側の記録を消すだけで即座に無効化できる。
//
// 本書はセッションの置き場所をサーバーのメモリ（Map）にしている。学習用に道具を
// 増やさないためで、プロセスを再起動すると消える（＝全員ログアウトになる）。
// 実務ではデータベースや Redis のような外部の記憶に置く。

import { randomBytes } from 'node:crypto';
import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { prisma } from '@/lib/db';
import { SESSION_COOKIE_NAME, canAccessAdmin, parseRole, type SessionUser } from '@/lib/authz';

/** セッションの有効期間（秒）。8時間 */
export const SESSION_MAX_AGE_SECONDS = 60 * 60 * 8;

/** セッションIDの長さ（バイト）。32バイト＝256ビット */
const SESSION_ID_BYTES = 32;

/** サーバー側に持つセッションの中身 */
export type SessionRecord = {
  userId: number;
  /** 有効期限（エポックミリ秒） */
  expiresAt: number;
};

// 開発中のホットリロードで Map が作り直されないよう、lib/db.ts と同じ方法で globalThis に置く
const globalForSession = globalThis as unknown as {
  sessionStore?: Map<string, SessionRecord>;
};

const sessionStore: Map<string, SessionRecord> =
  globalForSession.sessionStore ?? new Map<string, SessionRecord>();

globalForSession.sessionStore = sessionStore;

/** 推測できないセッションIDを作る。Math.random() は使わない（本文の第5節） */
export function createSessionId(): string {
  return randomBytes(SESSION_ID_BYTES).toString('hex');
}

/** 期限が来ているか。境界（ちょうど期限の瞬間）は切れている扱いにする */
export function isSessionExpired(record: SessionRecord, now: number): boolean {
  return record.expiresAt <= now;
}

/** ログインに成功したときに呼ぶ。セッションを記録し、Cookie を発行する */
export async function createSession(userId: number): Promise<void> {
  const sessionId = createSessionId();

  sessionStore.set(sessionId, {
    userId,
    expiresAt: Date.now() + SESSION_MAX_AGE_SECONDS * 1000,
  });

  const jar = await cookies();

  jar.set(SESSION_COOKIE_NAME, sessionId, {
    // JavaScript から読めなくする。document.cookie に現れない
    httpOnly: true,
    // 本番は HTTPS のときだけ送る。開発は http://localhost なので付けない
    secure: process.env.NODE_ENV === 'production',
    // 別サイトから送られた POST には付けない
    sameSite: 'lax',
    // サイト全体で有効にする
    path: '/',
    maxAge: SESSION_MAX_AGE_SECONDS,
  });
}

/** いまログインしているのは誰か。未ログイン・期限切れ・記録が無い場合は undefined */
export async function getSessionUser(): Promise<SessionUser | undefined> {
  const jar = await cookies();
  const sessionId = jar.get(SESSION_COOKIE_NAME)?.value;

  if (sessionId === undefined || sessionId === '') {
    return undefined;
  }

  const record = sessionStore.get(sessionId);

  // 記録が無い＝ログアウト済み・サーバー再起動後・偽の Cookie。Cookie の有無では判断しない
  if (record === undefined) {
    return undefined;
  }

  if (isSessionExpired(record, Date.now())) {
    sessionStore.delete(sessionId);

    return undefined;
  }

  // 役割は毎回データベースから読む。セッションに焼き付けると、権限を変えても反映されない
  const user = await prisma.user.findUnique({
    where: { id: record.userId },
    // passwordHash は取らない。必要のない秘密は画面まで運ばない
    select: { id: true, email: true, name: true, role: true },
  });

  if (user === null) {
    sessionStore.delete(sessionId);

    return undefined;
  }

  return { id: user.id, email: user.email, name: user.name, role: parseRole(user.role) };
}

/** ログアウト。サーバー側の記録を消し、Cookie も空にする */
export async function destroySession(): Promise<void> {
  const jar = await cookies();
  const sessionId = jar.get(SESSION_COOKIE_NAME)?.value;

  if (sessionId !== undefined) {
    sessionStore.delete(sessionId);
  }

  // 発行したときと同じ属性で、値を空・寿命0にする
  jar.set(SESSION_COOKIE_NAME, '', {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: '/',
    maxAge: 0,
  });
}

/**
 * ログインが必要なページの先頭で呼ぶ。未ログインならログイン画面へ送る。
 * 戻り値が SessionUser なので、呼び出した先では「ログイン済み」が型で保証される。
 */
export async function requireSessionUser(nextPath: string): Promise<SessionUser> {
  const user = await getSessionUser();

  if (user === undefined) {
    // redirect は never を返す（ここから先は実行されない）
    redirect(`/login?next=${encodeURIComponent(nextPath)}`);
  }

  return user;
}

/**
 * その利用者のセッションをすべて消す（パスワードを変えたときに使う）。
 * 戻り値は消した件数。他の端末に残っているログイン状態も無効になる。
 */
export function deleteSessionsForUser(userId: number): number {
  let deleted = 0;

  for (const [sessionId, record] of sessionStore) {
    if (record.userId === userId) {
      sessionStore.delete(sessionId);
      deleted += 1;
    }
  }

  return deleted;
}

/** 管理者かどうかまで確かめたいときに使う。判定そのものは lib/authz.ts に置いてある */
export async function isAdminSession(): Promise<boolean> {
  return canAccessAdmin(await getSessionUser());
}
