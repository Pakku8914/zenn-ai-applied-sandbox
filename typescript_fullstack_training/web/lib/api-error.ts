// JSON API が返す「失敗」を型で表し、HTTP の言葉に写す。
// 判別タグは本書共通の kind（セッション12で決めた規約）。
// ステータスコードの割り当てはセッション20の対応表に従う。

/** API が返しうる失敗の種類 */
export type ApiFailure =
  | { kind: 'invalid_id'; raw: string }
  | { kind: 'unknown_category'; slug: string }
  | { kind: 'product_not_found'; productId: number };

/** クライアントに返す JSON の形。内部の詳細（スタックトレースなど）は載せない */
export type ApiErrorBody = {
  error: ApiFailure['kind'];
  message: string;
};

/** 失敗を HTTP の表現に写す。入力が悪ければ400、対象が無ければ404 */
export function describeFailure(failure: ApiFailure): { status: number; message: string } {
  switch (failure.kind) {
    case 'invalid_id':
      return { status: 400, message: `商品IDの形式が正しくありません: ${failure.raw}` };
    case 'unknown_category':
      return { status: 400, message: `存在しないカテゴリです: ${failure.slug}` };
    case 'product_not_found':
      return { status: 404, message: `商品が見つかりません: ${failure.productId}` };
    default: {
      const unreachable: never = failure;

      throw new Error(`未知の失敗です: ${JSON.stringify(unreachable)}`);
    }
  }
}

/** 失敗を HTTP のレスポンスに変換する。ステータスコードを決める場所はここだけ */
export function toErrorResponse(failure: ApiFailure): Response {
  const { status, message } = describeFailure(failure);
  const body: ApiErrorBody = { error: failure.kind, message };

  return Response.json(body, { status });
}
