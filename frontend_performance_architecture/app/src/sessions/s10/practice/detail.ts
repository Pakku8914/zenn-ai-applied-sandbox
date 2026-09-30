/** 問題6：商品詳細ページのデータ取得 */
export type DetailApi = {
  getProduct(id: number): Promise<{ id: number; name: string; category: string }>;
  getReviews(id: number): Promise<string[]>;
  getRelated(category: string): Promise<string[]>;
};

export type Detail = {
  product: Awaited<ReturnType<DetailApi['getProduct']>>;
  reviews: string[];
  related: string[];
};

/** Bad：3つを順番に待つ（レビューは商品に依存しないのに、商品を待ってから始まる） */
export async function loadDetailSerial(api: DetailApi, id: number): Promise<Detail> {
  const product = await api.getProduct(id);
  const reviews = await api.getReviews(id);
  const related = await api.getRelated(product.category);
  return { product, reviews, related };
}

/**
 * Good：依存関係のとおりに並べる。
 * レビューは ID だけで取れるので商品と同時に始め、関連商品だけが商品のカテゴリを待つ。
 */
export async function loadDetailParallel(api: DetailApi, id: number): Promise<Detail> {
  const productPromise = api.getProduct(id);
  const reviewsPromise = api.getReviews(id);
  const relatedPromise = productPromise.then((product) => api.getRelated(product.category));
  const [product, reviews, related] = await Promise.all([productPromise, reviewsPromise, relatedPromise]);
  return { product, reviews, related };
}
