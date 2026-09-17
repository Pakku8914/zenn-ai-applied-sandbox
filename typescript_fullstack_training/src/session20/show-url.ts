// URL を部品に分解して表示する。
// 実行: docker compose exec ts npx tsx src/session20/show-url.ts

import { formatUrlParts } from './url-parts';

const target = process.argv[2] ?? 'https://shop.example.com:8443/products/3?color=blue&size=m#reviews';

console.log(`--- ${target} ---`);
console.log(formatUrlParts(target));
