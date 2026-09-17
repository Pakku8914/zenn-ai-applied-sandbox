// セッション25「認証と認可」の検証スクリプト。
//
// この章の実装は web フォルダ側（lib の auth.ts / session.ts / authz.ts と
// middleware.ts）にあり、src 側からは import できない。ただしこの章の中身は
// ほとんどが Node.js 組み込みの node:crypto と純粋な判定なので、
// パスワードのハッシュ化と照合・Cookie の組み立てと解析・セッションIDの生成・
// ロールベース認可・有効期限の判定は、ここで同じ実装を動かして確かめられる。
//
// データベースを使う部分（利用者の取得・セッションの永続化）の型は、
// verify-all.sh の最後に走る web の型チェックと next build が担保する。
//
// 実行: docker compose exec ts npx tsx src/session25/verify.ts

import { createHash, randomBytes, scrypt, scryptSync, timingSafeEqual } from 'node:crypto';
import { promisify } from 'node:util';

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

// ---------------------------------------------------------------------------
// 本文3節：パスワードのハッシュ化（web の lib/auth.ts と同じ実装）
// ---------------------------------------------------------------------------
const SALT_BYTES = 16;
const KEY_BYTES = 64;

type ScryptAsync = (password: string, salt: Buffer, keyBytes: number) => Promise<Buffer>;

const scryptAsync = promisify(scrypt) as ScryptAsync;

async function hashPassword(password: string): Promise<string> {
  const salt = randomBytes(SALT_BYTES);
  const derivedKey = await scryptAsync(password, salt, KEY_BYTES);

  return `${salt.toString('hex')}:${derivedKey.toString('hex')}`;
}

async function verifyPassword(password: string, stored: string): Promise<boolean> {
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

  // timingSafeEqual は長さが違うと例外を投げるので、先に長さを確かめる
  if (actual.length !== expected.length) {
    return false;
  }

  return timingSafeEqual(actual, expected);
}

/** prisma/seed.ts と同じ、同期版（scryptSync）で作ったハッシュ */
function hashPasswordSync(password: string): string {
  const salt = randomBytes(SALT_BYTES);

  return `${salt.toString('hex')}:${scryptSync(password, salt, KEY_BYTES).toString('hex')}`;
}

/** ソルトを使わない素朴なハッシュ（危険な例。同じ入力から必ず同じ値が出る） */
function naiveHash(password: string): string {
  return createHash('sha256').update(password).digest('hex');
}

/** timingSafeEqual が長さの違いで例外を投げることを確かめる */
function throwsOnLengthMismatch(): boolean {
  try {
    timingSafeEqual(Buffer.alloc(8), Buffer.alloc(16));

    return false;
  } catch {
    return true;
  }
}

// ---------------------------------------------------------------------------
// 本文5節：セッションIDの生成
// ---------------------------------------------------------------------------
const SESSION_ID_BYTES = 32;

function createSessionId(): string {
  return randomBytes(SESSION_ID_BYTES).toString('hex');
}

/** 予測できてしまう作り方（悪い例）。連番なので次の値が分かる */
function weakSessionId(counter: number): string {
  return `session-${counter}`;
}

function predictNextWeakId(previous: string): string {
  const counter = Number(previous.replace('session-', ''));

  return `session-${counter + 1}`;
}

// ---------------------------------------------------------------------------
// 本文6節：Cookie の組み立てと解析
// ---------------------------------------------------------------------------
type SameSite = 'lax' | 'strict' | 'none';

type CookieOptions = {
  httpOnly: boolean;
  secure: boolean;
  sameSite: SameSite;
  path: string;
  maxAge: number;
};

function formatSameSite(sameSite: SameSite): string {
  switch (sameSite) {
    case 'lax':
      return 'Lax';
    case 'strict':
      return 'Strict';
    case 'none':
      return 'None';
    default: {
      const unreachable: never = sameSite;

      throw new Error(`未知の SameSite です: ${String(unreachable)}`);
    }
  }
}

/** Next.js の cookies().set が実際に組み立てる Set-Cookie ヘッダと同じ形を作る */
function buildSetCookie(name: string, value: string, options: CookieOptions): string {
  const parts = [
    `${name}=${value}`,
    `Path=${options.path}`,
    `Max-Age=${String(options.maxAge)}`,
    `SameSite=${formatSameSite(options.sameSite)}`,
  ];

  if (options.httpOnly) {
    parts.push('HttpOnly');
  }

  if (options.secure) {
    parts.push('Secure');
  }

  return parts.join('; ');
}

const REQUIRED_COOKIE_ATTRIBUTES = ['HttpOnly', 'Secure', 'SameSite=Lax', 'Path=/', 'Max-Age='];

/** 必須の属性のうち、欠けているものを挙げる（1つでも欠けたら検出できる） */
function missingCookieAttributes(setCookie: string): string[] {
  return REQUIRED_COOKIE_ATTRIBUTES.filter((attribute) => !setCookie.includes(attribute));
}

/** ブラウザが送ってくる Cookie ヘッダ（「名前=値; 名前=値」）を分解する */
function parseCookieHeader(header: string): Map<string, string> {
  const jar = new Map<string, string>();

  for (const part of header.split(';')) {
    const trimmed = part.trim();
    const separator = trimmed.indexOf('=');

    if (separator > 0) {
      jar.set(trimmed.slice(0, separator), trimmed.slice(separator + 1));
    }
  }

  return jar;
}

function readCookie(header: string, name: string): string | undefined {
  return parseCookieHeader(header).get(name);
}

// ---------------------------------------------------------------------------
// 本文6節：セッションの有効期限とログアウト
// ---------------------------------------------------------------------------
type SessionRecord = { userId: number; expiresAt: number };

const SESSION_MAX_AGE_SECONDS = 60 * 60 * 8;

function isSessionExpired(record: SessionRecord, now: number): boolean {
  return record.expiresAt <= now;
}

// ---------------------------------------------------------------------------
// 本文9節：ロールベース認可（web の lib/authz.ts と同じ実装）
// ---------------------------------------------------------------------------
type Role = 'user' | 'admin';

type SessionUser = { id: number; email: string; name: string; role: Role };

type OrderRef = { id: number; userId: number };

type AuthzFailure = { kind: 'unauthenticated' } | { kind: 'forbidden' };

function parseRole(raw: string): Role {
  return raw === 'admin' ? 'admin' : 'user';
}

function canAccessAdmin(user: SessionUser | undefined): boolean {
  return user !== undefined && user.role === 'admin';
}

function canViewOrder(user: SessionUser | undefined, order: OrderRef): boolean {
  return user !== undefined && order.userId === user.id;
}

function judgeAdminAccess(user: SessionUser | undefined): AuthzFailure | null {
  if (user === undefined) {
    return { kind: 'unauthenticated' };
  }

  if (!canAccessAdmin(user)) {
    return { kind: 'forbidden' };
  }

  return null;
}

function judgeOrderAccess(user: SessionUser | undefined, order: OrderRef): AuthzFailure | null {
  if (user === undefined) {
    return { kind: 'unauthenticated' };
  }

  if (!canViewOrder(user, order)) {
    return { kind: 'forbidden' };
  }

  return null;
}

function statusForFailure(failure: AuthzFailure): 401 | 403 {
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

/** 判定結果を短い文字列にして比べやすくする */
function summarizeAccess(failure: AuthzFailure | null): string {
  return failure === null ? 'allowed' : `${failure.kind}:${String(statusForFailure(failure))}`;
}

function resolveNextPath(raw: string | null | undefined): string {
  if (raw === null || raw === undefined || raw === '') {
    return '/';
  }

  if (!raw.startsWith('/') || raw.startsWith('//') || raw.includes('\\')) {
    return '/';
  }

  return raw;
}

// ---------------------------------------------------------------------------
// 本文3節：パスワードの決まり（web の lib/auth.ts と同じ実装）
// ---------------------------------------------------------------------------
const PASSWORD_MIN_LENGTH = 8;

type PasswordPolicyFailure =
  | { kind: 'too_short'; minLength: number }
  | { kind: 'no_letter' }
  | { kind: 'no_digit' };

function checkPasswordPolicy(password: string): PasswordPolicyFailure | null {
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

// ---------------------------------------------------------------------------
// 検証本体
// ---------------------------------------------------------------------------
async function main(): Promise<void> {
  // --- 3節：ハッシュ化と照合 ---------------------------------------------
  const password = 'lavender-2026';
  const storedA = await hashPassword(password);
  const storedB = await hashPassword(password);

  checkBoolean('本文3節: 同じパスワードでも毎回違うハッシュになる', storedA === storedB, false);
  checkBoolean(
    '本文3節: 保存する形は <ソルト(hex)>:<ハッシュ(hex)>',
    /^[0-9a-f]{32}:[0-9a-f]{128}$/.test(storedA),
    true
  );
  checkNumber('本文3節: ソルトは16バイト', Buffer.from(storedA.split(':')[0] ?? '', 'hex').length, 16);
  checkNumber('本文3節: ハッシュは64バイト', Buffer.from(storedA.split(':')[1] ?? '', 'hex').length, 64);

  checkBoolean('本文3節: 正しいパスワードで照合できる', await verifyPassword(password, storedA), true);
  checkBoolean(
    '本文3節: 別のソルトで作ったハッシュとも照合できる',
    await verifyPassword(password, storedB),
    true
  );
  checkBoolean(
    '本文3節: 1文字違うパスワードは通らない',
    await verifyPassword('lavender-2027', storedA),
    false
  );
  checkBoolean('本文3節: 空のパスワードは通らない', await verifyPassword('', storedA), false);
  checkBoolean(
    '本文3節: 大文字小文字が違えば通らない',
    await verifyPassword('Lavender-2026', storedA),
    false
  );

  // 保存側が壊れていても例外にせず false を返す（画面が500にならないように）
  checkBoolean('本文3節: 区切りが無い保存値', await verifyPassword(password, 'broken'), false);
  checkBoolean('本文3節: ハッシュが空の保存値', await verifyPassword(password, `${'ab'.repeat(16)}:`), false);
  checkBoolean(
    '本文3節: 長さが足りないハッシュの保存値',
    await verifyPassword(password, `${'ab'.repeat(16)}:${'cd'.repeat(8)}`),
    false
  );

  // prisma/seed.ts は scryptSync で作る。形式が同じなので同じ関数で照合できる
  const storedFromSeed = hashPasswordSync('demo-pass-2026');

  checkBoolean(
    '本文3節: scryptSync で作ったハッシュも同じ関数で照合できる',
    await verifyPassword('demo-pass-2026', storedFromSeed),
    true
  );
  checkBoolean(
    '本文3節: scryptSync で作ったハッシュも間違いは弾く',
    await verifyPassword('demo-pass-2027', storedFromSeed),
    false
  );

  // ソルトが無いと、同じパスワードから必ず同じ値が出る（レインボーテーブルが効く）
  checkBoolean(
    '本文3節: ソルト無しのハッシュは同じ値になってしまう',
    naiveHash('password123') === naiveHash('password123'),
    true
  );
  checkNumber('本文3節: ソルト無しのハッシュの長さ（sha256 は32バイト）', naiveHash('password123').length, 64);
  checkBoolean(
    '本文3節: 違うパスワードなら違う値になる（それは当然）',
    naiveHash('password123') === naiveHash('password124'),
    false
  );

  checkBoolean('本文3節: timingSafeEqual は長さが違うと例外を投げる', throwsOnLengthMismatch(), true);
  checkBoolean(
    '本文3節: 同じ長さ・同じ内容なら true',
    timingSafeEqual(Buffer.from('abcd'), Buffer.from('abcd')),
    true
  );
  checkBoolean(
    '本文3節: 同じ長さ・違う内容なら false',
    timingSafeEqual(Buffer.from('abcd'), Buffer.from('abce')),
    false
  );

  // --- 2節：パスワードの決まり -------------------------------------------
  checkJson('本文3節: 短すぎる', checkPasswordPolicy('abc123'), { kind: 'too_short', minLength: 8 });
  checkJson('本文3節: 数字だけ', checkPasswordPolicy('12345678'), { kind: 'no_letter' });
  checkJson('本文3節: 英字だけ', checkPasswordPolicy('abcdefgh'), { kind: 'no_digit' });
  checkJson('本文3節: 決まりを満たす', checkPasswordPolicy('lavender2026'), null);

  // --- 4節：セッションIDの生成 -------------------------------------------
  const sessionId = createSessionId();

  checkNumber('本文5節: セッションIDは64文字（32バイトの16進数）', sessionId.length, 64);
  checkBoolean('本文5節: 16進数の文字だけ', /^[0-9a-f]{64}$/.test(sessionId), true);

  const generated = new Set<string>();

  for (let index = 0; index < 200; index += 1) {
    generated.add(createSessionId());
  }

  checkNumber('本文5節: 200回作って重複なし', generated.size, 200);

  // Math.random を使った作り方は「予測できる」ことが問題。連番はその極端な例
  const firstWeak = weakSessionId(1);

  checkString('本文5節: 連番のIDは次の値を当てられる', predictNextWeakId(firstWeak), weakSessionId(2));
  checkNumber('本文5節: randomBytes(32) のビット数', SESSION_ID_BYTES * 8, 256);
  checkBoolean('本文5節: Math.random の52ビットでは足りない', 52 < SESSION_ID_BYTES * 8, true);

  // --- 5節：Cookie の組み立てと解析 --------------------------------------
  const setCookie = buildSetCookie('shop_session', sessionId, {
    httpOnly: true,
    secure: true,
    sameSite: 'lax',
    path: '/',
    maxAge: SESSION_MAX_AGE_SECONDS,
  });

  checkJson('本文6節: 必須の属性がすべて付いている', missingCookieAttributes(setCookie), []);
  checkBoolean('本文6節: 有効期間は8時間（28800秒）', setCookie.includes('Max-Age=28800'), true);
  checkNumber('本文6節: 有効期間の秒数', SESSION_MAX_AGE_SECONDS, 28800);

  // 属性が1つ欠けたら検出できることを確かめる（欠けを見逃す検査は役に立たない）
  const withoutHttpOnly = buildSetCookie('shop_session', sessionId, {
    httpOnly: false,
    secure: true,
    sameSite: 'lax',
    path: '/',
    maxAge: SESSION_MAX_AGE_SECONDS,
  });
  const withoutSecure = buildSetCookie('shop_session', sessionId, {
    httpOnly: true,
    secure: false,
    sameSite: 'lax',
    path: '/',
    maxAge: SESSION_MAX_AGE_SECONDS,
  });
  const withSameSiteNone = buildSetCookie('shop_session', sessionId, {
    httpOnly: true,
    secure: true,
    sameSite: 'none',
    path: '/',
    maxAge: SESSION_MAX_AGE_SECONDS,
  });

  checkJson('本文6節: HttpOnly の欠けを検出', missingCookieAttributes(withoutHttpOnly), ['HttpOnly']);
  checkJson('本文6節: Secure の欠けを検出', missingCookieAttributes(withoutSecure), ['Secure']);
  checkJson('本文6節: SameSite=Lax でないことを検出', missingCookieAttributes(withSameSiteNone), [
    'SameSite=Lax',
  ]);

  // ログアウトの Cookie は「値が空・寿命0」。属性は発行時とそろえる
  const logoutCookie = buildSetCookie('shop_session', '', {
    httpOnly: true,
    secure: true,
    sameSite: 'lax',
    path: '/',
    maxAge: 0,
  });

  checkBoolean('本文6節: ログアウトの Cookie は Max-Age=0', logoutCookie.includes('Max-Age=0'), true);
  checkString('本文6節: ログアウトの Cookie の値は空', logoutCookie.split(';')[0] ?? '', 'shop_session=');

  const requestHeader = `theme=light; shop_session=${sessionId}; cart_hint=3`;

  checkString('本文6節: 複数の Cookie から目的の値を取り出す', readCookie(requestHeader, 'shop_session') ?? '', sessionId);
  checkString('本文6節: 別の Cookie も取り出せる', readCookie(requestHeader, 'theme') ?? '', 'light');
  checkBoolean(
    '本文6節: 無い名前は undefined',
    readCookie(requestHeader, 'session') === undefined,
    true
  );
  checkBoolean('本文6節: 空のヘッダでも例外にならない', readCookie('', 'shop_session') === undefined, true);
  checkNumber('本文6節: Cookie の個数', parseCookieHeader(requestHeader).size, 3);

  // --- 6節：有効期限とログアウト -----------------------------------------
  const baseTime = 1_800_000_000_000;
  const record: SessionRecord = { userId: 1, expiresAt: baseTime + SESSION_MAX_AGE_SECONDS * 1000 };

  checkBoolean('本文6節: 期限内は有効', isSessionExpired(record, baseTime), false);
  checkBoolean('本文6節: 期限の1ミリ秒前は有効', isSessionExpired(record, record.expiresAt - 1), false);
  checkBoolean('本文6節: 期限ちょうどは切れている扱い', isSessionExpired(record, record.expiresAt), true);
  checkBoolean('本文6節: 期限後は切れている', isSessionExpired(record, record.expiresAt + 1), true);

  // ログアウト＝サーバー側の記録を消す。Cookie が残っていても通らなくなる
  const store = new Map<string, SessionRecord>();

  store.set(sessionId, record);
  checkNumber('本文6節: ログイン中はセッションの記録がある', store.size, 1);
  checkBoolean('本文6節: 記録から利用者が引ける', store.get(sessionId)?.userId === 1, true);

  store.delete(sessionId);
  checkNumber('本文6節: ログアウトで記録が消える', store.size, 0);
  checkBoolean(
    '本文6節: Cookie が残っていても記録が無ければ未ログイン',
    store.get(sessionId) === undefined,
    true
  );

  // --- 8節：ロールベース認可 ---------------------------------------------
  const demoUser: SessionUser = {
    id: 1,
    email: 'demo@example.com',
    name: 'デモユーザー',
    role: 'user',
  };
  const otherUser: SessionUser = {
    id: 2,
    email: 'other@example.com',
    name: 'ほかの人',
    role: 'user',
  };
  const adminUser: SessionUser = {
    id: 3,
    email: 'admin@example.com',
    name: '管理者',
    role: 'admin',
  };
  const demoOrder: OrderRef = { id: 10, userId: 1 };

  checkString('本文9節: role の文字列を型に変換（user）', parseRole('user'), 'user');
  checkString('本文9節: role の文字列を型に変換（admin）', parseRole('admin'), 'admin');
  checkString('本文9節: 知らない role は user に寄せる', parseRole('superadmin'), 'user');
  checkString('本文9節: 空文字も user に寄せる', parseRole(''), 'user');

  checkBoolean('本文9節: 未ログインは管理画面に入れない', canAccessAdmin(undefined), false);
  checkBoolean('本文9節: 一般の利用者は管理画面に入れない', canAccessAdmin(demoUser), false);
  checkBoolean('本文9節: 管理者は管理画面に入れる', canAccessAdmin(adminUser), true);

  checkBoolean('本文9節: 自分の注文は見える', canViewOrder(demoUser, demoOrder), true);
  checkBoolean('本文9節: 他人の注文は見えない', canViewOrder(otherUser, demoOrder), false);
  checkBoolean('本文9節: 未ログインでは見えない', canViewOrder(undefined, demoOrder), false);
  checkBoolean('本文9節: 管理者でも他人の注文はこの入口では見えない', canViewOrder(adminUser, demoOrder), false);

  checkString('本文9節: 未ログインの管理画面は401', summarizeAccess(judgeAdminAccess(undefined)), 'unauthenticated:401');
  checkString('本文9節: 権限不足の管理画面は403', summarizeAccess(judgeAdminAccess(demoUser)), 'forbidden:403');
  checkString('本文9節: 管理者は通る', summarizeAccess(judgeAdminAccess(adminUser)), 'allowed');
  checkString(
    '本文9節: 未ログインの注文閲覧は401',
    summarizeAccess(judgeOrderAccess(undefined, demoOrder)),
    'unauthenticated:401'
  );
  checkString(
    '本文9節: 他人の注文の閲覧は403',
    summarizeAccess(judgeOrderAccess(otherUser, demoOrder)),
    'forbidden:403'
  );
  checkString(
    '本文9節: 自分の注文の閲覧は通る',
    summarizeAccess(judgeOrderAccess(demoUser, demoOrder)),
    'allowed'
  );

  // 他人の注文を1件ずつ試しても、1つも通らないことを確かめる
  const allOrders: OrderRef[] = [
    { id: 10, userId: 1 },
    { id: 11, userId: 2 },
    { id: 12, userId: 2 },
    { id: 13, userId: 3 },
  ];

  checkJson(
    '本文9節: demoUser に見える注文は自分のものだけ',
    allOrders.filter((order) => canViewOrder(demoUser, order)).map((order) => order.id),
    [10]
  );
  checkNumber(
    '本文9節: demoUser が他人の注文を見られた回数',
    allOrders.filter((order) => order.userId !== demoUser.id && canViewOrder(demoUser, order)).length,
    0
  );

  // --- 7節：ログイン後の戻り先 -------------------------------------------
  checkString('本文7節: 自サイトのパスは通す', resolveNextPath('/orders'), '/orders');
  checkString('本文7節: クエリ付きも通す', resolveNextPath('/orders?page=2'), '/orders?page=2');
  checkString('本文7節: 外部サイトのURLは通さない', resolveNextPath('https://evil.example.com'), '/');
  checkString('本文7節: プロトコル相対URLも通さない', resolveNextPath('//evil.example.com'), '/');
  checkString('本文7節: 逆スラッシュを含む値も通さない', resolveNextPath('/\\evil.example.com'), '/');
  checkString('本文7節: 指定が無ければトップへ', resolveNextPath(null), '/');
  checkString('本文7節: 空文字もトップへ', resolveNextPath(''), '/');

  // ---------------------------------------------------------------------------
  // 結果
  // ---------------------------------------------------------------------------
  if (failedCount > 0) {
    console.error(`session25: ${failedCount} 件の検証に失敗しました`);
    process.exit(1);
  }

  console.log('session25: ok');
}

main().catch((error: unknown) => {
  console.error(error);
  process.exit(1);
});
