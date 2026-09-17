// 認可（何をしてよいか）の判定だけを集めたモジュール（セッション25）。
//
// このファイルには node:crypto も Prisma も import しない。middleware.ts は
// Edge ランタイムで動き、そこでは Node.js 組み込みモジュールや PrismaClient が
// 使えないため、「middleware とサーバー側の両方から読める純粋な判定」だけを置く。

/** セッションIDを入れる Cookie の名前。middleware とサーバー側で同じ名前を使う */
export const SESSION_COOKIE_NAME = 'shop_session';

/** 役割。'user'（一般の利用者）と 'admin'（管理者）の2つだけ */
export type Role = 'user' | 'admin';

/** ログイン中の利用者。パスワードのハッシュはここに入れない（画面まで運ばない） */
export type SessionUser = {
  id: number;
  email: string;
  name: string;
  role: Role;
};

/** 注文のうち「誰のものか」を判定するために必要な最小限 */
export type OrderRef = {
  id: number;
  userId: number;
};

/** 認可に失敗した理由。HTTP のステータスコードに1対1で対応させる */
export type AuthzFailure = { kind: 'unauthenticated' } | { kind: 'forbidden' };

/**
 * データベースの role カラムは String なので、アプリのリテラル型に変換する。
 * 知らない値は最も権限の小さい 'user' に寄せる（迷ったら弱いほうへ）。
 */
export function parseRole(raw: string): Role {
  return raw === 'admin' ? 'admin' : 'user';
}

/** 管理画面を見てよいか。未ログイン（undefined）は当然 false */
export function canAccessAdmin(user: SessionUser | undefined): boolean {
  return user !== undefined && user.role === 'admin';
}

/**
 * その注文を見てよいか。本書の方針は「自分の注文だけ」。
 * 管理者もこの関数では他人の注文を見られない（管理者は管理画面という別の入口から見る）。
 */
export function canViewOrder(user: SessionUser | undefined, order: OrderRef): boolean {
  return user !== undefined && order.userId === user.id;
}

/** 管理画面へのアクセスを判定する。通ってよいときだけ null を返す */
export function judgeAdminAccess(user: SessionUser | undefined): AuthzFailure | null {
  if (user === undefined) {
    return { kind: 'unauthenticated' };
  }

  if (!canAccessAdmin(user)) {
    return { kind: 'forbidden' };
  }

  return null;
}

/** 注文の閲覧を判定する。通ってよいときだけ null を返す */
export function judgeOrderAccess(
  user: SessionUser | undefined,
  order: OrderRef
): AuthzFailure | null {
  if (user === undefined) {
    return { kind: 'unauthenticated' };
  }

  if (!canViewOrder(user, order)) {
    return { kind: 'forbidden' };
  }

  return null;
}

/** 失敗の理由をステータスコードに翻訳する（未ログインは401・権限不足は403） */
export function statusForFailure(failure: AuthzFailure): 401 | 403 {
  switch (failure.kind) {
    case 'unauthenticated':
      return 401;
    case 'forbidden':
      return 403;
    default: {
      const unreachable: never = failure;

      throw new Error(`未知の失敗です: ${JSON.stringify(unreachable)}`);
    }
  }
}

/**
 * ログイン後に戻る先を決める。自サイトの中のパスだけを通し、
 * それ以外はトップページに落とす（外部サイトへ飛ばされるのを防ぐ）。
 */
export function resolveNextPath(raw: string | null | undefined): string {
  if (raw === null || raw === undefined || raw === '') {
    return '/';
  }

  // http://... のような絶対URLを弾く
  if (!raw.startsWith('/')) {
    return '/';
  }

  // //evil.example.com は「プロトコル相対URL」で、外部サイトへの絶対URLとして扱われる
  if (raw.startsWith('//')) {
    return '/';
  }

  // 逆スラッシュを / と解釈するブラウザがあるので、含む値は通さない
  if (raw.includes('\\')) {
    return '/';
  }

  return raw;
}
