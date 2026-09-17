'use server';

// 商品マスタを操作する Server Action（最終プロジェクト）。
//
// 'use server' を書いたファイルの export は、すべて「ブラウザから呼べる関数」に
// なる。つまりこの3つは URL を持たない入口である。middleware は URL でしか
// 判断できないので、管理者かどうかの確認は必ずこの中で行う。
//
// 「/admin の画面を出さないようにしたから安全」ではない。画面を隠しても
// Server Action は呼べるので、入口ごとに確かめる（多層防御）。

import { revalidateTag } from 'next/cache';
import { canAccessAdmin } from '@/lib/authz';
import { getSessionUser } from '@/lib/session';
import { tagsForProductUpdate } from '@/lib/cache-tags';
import { getLogger } from '@/lib/logger';
import {
  createProduct,
  deleteProduct,
  updateProduct,
  type ProductWriteInput,
  type ProductWriteResult,
} from '@/lib/product-repository';
import {
  PRODUCT_FIELD_LABELS,
  errorState,
  invalidInputState,
  okState,
  productFormSchema,
  productRefSchema,
  productUpdateSchema,
  resolveProductImageUrl,
  type CartActionState,
  type ProductFormInput,
} from '@/lib/validation';

/** 管理者でなければ、その理由を状態として返す。通ってよいときだけ null */
async function denyIfNotAdmin(): Promise<CartActionState | null> {
  const user = await getSessionUser();

  if (!canAccessAdmin(user)) {
    getLogger().warn('admin.denied', { userId: user?.id ?? null });

    return errorState(['この操作を行う権限がありません']);
  }

  return null;
}

/** フォームの値を取り出す。null（入力欄が無い）と ''（空欄）を区別する */
function readProductForm(formData: FormData): Record<string, unknown> {
  return {
    name: formData.get('name'),
    price: formData.get('price'),
    stock: formData.get('stock'),
    description: formData.get('description'),
    imageUrl: formData.get('imageUrl') ?? undefined,
    categoryId: formData.get('categoryId'),
  };
}

/**
 * 検証済みの値を、書き込む形に整える。
 * imageUrl はスキーマで省略可にしてあるので、ここで既定値に寄せる。
 */
function toWriteInput(parsed: ProductFormInput): ProductWriteInput {
  return {
    name: parsed.name,
    price: parsed.price,
    stock: parsed.stock,
    description: parsed.description,
    imageUrl: resolveProductImageUrl(parsed.imageUrl),
    categoryId: parsed.categoryId,
  };
}

/**
 * 書き込みの結果を画面の状態に変える。
 * 成功したら、古くなったキャッシュのタグをまとめて捨てる（セッション27）。
 * タグの組み立ては lib/cache-tags.ts の1か所に任せ、ここでは文字列を作らない。
 */
function finish(result: ProductWriteResult, message: string): CartActionState {
  if (result.kind === 'error') {
    return errorState([result.message]);
  }

  for (const tag of tagsForProductUpdate({
    productId: result.productId,
    categorySlug: result.categorySlug,
    previousCategorySlug: result.previousCategorySlug,
  })) {
    revalidateTag(tag);
  }

  return okState(message);
}

/** 商品を登録する */
export async function createProductAction(
  _prevState: CartActionState,
  formData: FormData
): Promise<CartActionState> {
  const denied = await denyIfNotAdmin();

  if (denied !== null) {
    return denied;
  }

  const parsed = productFormSchema.safeParse(readProductForm(formData));

  if (!parsed.success) {
    return invalidInputState(parsed.error, PRODUCT_FIELD_LABELS);
  }

  const result = await createProduct(toWriteInput(parsed.data));

  return finish(result, `${parsed.data.name}を登録しました`);
}

/** 商品を更新する */
export async function updateProductAction(
  _prevState: CartActionState,
  formData: FormData
): Promise<CartActionState> {
  const denied = await denyIfNotAdmin();

  if (denied !== null) {
    return denied;
  }

  const parsed = productUpdateSchema.safeParse({
    ...readProductForm(formData),
    id: formData.get('id'),
  });

  if (!parsed.success) {
    return invalidInputState(parsed.error, PRODUCT_FIELD_LABELS);
  }

  const result = await updateProduct(parsed.data.id, toWriteInput(parsed.data));

  return finish(result, `${parsed.data.name}を更新しました`);
}

/** 商品を削除する。注文実績があるものは削除できない（過去の注文を壊さないため） */
export async function deleteProductAction(
  _prevState: CartActionState,
  formData: FormData
): Promise<CartActionState> {
  const denied = await denyIfNotAdmin();

  if (denied !== null) {
    return denied;
  }

  const parsed = productRefSchema.safeParse({ productId: formData.get('productId') });

  if (!parsed.success) {
    return invalidInputState(parsed.error, PRODUCT_FIELD_LABELS);
  }

  const result = await deleteProduct(parsed.data.productId);

  return finish(result, '商品を削除しました');
}
