// セッション17「非同期処理」の到達点。
// fixtures の JSON を非同期に読み込み、商品にカテゴリ名を紐づけた
// カタログを組み立てる。ネットワークには一切アクセスしない。

import { readFile } from 'node:fs/promises';
import { delay } from './async-tools';
import { fixturePath } from './fixtures-path';

export type Product = {
  id: number;
  name: string;
  price: number;
  stock: number;
  description: string;
  imageUrl: string;
  categoryId: number;
};

export type Category = {
  id: number;
  name: string;
  slug: string;
};

export type CatalogItem = {
  id: number;
  name: string;
  price: number;
  stock: number;
  categoryName: string;
};

/** fixtures の JSON をテキストとして読む */
export async function loadJsonText(fileName: string): Promise<string> {
  return readFile(fixturePath(fileName), 'utf-8');
}

/** JSON.parse の戻り値は any なので、unknown で受け直してから使う */
async function loadJsonValue(fileName: string): Promise<unknown> {
  const text = await loadJsonText(fileName);
  const value: unknown = JSON.parse(text);
  return value;
}

function isProduct(value: unknown): value is Product {
  return (
    typeof value === 'object' &&
    value !== null &&
    'id' in value &&
    typeof value.id === 'number' &&
    'name' in value &&
    typeof value.name === 'string' &&
    'price' in value &&
    typeof value.price === 'number' &&
    'stock' in value &&
    typeof value.stock === 'number' &&
    'description' in value &&
    typeof value.description === 'string' &&
    'imageUrl' in value &&
    typeof value.imageUrl === 'string' &&
    'categoryId' in value &&
    typeof value.categoryId === 'number'
  );
}

function isCategory(value: unknown): value is Category {
  return (
    typeof value === 'object' &&
    value !== null &&
    'id' in value &&
    typeof value.id === 'number' &&
    'name' in value &&
    typeof value.name === 'string' &&
    'slug' in value &&
    typeof value.slug === 'string'
  );
}

function toUnknownArray(value: unknown, fileName: string): readonly unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`${fileName} が配列ではありません`);
  }
  return value;
}

export async function loadProducts(): Promise<Product[]> {
  const items = toUnknownArray(await loadJsonValue('products.json'), 'products.json');
  const products = items.filter(isProduct);

  if (products.length !== items.length) {
    throw new Error('products.json に想定外の形のデータが含まれています');
  }
  return products;
}

export async function loadCategories(): Promise<Category[]> {
  const items = toUnknownArray(await loadJsonValue('categories.json'), 'categories.json');
  const categories = items.filter(isCategory);

  if (categories.length !== items.length) {
    throw new Error('categories.json に想定外の形のデータが含まれています');
  }
  return categories;
}

/** 商品にカテゴリ名を紐づける（ここは同期処理でよい） */
export function buildCatalog(
  products: readonly Product[],
  categories: readonly Category[]
): CatalogItem[] {
  const categoryNameById = new Map<number, string>();
  for (const category of categories) {
    categoryNameById.set(category.id, category.name);
  }

  return products.map((product) => ({
    id: product.id,
    name: product.name,
    price: product.price,
    stock: product.stock,
    categoryName: categoryNameById.get(product.categoryId) ?? '（カテゴリ未設定）',
  }));
}

export function formatCatalogItem(item: CatalogItem): string {
  const stockLabel = item.stock > 0 ? `在庫${item.stock}点` : '在庫切れ';
  return `${item.name}（${item.categoryName}）${item.price}円 / ${stockLabel}`;
}

/** この章の到達点：2つのファイルを並行に読み、カタログを組み立てる */
export async function loadCatalog(): Promise<CatalogItem[]> {
  const [products, categories] = await Promise.all([loadProducts(), loadCategories()]);
  return buildCatalog(products, categories);
}

/** 商品を pageSize 件ずつ非同期に取り出す（ページングの模擬） */
export async function* readProductPages(pageSize: number): AsyncGenerator<Product[]> {
  const products = await loadProducts();

  for (let start = 0; start < products.length; start += pageSize) {
    await delay(5); // 1ページ取得するのにかかる時間のつもり
    yield products.slice(start, start + pageSize);
  }
}

/** 在庫を確保する（在庫0なら失敗する）。非同期の失敗を作るためのスタブ */
export async function reserveStockStub(product: Product): Promise<string> {
  await delay(10);

  if (product.stock <= 0) {
    throw new Error('在庫がありません');
  }
  return `確保しました（${product.stock}点）`;
}
