'use server';

// カートを操作する Server Action（セッション24）。
//
// ファイルの先頭に 'use server' を書くと、このファイルの export はすべて
// 「ブラウザから呼べるサーバー側の関数」になる。したがって export できるのは
// 非同期関数だけであり、引数と戻り値は JSON にできる値でなければならない。
//
// 検証は必ずここで行う。ブラウザ側の検証は親切心（UX）であって、守りではない。

import { revalidatePath } from 'next/cache';
import {
  CART_FIELD_LABELS,
  cartItemSchema,
  customerSchema,
  errorState,
  invalidInputState,
  okState,
  productRefSchema,
  toCustomerFieldErrors,
  type CartActionState,
  type CustomerFormState,
} from '@/lib/validation';
import { addToCart, changeCartQuantity, removeFromCart } from '@/lib/cart-repository';
import { getSessionUser } from '@/lib/session';

/**
 * いま操作しているのは誰か。
 *
 * セッション24 の時点では固定の DEMO_USER_ID を使っていたが、認証を実装した
 * いまは必ずセッションから取る。カートは「誰のものか」で行が分かれているので、
 * ここを固定値のままにすると全員が同じカートを共有してしまう。
 */
async function currentUserId(): Promise<number | undefined> {
  const user = await getSessionUser();

  return user?.id;
}

/** 未ログインのときに返す状態。どの操作でも同じ文言にする */
function loginRequiredState(): CartActionState {
  return errorState(['カートを使うにはログインが必要です']);
}

/** カートに商品を足す */
export async function addToCartAction(
  _prevState: CartActionState,
  formData: FormData
): Promise<CartActionState> {
  const userId = await currentUserId();

  if (userId === undefined) {
    return loginRequiredState();
  }

  // formData.get は「文字列 or ファイル or null」を返す。信用せずスキーマに通す
  const parsed = cartItemSchema.safeParse({
    productId: formData.get('productId'),
    quantity: formData.get('quantity'),
  });

  if (!parsed.success) {
    return invalidInputState(parsed.error, CART_FIELD_LABELS);
  }

  const change = await addToCart(userId, parsed.data.productId, parsed.data.quantity);

  if (change.kind === 'error') {
    return errorState([change.message]);
  }

  // これを呼ばないと、データベースは変わったのに画面が古いまま表示される
  revalidatePath('/cart');

  return okState(change.message);
}

/** 明細の数量を変更する（練習問題1） */
export async function changeQuantityAction(
  _prevState: CartActionState,
  formData: FormData
): Promise<CartActionState> {
  const userId = await currentUserId();

  if (userId === undefined) {
    return loginRequiredState();
  }

  const parsed = cartItemSchema.safeParse({
    productId: formData.get('productId'),
    quantity: formData.get('quantity'),
  });

  if (!parsed.success) {
    return invalidInputState(parsed.error, CART_FIELD_LABELS);
  }

  const change = await changeCartQuantity(userId, parsed.data.productId, parsed.data.quantity);

  if (change.kind === 'error') {
    return errorState([change.message]);
  }

  revalidatePath('/cart');

  return okState(change.message);
}

/** 明細を削除する */
export async function removeItemAction(
  _prevState: CartActionState,
  formData: FormData
): Promise<CartActionState> {
  const userId = await currentUserId();

  if (userId === undefined) {
    return loginRequiredState();
  }

  const parsed = productRefSchema.safeParse({ productId: formData.get('productId') });

  if (!parsed.success) {
    return invalidInputState(parsed.error, CART_FIELD_LABELS);
  }

  const change = await removeFromCart(userId, parsed.data.productId);

  if (change.kind === 'error') {
    return errorState([change.message]);
  }

  revalidatePath('/cart');

  return okState(change.message);
}

/**
 * お届け先の入力を確かめるだけの Server Action（練習問題4）。
 * データベースには書かない。注文の確定は最終プロジェクトで作る。
 */
export async function previewCustomerAction(
  _prevState: CustomerFormState,
  formData: FormData
): Promise<CustomerFormState> {
  // 入力欄が無いときの null と、空欄のときの '' を区別する。
  // 任意項目（optional）は「キーが無い（undefined）」ときだけ省略とみなされる
  const parsed = customerSchema.safeParse({
    name: formData.get('name'),
    email: formData.get('email'),
    note: formData.get('note') ?? undefined,
  });

  if (!parsed.success) {
    return { kind: 'error', fieldErrors: toCustomerFieldErrors(parsed.error) };
  }

  return {
    kind: 'ok',
    message: `${parsed.data.name} さん（${parsed.data.email}）にお届けします`,
  };
}
