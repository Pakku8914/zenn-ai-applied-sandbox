'use client';

// 商品の登録・更新フォーム（最終プロジェクト）。
//
// 登録と更新で同じ入力欄を使うので、1つの部品にまとめて mode で切り替える。
// 更新のときだけ隠しフィールドで id を送る。
//
// 入力欄に required や min を付けているのは親切心（UX）であって、守りではない。
// 本当の検証は Server Action の中で Zod が行う（ブラウザ側の検査は簡単に外せる）。

import { useActionState } from 'react';
import { createProductAction, updateProductAction } from '@/lib/admin-product-actions';
import {
  MAX_PRODUCT_PRICE,
  MAX_PRODUCT_STOCK,
  type CartActionState,
} from '@/lib/validation';

const INITIAL_STATE: CartActionState = { kind: 'idle' };

type CategoryOption = { id: number; name: string };

type ProductDraft = {
  id: number;
  name: string;
  price: number;
  stock: number;
  description: string;
  imageUrl: string;
  categoryId: number;
};

type ProductEditorFormProps = {
  mode: 'create' | 'edit';
  categories: readonly CategoryOption[];
  /** 更新のときだけ渡す */
  product?: ProductDraft;
};

export function ProductEditorForm({ mode, categories, product }: ProductEditorFormProps) {
  const action = mode === 'create' ? createProductAction : updateProductAction;
  const [state, formAction, isPending] = useActionState(action, INITIAL_STATE);

  return (
    <form action={formAction}>
      {mode === 'edit' && product !== undefined ? (
        <input type="hidden" name="id" value={product.id} />
      ) : null}

      <p>
        <label>
          商品名
          <input type="text" name="name" defaultValue={product?.name ?? ''} maxLength={200} required />
        </label>
      </p>

      <p>
        <label>
          価格（円・整数）
          <input
            type="number"
            name="price"
            defaultValue={product?.price ?? ''}
            min={1}
            max={MAX_PRODUCT_PRICE}
            step={1}
            required
          />
        </label>
      </p>

      <p>
        <label>
          在庫数
          <input
            type="number"
            name="stock"
            defaultValue={product?.stock ?? 0}
            min={0}
            max={MAX_PRODUCT_STOCK}
            step={1}
            required
          />
        </label>
      </p>

      <p>
        <label>
          説明
          <textarea name="description" defaultValue={product?.description ?? ''} maxLength={500} required />
        </label>
      </p>

      <p>
        <label>
          画像のURL（空欄なら既定の画像）
          <input type="text" name="imageUrl" defaultValue={product?.imageUrl ?? ''} maxLength={200} />
        </label>
      </p>

      <p>
        <label>
          カテゴリ
          <select name="categoryId" defaultValue={product?.categoryId ?? categories[0]?.id ?? 1}>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </select>
        </label>
      </p>

      <button type="submit" disabled={isPending}>
        {isPending ? '保存中…' : mode === 'create' ? '登録する' : '更新する'}
      </button>

      {state.kind === 'ok' ? <p role="status">{state.message}</p> : null}
      {state.kind === 'error' ? <p role="alert">{state.messages.join(' / ')}</p> : null}
    </form>
  );
}
