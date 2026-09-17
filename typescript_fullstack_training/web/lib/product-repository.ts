// 商品・カテゴリの問い合わせをまとめる場所（セッション23）。
//
// 画面やルートハンドラから直接 prisma を呼ばず、必ずこのモジュールを通す。
// 「どんな SQL が飛ぶか」を1か所に閉じ込めておくと、あとで N+1 を直したり
// 索引を張ったりするときに探す場所が1つで済む。

import type { Prisma } from '@prisma/client';
import { cache } from 'react';
import { unstable_cache } from 'next/cache';
import { prisma } from '@/lib/db';
import { CATEGORIES_TAG, PRODUCTS_TAG } from '@/lib/cache-tags';
import { PAGE_SIZE, calcPagination, type Pagination, type SortKey } from '@/lib/product-query';

/** カテゴリ1行。セッション21の Category 型と同じ形 */
export type CategoryRow = {
  id: number;
  name: string;
  slug: string;
};

/** 一覧に必要な最小限。select で取る列と1対1で対応する */
export type ProductSummary = {
  id: number;
  name: string;
  price: number;
  stock: number;
  imageUrl: string;
  categoryId: number;
};

/** 詳細に必要な形。include: { category: true } の結果がこの形になる */
export type ProductWithCategory = {
  id: number;
  name: string;
  price: number;
  stock: number;
  description: string;
  imageUrl: string;
  categoryId: number;
  category: CategoryRow;
};

/** 一覧の問い合わせ条件 */
export type ProductPageOptions = {
  categoryId: number | null;
  keyword: string;
  sort: SortKey;
  page: number;
  pageSize?: number;
};

/** 一覧の問い合わせ結果 */
export type ProductPage<T> = {
  items: T[];
  totalCount: number;
  pagination: Pagination;
};

/** カテゴリを id 順に全件。3件しかないので条件は付けない */
export async function findAllCategories(): Promise<CategoryRow[]> {
  return prisma.category.findMany({
    select: { id: true, name: true, slug: true },
    orderBy: { id: 'asc' },
  });
}

/** slug でカテゴリを1件。slug に @unique を付けたので findUnique が使える */
export async function findCategoryBySlug(slug: string): Promise<CategoryRow | null> {
  return prisma.category.findUnique({
    where: { slug },
    select: { id: true, name: true, slug: true },
  });
}

/** 絞り込み条件を組み立てる。条件が無いときはキーを足さない（= 全件） */
function buildWhere(options: ProductPageOptions): Prisma.ProductWhereInput {
  const where: Prisma.ProductWhereInput = {};

  if (options.categoryId !== null) {
    where.categoryId = options.categoryId;
  }
  if (options.keyword !== '') {
    // mode: 'insensitive' は大文字小文字を区別しない部分一致
    where.name = { contains: options.keyword, mode: 'insensitive' };
  }

  return where;
}

/**
 * 並べ替えを組み立てる。同じ価格の商品どうしの順番がぶれないよう、
 * 第2キーに id を必ず入れる（ページ送りで同じ商品が2回出ないようにするため）。
 */
function buildOrderBy(sort: SortKey): Prisma.ProductOrderByWithRelationInput[] {
  switch (sort) {
    case 'price-asc':
      return [{ price: 'asc' }, { id: 'asc' }];
    case 'price-desc':
      return [{ price: 'desc' }, { id: 'asc' }];
    case 'name-asc':
      return [{ name: 'asc' }, { id: 'asc' }];
    default: {
      const unreachable: never = sort;

      throw new Error(`未知の並べ替えです: ${String(unreachable)}`);
    }
  }
}

/** 件数を数えてから、表示するページを確定する（ページ番号の丸めはセッション21の関数を使う） */
async function resolvePage(options: ProductPageOptions): Promise<{
  where: Prisma.ProductWhereInput;
  orderBy: Prisma.ProductOrderByWithRelationInput[];
  totalCount: number;
  pagination: Pagination;
}> {
  const where = buildWhere(options);
  const totalCount = await prisma.product.count({ where });
  const pagination = calcPagination(totalCount, options.page, options.pageSize ?? PAGE_SIZE);

  return { where, orderBy: buildOrderBy(options.sort), totalCount, pagination };
}

/** 一覧用。select で6列だけ取る（description は一覧では使わない） */
export async function findProductSummaryPage(
  options: ProductPageOptions
): Promise<ProductPage<ProductSummary>> {
  const { where, orderBy, totalCount, pagination } = await resolvePage(options);
  const items = await prisma.product.findMany({
    where,
    orderBy,
    skip: pagination.skip,
    take: pagination.take,
    select: { id: true, name: true, price: true, stock: true, imageUrl: true, categoryId: true },
  });

  return { items, totalCount, pagination };
}

/** カテゴリ名まで必要なとき用。include: { category: true } で商品と一緒に取る */
export async function findProductDetailPage(
  options: ProductPageOptions
): Promise<ProductPage<ProductWithCategory>> {
  const { where, orderBy, totalCount, pagination } = await resolvePage(options);
  const items = await prisma.product.findMany({
    where,
    orderBy,
    skip: pagination.skip,
    take: pagination.take,
    include: { category: true },
  });

  return { items, totalCount, pagination };
}

/** 詳細ページ用。主キー1件なので findUnique（見つからなければ null） */
export async function findProductDetail(id: number): Promise<ProductWithCategory | null> {
  return prisma.product.findUnique({
    where: { id },
    include: { category: true },
  });
}

// ---------------------------------------------------------------------------
// セッション27：キャッシュを効かせた入口
//
// 上の関数は「毎回データベースを見る版」。管理画面のように常に最新を見たい
// ところはこちらを使い続ける。公開側の一覧はキャッシュ付きの下の関数を使う。
// 上の関数のシグネチャは変えていないので、既存の呼び出しは何も直さなくてよい。
// ---------------------------------------------------------------------------

/** 一覧のキャッシュの寿命（秒）。「在庫の表示が最大1分古くても許せる」という判断 */
export const PRODUCT_LIST_REVALIDATE_SECONDS = 60;

/** カテゴリのキャッシュの寿命（秒）。ほとんど変わらないデータなので1時間 */
export const CATEGORY_REVALIDATE_SECONDS = 60 * 60;

/**
 * データキャッシュに乗せたカテゴリ一覧。
 * unstable_cache はリクエストをまたいで結果を保存する（＝データキャッシュ）。
 */
const loadAllCategories = unstable_cache(
  async (): Promise<CategoryRow[]> => findAllCategories(),
  ['product-repository', 'all-categories'],
  { revalidate: CATEGORY_REVALIDATE_SECONDS, tags: [CATEGORIES_TAG] }
);

/**
 * カテゴリ一覧。React の cache() でさらに包むと、同じリクエストの中で
 * 何度呼んでも1回しか実行されない（＝リクエストメモ化）。
 * 一覧ページでは「タブ」と「見出し」の2か所から呼ぶので、この1行が効く。
 */
export const findAllCategoriesCached = cache(
  async (): Promise<CategoryRow[]> => loadAllCategories()
);

/**
 * データキャッシュに乗せた一覧。
 *
 * unstable_cache のキーは「keyParts ＋ 引数を JSON にしたもの」で決まる。
 * オブジェクトを渡すとプロパティを書いた順番でキーが変わってしまうため、
 * 決まった順番の引数に開いて渡す。省略可能な値（pageSize）も呼び出し側で
 * 確定させてから渡す。
 */
const loadProductDetailPage = unstable_cache(
  async (
    categoryId: number | null,
    keyword: string,
    sort: SortKey,
    page: number,
    pageSize: number
  ): Promise<ProductPage<ProductWithCategory>> =>
    findProductDetailPage({ categoryId, keyword, sort, page, pageSize }),
  ['product-repository', 'detail-page'],
  { revalidate: PRODUCT_LIST_REVALIDATE_SECONDS, tags: [PRODUCTS_TAG] }
);

export async function findProductDetailPageCached(
  options: ProductPageOptions
): Promise<ProductPage<ProductWithCategory>> {
  return loadProductDetailPage(
    options.categoryId,
    options.keyword,
    options.sort,
    options.page,
    options.pageSize ?? PAGE_SIZE
  );
}

// ---------------------------------------------------------------------------
// 最終プロジェクト：商品マスタの書き込み（管理画面から使う）
//
// 読み取りと同じファイルに置くのは、「どのカテゴリの一覧が古くなるか」を
// 知っているのがこのモジュールだけだからである。書き込みの結果として
// 「捨てるべきキャッシュのタグを組み立てるための材料」を返す。
// ---------------------------------------------------------------------------

/** 書き込みの結果。成功時はキャッシュ無効化に必要な材料を添える */
export type ProductWriteResult =
  | {
      kind: 'ok';
      productId: number;
      categorySlug: string;
      /** カテゴリを移動した場合は移動前の slug。移動していなければ null */
      previousCategorySlug: string | null;
    }
  | { kind: 'error'; message: string };

/** 編集フォームに流し込む形 */
export type ProductDraft = {
  id: number;
  name: string;
  price: number;
  stock: number;
  description: string;
  imageUrl: string;
  categoryId: number;
};

/** 書き込む内容。lib/validation.ts の productFormSchema を通した値を渡す */
export type ProductWriteInput = {
  name: string;
  price: number;
  stock: number;
  description: string;
  imageUrl: string;
  categoryId: number;
};

/**
 * Prisma が投げるエラーの code を安全に取り出す。
 * 例外は unknown で受け、プロパティの有無を確かめてから読む（セッション16）。
 */
function prismaErrorCode(error: unknown): string | undefined {
  if (typeof error === 'object' && error !== null && 'code' in error) {
    const code: unknown = (error as { code: unknown }).code;

    return typeof code === 'string' ? code : undefined;
  }

  return undefined;
}

/** 編集画面用に1件引く。見つからなければ null */
export async function findProductDraft(id: number): Promise<ProductDraft | null> {
  return prisma.product.findUnique({
    where: { id },
    select: {
      id: true,
      name: true,
      price: true,
      stock: true,
      description: true,
      imageUrl: true,
      categoryId: true,
    },
  });
}

/** カテゴリの slug を引く。存在しないカテゴリを指定されたら null */
async function findCategorySlug(categoryId: number): Promise<string | null> {
  const category = await prisma.category.findUnique({
    where: { id: categoryId },
    select: { slug: true },
  });

  return category === null ? null : category.slug;
}

export async function createProduct(input: ProductWriteInput): Promise<ProductWriteResult> {
  const categorySlug = await findCategorySlug(input.categoryId);

  // 外部キー制約に任せると Prisma の例外になる。先に確かめて日本語で返す
  if (categorySlug === null) {
    return { kind: 'error', message: '存在しないカテゴリです' };
  }

  const created = await prisma.product.create({ data: input, select: { id: true } });

  return { kind: 'ok', productId: created.id, categorySlug, previousCategorySlug: null };
}

export async function updateProduct(
  id: number,
  input: ProductWriteInput
): Promise<ProductWriteResult> {
  const before = await prisma.product.findUnique({
    where: { id },
    select: { categoryId: true, category: { select: { slug: true } } },
  });

  if (before === null) {
    return { kind: 'error', message: '商品が見つかりません' };
  }

  const categorySlug = await findCategorySlug(input.categoryId);

  if (categorySlug === null) {
    return { kind: 'error', message: '存在しないカテゴリです' };
  }

  await prisma.product.update({ where: { id }, data: input });

  return {
    kind: 'ok',
    productId: id,
    categorySlug,
    // カテゴリを移動したときは、移動元の一覧のキャッシュも捨てないと商品が残り続ける
    previousCategorySlug: before.categoryId === input.categoryId ? null : before.category.slug,
  };
}

/**
 * 商品を削除する。
 *
 * order_items は削除の連鎖（onDelete: Cascade）を付けていないので、
 * 注文実績のある商品は削除できない。これは制約の不備ではなく、
 * 「過去の注文の内容を消してはいけない」という要件そのものである。
 * だから外部キー違反（P2003）を捕まえて、日本語の案内に変える。
 */
export async function deleteProduct(id: number): Promise<ProductWriteResult> {
  const before = await prisma.product.findUnique({
    where: { id },
    select: { category: { select: { slug: true } } },
  });

  if (before === null) {
    return { kind: 'error', message: '商品が見つかりません' };
  }

  try {
    // カートに入っているだけの行は消してよい（注文ではないため）
    await prisma.$transaction([
      prisma.cartItem.deleteMany({ where: { productId: id } }),
      prisma.product.delete({ where: { id } }),
    ]);
  } catch (error: unknown) {
    if (prismaErrorCode(error) === 'P2003') {
      return {
        kind: 'error',
        message: '注文実績があるため削除できません。在庫を0にして販売を止めてください',
      };
    }

    throw error;
  }

  return {
    kind: 'ok',
    productId: id,
    categorySlug: before.category.slug,
    previousCategorySlug: null,
  };
}
