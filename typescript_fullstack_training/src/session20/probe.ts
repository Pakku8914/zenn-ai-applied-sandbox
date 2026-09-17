// curl の代わりに使える簡易 HTTP クライアント。
// curl -i と同じように、ステータス行・ヘッダ・本文をまとめて表示する。
//
// 実行例:
//   npx tsx src/session20/probe.ts http://localhost:3000/api/products
//   npx tsx src/session20/probe.ts http://localhost:3000/api/cart POST '{"productId":1,"quantityInput":"2"}'

import { formatResponse } from './response-format';

const url = process.argv[2] ?? 'http://localhost:3000/';
const method = process.argv[3] ?? 'GET';
const body = process.argv[4];

// fetch は既定でリダイレクト（3xx）を自動で追いかける。
// curl は逆に、-L を付けないと追いかけない。
const res = await fetch(url, {
  method,
  headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
  body,
});

const headerLines: string[] = [];
res.headers.forEach((value, name) => {
  headerLines.push(`${name}: ${value}`);
});

console.log(formatResponse(res.status, res.statusText, headerLines, await res.text()));
