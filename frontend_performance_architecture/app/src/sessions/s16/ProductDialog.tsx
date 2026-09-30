import { useEffect, useRef, type CSSProperties } from 'react';
import type { Product } from '../../data/products';

const dialogStyle: CSSProperties = { border: 'none', borderRadius: 8, padding: 24, minWidth: 320 };

type Props = {
  product: Product | null;
  favorite: boolean;
  error: string | null;
  onToggleFavorite: (product: Product) => void;
  onClose: () => void;
};

/**
 * 商品の詳細ダイアログ。ネイティブの <dialog> を showModal() で開く。
 * - 開いたら「閉じる」ボタンへフォーカスを移す
 * - Escape で閉じる（ブラウザが cancel → close を発火する）
 * - 閉じたら、開く前にフォーカスがあった要素（押した行のボタン）へ戻す
 * - 保存失敗の role="alert" はダイアログの中に置く（外側は showModal で操作不能になり、読み上げの対象からも外れる）
 */
export function ProductDialog({ product, favorite, error, onToggleFavorite, onClose }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog === null || product === null) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.showModal();
    closeRef.current?.focus();
    return () => {
      if (dialog.open) dialog.close();
      opener?.focus();
    };
  }, [product]);

  return (
    <dialog ref={dialogRef} className="s16-dialog" aria-labelledby="dialog-title" onClose={onClose} style={dialogStyle}>
      {product !== null && (
        <>
          <h2 id="dialog-title">{product.name} の詳細</h2>
          <p>
            {product.price} 円・{product.category}
          </p>
          {/* 押した瞬間に aria-pressed を切り替える（楽観的UI）。失敗したら戻して alert で伝える */}
          <button type="button" aria-pressed={favorite} onClick={() => onToggleFavorite(product)}>
            <span aria-hidden="true">{favorite ? '★' : '☆'}</span> お気に入り
          </button>
          {error !== null && <p role="alert">{error}</p>}
          <p>
            <button ref={closeRef} type="button" onClick={onClose}>
              閉じる
            </button>
          </p>
        </>
      )}
    </dialog>
  );
}
