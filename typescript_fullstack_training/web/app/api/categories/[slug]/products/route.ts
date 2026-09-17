// 練習問題6の解答。GET /api/categories/fabric/products?limit=1
import { PRODUCTS, findCategoryBySlug } from '@/lib/products';
import { filterAndSortProducts } from '@/lib/product-query';
import { parseLimit, toCategoryErrorResponse } from '@/lib/category-api';

export async function GET(
  request: Request,
  { params }: { params: Promise<{ slug: string }> }
): Promise<Response> {
  const { slug } = await params;
  const category = findCategoryBySlug(slug);

  if (category === undefined) {
    return toCategoryErrorResponse({ kind: 'category_not_found', slug });
  }

  const limit = parseLimit(new URL(request.url).searchParams.get('limit'));

  if (limit.kind === 'error') {
    return toCategoryErrorResponse(limit.error);
  }

  // totalCount は limit で切る前の件数を返す（クライアントが「まだ続きがある」と判断できるように）
  const items = filterAndSortProducts(PRODUCTS, category.id, 'price-asc');

  return Response.json({
    category,
    items: items.slice(0, limit.value),
    totalCount: items.length,
  });
}
