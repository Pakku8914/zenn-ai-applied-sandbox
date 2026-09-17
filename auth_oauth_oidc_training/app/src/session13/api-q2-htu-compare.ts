// セッション 13 問題 2: proof の htu とリクエスト URL を、部品ごとに突き合わせます。
// 「どこが違って不一致になったか」まで返すので、拒否の理由をログに残せます。

/** 一致しなかったときは、最初に食い違った部品の名前を返します */
export type HtuDiff = "match" | "malformed" | "scheme" | "host" | "port" | "path";

function parse(url: string): URL | undefined {
  try {
    // URL は「ホスト名の小文字化」「既定ポートの省略」まで面倒を見てくれます
    return new URL(url);
  } catch {
    return undefined;
  }
}

export function compareHtu(claimed: string, requestUrl: string): HtuDiff {
  const a = parse(claimed);
  const b = parse(requestUrl);
  // スキームの無い相対 URL は URL にできないので、不一致ではなく「壊れている」と扱います
  if (a === undefined || b === undefined) return "malformed";
  if (a.protocol !== b.protocol) return "scheme";
  if (a.hostname !== b.hostname) return "host";
  // 既定ポート（http の 80・https の 443）は URL の段階で空文字に正規化されます
  if (a.port !== b.port) return "port";
  // パスは大文字小文字も末尾のスラッシュも区別します（RFC 9449 は完全一致を求めます）
  if (a.pathname !== b.pathname) return "path";
  // クエリ（search）とフラグメント（hash）は最初から比べません
  return "match";
}

export function htuMatches(claimed: string, requestUrl: string): boolean {
  return compareHtu(claimed, requestUrl) === "match";
}
