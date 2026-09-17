// すべての要求が最初に通る関所（セッション25で作り、セッション26で広げた）。
//
// ここでやることは3つ。上から順に、安い確認から並べている。
//   1. レート制限   … 数が多すぎる相手を早い段階で断る
//   2. 認証の入口確認 … Cookie が無い相手を保護されたページから弾く（セッション25）
//   3. セキュリティヘッダ … すべての応答に CSP などを付ける（セッション26）
//
// セッション25では matcher を /orders と /admin だけに絞っていた。セッション26で
// ヘッダをすべてのページに付ける必要が出たので matcher を広げ、代わりに
// 「どのパスが保護対象か」を isProtectedPath で自分で判定するようにした。
// matcher を広げたときに認証の条件を書き忘れると、トップページまで
// ログイン必須になってしまう（実際にやりがちな事故）。
//
// middleware は Edge ランタイムで動くので node:crypto と PrismaClient は使えない。
// だから本当の確認（セッションの中身・役割）はページとデータを取る関数で行う。

import { NextResponse, type NextRequest } from 'next/server';
import { SESSION_COOKIE_NAME } from '@/lib/authz';
import {
  buildSecurityHeaders,
  checkRateLimit,
  clientKey,
  cspHeaderName,
  isProtectedPath,
  createNonce,
  rateLimitRuleFor,
  type HeaderMap,
} from '@/lib/security';

// CSP を「報告だけ」にするかどうか。既に動いているサイトに後から入れるときは
// true から始めて、壊れる箇所を直してから false にする（本文の第10節）。
const CSP_REPORT_ONLY = false;

/** 作ったヘッダを応答に写す。転送でも429でも同じヘッダを付ける */
function applySecurityHeaders(response: NextResponse, headers: HeaderMap): NextResponse {
  for (const [name, value] of Object.entries(headers)) {
    response.headers.set(name, value);
  }

  return response;
}

export function middleware(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;
  const isDevelopment = process.env.NODE_ENV !== 'production';
  const nonce = createNonce();
  const headers = buildSecurityHeaders({ nonce, isDevelopment, reportOnly: CSP_REPORT_ONLY });

  // --- 1. レート制限 -------------------------------------------------------
  const rule = rateLimitRuleFor(pathname, request.method);

  if (rule !== null) {
    const decision = checkRateLimit(clientKey(request.headers, pathname), Date.now(), rule);

    if (decision.kind === 'blocked') {
      const tooMany = new NextResponse('要求が多すぎます。しばらく待ってからやり直してください。', {
        status: 429,
        headers: {
          'Content-Type': 'text/plain; charset=utf-8',
          // いつ再開してよいかを伝える。相手が機械なら従ってくれる
          'Retry-After': String(decision.retryAfterSeconds),
        },
      });

      return applySecurityHeaders(tooMany, headers);
    }
  }

  // --- 2. 認証の入口確認（セッション25の処理をそのまま維持） ---------------
  if (isProtectedPath(pathname)) {
    const sessionId = request.cookies.get(SESSION_COOKIE_NAME)?.value;

    if (sessionId === undefined || sessionId === '') {
      const loginUrl = new URL('/login', request.url);

      // ログインしたら元のページに戻れるように、行き先を渡す
      loginUrl.searchParams.set('next', pathname);

      return applySecurityHeaders(NextResponse.redirect(loginUrl), headers);
    }
  }

  // --- 3. セキュリティヘッダ -----------------------------------------------
  // 要求側にも nonce と CSP を渡す。こうすると Next.js が自分で出す
  // <script> に同じ nonce を付けてくれる（自分で layout.tsx を触らなくてよい）。
  const requestHeaders = new Headers(request.headers);
  const cspName = cspHeaderName(CSP_REPORT_ONLY);

  requestHeaders.set('x-nonce', nonce);
  requestHeaders.set(cspName, headers[cspName] ?? '');

  const response = NextResponse.next({ request: { headers: requestHeaders } });

  return applySecurityHeaders(response, headers);
}

// この middleware を走らせる URL。
// 画像・ビルド済みの静的ファイルは対象外にする（ヘッダを付ける意味がなく、
// 毎回 nonce を作る分だけ遅くなる）。逆に /api は対象に含める。
// JSON を返す口こそレート制限が必要な場所だからである。
export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico|images).*)'],
};
