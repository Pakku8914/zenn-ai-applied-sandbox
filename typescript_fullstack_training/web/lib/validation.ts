// フォームや URL から届いた「外から来た値」を検証するスキーマを1か所に集める（セッション24）。
//
// ここには Prisma も React も import しない。純粋な検証だけを置くので、
// 同じ実装を src/session24/verify.ts で検証できる（src からは web を import できないため写している）。
//
// Zod 4 の書き方に注意する:
//   - メールアドレスは z.string().email() ではなく z.email()
//   - 失敗の一覧は error.issues
//   - 項目ごとにまとめるのは z.flattenError(error) / z.treeifyError(error)
//   - 自分のメッセージは { error: '...' }（Zod 3 の { message: '...' } は非推奨）

import { z } from 'zod';
import { MAX_CART_QUANTITY } from '@/lib/cart';
import { DEFAULT_SORT, type SortKey } from '@/lib/product-query';

// ---------------------------------------------------------------------------
// 1. 部品となるスキーマ
// ---------------------------------------------------------------------------

/**
 * 商品 ID。フォームからは文字列で届くので、数値に変換してから検査する。
 * 利用者が直接入力する値ではないので、失敗のメッセージは1種類にまとめてある。
 */
export const productIdSchema = z.coerce
  .number({ error: '商品を選び直してください' })
  .int({ error: '商品を選び直してください' })
  .positive({ error: '商品を選び直してください' });

/** 数量。1以上 MAX_CART_QUANTITY 以下の整数だけを通す（上限はセッション15で決めた値） */
export const quantitySchema = z.coerce
  .number({ error: '数量は数字で入力してください' })
  .int({ error: '数量は整数で入力してください' })
  .min(1, { error: '数量は1点以上にしてください' })
  .max(MAX_CART_QUANTITY, { error: `数量は${MAX_CART_QUANTITY}点以下にしてください` });

// ---------------------------------------------------------------------------
// 2. フォーム1つにつき1つのスキーマ
// ---------------------------------------------------------------------------

/** 「カートに入れる」「数量を変更する」フォームが送ってくる形 */
export const cartItemSchema = z.object({
  productId: productIdSchema,
  quantity: quantitySchema,
});

/** 「削除する」フォームが送ってくる形。数量は要らない */
export const productRefSchema = z.object({
  productId: productIdSchema,
});

/** お届け先。備考は任意（入力欄が空でもよい） */
export const customerSchema = z.object({
  name: z
    .string({ error: 'お名前を入力してください' })
    .trim()
    .min(1, { error: 'お名前を入力してください' })
    .max(50, { error: 'お名前は50文字以内で入力してください' }),
  email: z.email({ error: 'メールアドレスの形式が正しくありません' }),
  note: z.string().max(200, { error: '備考は200文字以内で入力してください' }).optional(),
});

// スキーマから型を導出する。型を手で書かないので、両者がずれることが起こりえない
export type CartItemInput = z.infer<typeof cartItemSchema>;
export type ProductRefInput = z.infer<typeof productRefSchema>;
export type CustomerInput = z.infer<typeof customerSchema>;

// ---------------------------------------------------------------------------
// 3. 失敗を画面に出せる形に変える
// ---------------------------------------------------------------------------

/** 項目名（スキーマのキー）を、画面に出す日本語に対応させる表 */
export type FieldLabels = Record<string, string>;

export const CART_FIELD_LABELS: FieldLabels = {
  productId: '商品',
  quantity: '数量',
};

/**
 * 検証の失敗を、そのまま並べられるメッセージの配列にする。
 * issue.path は ['quantity'] のような「どの項目か」の道順。ラベル表を引いて日本語を前に付ける。
 */
export function toErrorMessages(error: z.ZodError, labels: FieldLabels): string[] {
  return error.issues.map((issue) => {
    const key = issue.path.map((segment) => String(segment)).join('.');
    const label = labels[key];

    return label === undefined ? issue.message : `${label}：${issue.message}`;
  });
}

/** 項目ごとに分けて表示したいとき用の形（練習問題3） */
export type CustomerFieldErrors = {
  name: string[];
  email: string[];
  note: string[];
  /** どの項目にも属さないエラー（スキーマ全体に付けた検査の結果） */
  form: string[];
};

/**
 * z.flattenError は失敗を「フォーム全体（formErrors）」と「項目ごと（fieldErrors）」に分ける。
 * 項目の下にメッセージを出すレイアウトでは、この形が扱いやすい。
 */
export function toCustomerFieldErrors(error: z.ZodError<CustomerInput>): CustomerFieldErrors {
  const flat = z.flattenError(error);

  return {
    name: flat.fieldErrors.name ?? [],
    email: flat.fieldErrors.email ?? [],
    note: flat.fieldErrors.note ?? [],
    form: flat.formErrors,
  };
}

// ---------------------------------------------------------------------------
// 4. Server Action が画面に返す状態（判別タグは本書共通の kind）
// ---------------------------------------------------------------------------

export type CartActionState =
  | { kind: 'idle' }
  | { kind: 'ok'; message: string }
  | { kind: 'error'; messages: string[] };

export function okState(message: string): CartActionState {
  return { kind: 'ok', message };
}

export function errorState(messages: readonly string[]): CartActionState {
  return { kind: 'error', messages: [...messages] };
}

/** 検証の失敗をそのまま状態に変える近道 */
export function invalidInputState(error: z.ZodError, labels: FieldLabels): CartActionState {
  return errorState(toErrorMessages(error, labels));
}

/** お届け先フォームの状態。エラーを項目ごとに持つ（練習問題4） */
export type CustomerFormState =
  | { kind: 'idle' }
  | { kind: 'ok'; message: string }
  | { kind: 'error'; fieldErrors: CustomerFieldErrors };

// ---------------------------------------------------------------------------
// 5. URL のクエリを検証する（練習問題6）
// ---------------------------------------------------------------------------

const SORT_KEYS = ['price-asc', 'price-desc', 'name-asc'] as const;

/**
 * 一覧ページのクエリ。URL の値が壊れていても画面は出したいので、
 * エラーにせず .catch(...) で既定値に落とす（セッション21と同じ方針）。
 *
 * z.enum は TypeScript の enum とは別物で、リテラル型のユニオンを作る道具である。
 */
export const productQuerySchema = z.object({
  category: z.string().trim().min(1).nullable().catch(null),
  sort: z.enum(SORT_KEYS).catch(DEFAULT_SORT),
  page: z.coerce.number().int().min(1).catch(1),
});

export type ProductQueryInput = z.infer<typeof productQuerySchema>;

/**
 * 何も指定されていないときの条件。
 * sort に SortKey の値を入れられることが、スキーマから導出した型と
 * セッション21の SortKey が同じユニオンであることの証明になる。
 */
export const DEFAULT_PRODUCT_QUERY: ProductQueryInput = {
  category: null,
  sort: DEFAULT_SORT satisfies SortKey,
  page: 1,
};

// ---------------------------------------------------------------------------
// 6. 最終プロジェクト：商品マスタの入力（管理画面）
//
// 管理者が入れる値も「外から来た値」である。信頼できる相手だからといって
// 検証を省くと、桁を打ち間違えた価格がそのまま公開されてしまう。
// ---------------------------------------------------------------------------

/** 画像が無いときの既定値（マスタデータの取り決め） */
export const DEFAULT_PRODUCT_IMAGE_URL = '/images/products/no-image.png';

export const MAX_PRODUCT_PRICE = 1_000_000;
export const MAX_PRODUCT_STOCK = 9_999;

/**
 * 画像のURL。サイト内のパスだけを許し、http:// で始まる外部URLは弾く。
 * 外部URLを許すと、商品画像の読み込みで利用者の閲覧が第三者に伝わってしまう。
 */
const productImageUrlSchema = z
  .string()
  .trim()
  .max(200, { error: '画像のURLは200文字以内で入力してください' })
  .refine((value) => value === '' || value.startsWith('/'), {
    error: '画像のURLはサイト内のパス（/images/... の形）で指定してください',
  })
  .optional();

/** 空欄・未入力を既定の画像に寄せる。スキーマを通したあとに1か所で行う */
export function resolveProductImageUrl(imageUrl: string | undefined): string {
  return imageUrl === undefined || imageUrl === '' ? DEFAULT_PRODUCT_IMAGE_URL : imageUrl;
}

/** 商品の登録・更新フォームが送ってくる形 */
export const productFormSchema = z.object({
  name: z
    .string({ error: '商品名を入力してください' })
    .trim()
    .min(1, { error: '商品名を入力してください' })
    .max(200, { error: '商品名は200文字以内で入力してください' }),
  // 金額は整数の円。小数を受け取らないことをスキーマで宣言する（セッション2の方針）
  price: z.coerce
    .number({ error: '価格は数字で入力してください' })
    .int({ error: '価格は1円単位の整数で入力してください' })
    .min(1, { error: '価格は1円以上にしてください' })
    .max(MAX_PRODUCT_PRICE, { error: `価格は${MAX_PRODUCT_PRICE}円以下にしてください` }),
  stock: z.coerce
    .number({ error: '在庫数は数字で入力してください' })
    .int({ error: '在庫数は整数で入力してください' })
    .min(0, { error: '在庫数は0以上にしてください' })
    .max(MAX_PRODUCT_STOCK, { error: `在庫数は${MAX_PRODUCT_STOCK}以下にしてください` }),
  description: z
    .string({ error: '説明を入力してください' })
    .trim()
    .min(1, { error: '説明を入力してください' })
    .max(500, { error: '説明は500文字以内で入力してください' }),
  imageUrl: productImageUrlSchema,
  categoryId: z.coerce
    .number({ error: 'カテゴリを選んでください' })
    .int({ error: 'カテゴリを選んでください' })
    .positive({ error: 'カテゴリを選んでください' }),
});

export type ProductFormInput = z.infer<typeof productFormSchema>;

/** 更新のときは、どの商品かを表す id が増える */
export const productUpdateSchema = productFormSchema.extend({ id: productIdSchema });

export type ProductUpdateInput = z.infer<typeof productUpdateSchema>;

export const PRODUCT_FIELD_LABELS: FieldLabels = {
  id: '商品',
  name: '商品名',
  price: '価格',
  stock: '在庫数',
  description: '説明',
  imageUrl: '画像のURL',
  categoryId: 'カテゴリ',
};
