// 商品一覧が届くまでのあいだに出す「骨組み」（セッション27）。
//
// 「読み込み中…」の1行ではなく、あとから来る中身と同じ形・同じ高さの箱を並べる。
// こうすると中身が届いたときに画面がガタッと動かない（＝CLS が悪化しない）。
// サーバーコンポーネントなので、この部品はクライアントに JavaScript を送らない。

type ProductListSkeletonProps = {
  /** 並べる箱の数。1ページの表示件数に合わせる */
  rows?: number;
};

export function ProductListSkeleton({ rows = 3 }: ProductListSkeletonProps) {
  // 添字ではなく「何番目か」を key にできる値を先に作る（配列の添字を key にしない）
  const placeholders = Array.from({ length: rows }, (_, index) => `row-${index + 1}`);

  return (
    <section aria-busy="true">
      <h2>商品を読み込んでいます…</h2>
      <ul>
        {placeholders.map((placeholder) => (
          <li key={placeholder} style={{ minHeight: '1.5rem' }}>
            <span aria-hidden="true">━━━━━━━━━━</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
