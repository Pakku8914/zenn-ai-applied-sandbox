// fetch でサーバーに話しかけるクライアント。
//
// 先に別のターミナルでサーバーを起動しておく:
//   docker compose exec ts npx tsx src/session20/start-shop.ts
// そのうえで、こちらを実行する:
//   docker compose exec ts npx tsx src/session20/client.ts

const baseUrl = process.env['BASE_URL'] ?? 'http://localhost:3000';

/** GET して JSON を受け取る。res.json() は any を返すので unknown で受け直す */
async function getJson(path: string): Promise<unknown> {
  const res = await fetch(`${baseUrl}${path}`);
  console.log(`GET ${path} → ${res.status}`);

  const value: unknown = await res.json();
  return value;
}

/** JSON を送って JSON を受け取る。Content-Type で「これは JSON です」と伝える */
async function postJson(path: string, payload: unknown): Promise<unknown> {
  const res = await fetch(`${baseUrl}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  console.log(`POST ${path} → ${res.status}`);

  const value: unknown = await res.json();
  return value;
}

console.log(JSON.stringify(await getJson('/api/products?q=石けん')));
console.log(JSON.stringify(await getJson('/api/products/3')));
console.log(JSON.stringify(await getJson('/api/products/999')));
console.log(JSON.stringify(await postJson('/api/cart', { productId: 1, quantityInput: '2' })));
console.log(JSON.stringify(await postJson('/api/cart', { productId: 4, quantityInput: '1' })));
