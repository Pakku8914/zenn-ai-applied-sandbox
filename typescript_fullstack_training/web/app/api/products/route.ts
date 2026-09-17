import { toErrorResponse } from '@/lib/api-error';
import { describeFieldSet, parseFieldSet } from '@/lib/product-fields';
import {
  findCategoryBySlug,
  findProductDetailPage,
  findProductSummaryPage,
} from '@/lib/product-repository';
import { parseKeyword, parseProductQuery, type RawSearchParams } from '@/lib/product-query';

// データベースの現在値を返す API なので、応答をビルド時に固定しない。
export const dynamic = 'force-dynamic';

// GET /api/products?category=kitchen&sort=price-desc&page=2&q=マグ&fields=detail
export async function GET(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const rawCategory = url.searchParams.get('category');
  // カテゴリの存在確認もデータベースに問い合わせる（slug は @unique なので1件で確定する）
  const category = rawCategory === null ? null : await findCategoryBySlug(rawCategory);

  // 画面は不正なカテゴリを黙って無視するが、API は「間違って呼ばれた」ことを呼び出し側に伝える
  if (rawCategory !== null && category === null) {
    return toErrorResponse({ kind: 'unknown_category', slug: rawCategory });
  }

  const raw: RawSearchParams = Object.fromEntries(url.searchParams.entries());
  const query = parseProductQuery(raw);
  const keyword = parseKeyword(raw['q']);
  const fieldSet = parseFieldSet(url.searchParams.get('fields'));
  const options = {
    categoryId: category?.id ?? null,
    keyword,
    sort: query.sort,
    page: query.page,
  };

  // 一覧用は select で6列だけ、詳細用は include でカテゴリまで取る
  const result =
    fieldSet === 'detail'
      ? await findProductDetailPage(options)
      : await findProductSummaryPage(options);

  return Response.json({
    fields: describeFieldSet(fieldSet).fields,
    items: result.items,
    page: result.pagination.page,
    totalPages: result.pagination.totalPages,
    totalCount: result.totalCount,
  });
}
