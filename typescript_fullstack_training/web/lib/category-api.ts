// 練習問題6の解答。カテゴリごとの商品を返す API の、純粋なロジック部分。
// セッション18の Result で成功・失敗を返し、HTTP の言葉に写すのは describeCategoryFailure だけ。

/** 成功なら value、失敗なら error（セッション13・18で定義したものと同じ形） */
export type Result<T, E> = { kind: 'ok'; value: T } | { kind: 'error'; error: E };

export type CategoryApiFailure =
  | { kind: 'category_not_found'; slug: string }
  | { kind: 'invalid_limit'; raw: string };

/** limit を指定しなかったときの件数 */
export const DEFAULT_LIMIT = 5;

/** limit の上限。大きすぎる要求で無駄な処理をさせないため */
export const MAX_LIMIT = 20;

/** ?limit= の値を検証する。範囲外・整数でない値は失敗として返す */
export function parseLimit(raw: string | null): Result<number, CategoryApiFailure> {
  if (raw === null) {
    return { kind: 'ok', value: DEFAULT_LIMIT };
  }

  const limit = Number(raw);

  if (!Number.isInteger(limit) || limit < 1 || limit > MAX_LIMIT) {
    return { kind: 'error', error: { kind: 'invalid_limit', raw } };
  }

  return { kind: 'ok', value: limit };
}

/** 失敗を HTTP の表現に写す。対象が無ければ404、入力が悪ければ400 */
export function describeCategoryFailure(failure: CategoryApiFailure): {
  status: number;
  message: string;
} {
  switch (failure.kind) {
    case 'category_not_found':
      return { status: 404, message: `カテゴリが見つかりません: ${failure.slug}` };
    case 'invalid_limit':
      return {
        status: 400,
        message: `limit は1以上${MAX_LIMIT}以下の整数で指定してください: ${failure.raw}`,
      };
    default: {
      const unreachable: never = failure;

      throw new Error(`未知の失敗です: ${JSON.stringify(unreachable)}`);
    }
  }
}

/** 失敗を HTTP のレスポンスに変換する */
export function toCategoryErrorResponse(failure: CategoryApiFailure): Response {
  const { status, message } = describeCategoryFailure(failure);

  return Response.json({ error: failure.kind, message }, { status });
}
