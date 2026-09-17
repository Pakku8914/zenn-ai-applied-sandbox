// セッション 13: 送信者制約付きトークンを受け付ける注文 API の住所。
// proof の htu には、クエリを除いたこの形の URL を入れます。
// API 本体（Hono アプリと検証ミドルウェア）は練習問題 4 で組み立てます。
export const API_BASE = "http://api-service:4100";
export const apiUrl = (path: string): string => `${API_BASE}${path}`;
