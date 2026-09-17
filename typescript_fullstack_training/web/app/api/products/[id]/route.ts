import { findProductById } from '@/lib/products';
import { parseProductId } from '@/lib/product-query';
import { toErrorResponse } from '@/lib/api-error';

// GET /api/products/3
// 第2引数の params は、ページと同じく Next.js 15 から Promise になっている。
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
): Promise<Response> {
  const { id } = await params;
  const productId = parseProductId(id);

  if (productId === null) {
    return toErrorResponse({ kind: 'invalid_id', raw: id });
  }

  const product = findProductById(productId);

  if (product === undefined) {
    return toErrorResponse({ kind: 'product_not_found', productId });
  }

  return Response.json(product);
}
