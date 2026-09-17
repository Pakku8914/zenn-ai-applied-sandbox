'use client';

// error.tsx は「再試行ボタン」を持つため、必ずクライアントコンポーネントにする。
// この 'use client' が無いと Next.js がビルド時にエラーを出す。

type ErrorPageProps = {
  error: Error & { digest?: string };
  reset: () => void;
};

export default function ProductsError({ error, reset }: ErrorPageProps) {
  return (
    <div>
      <h1>商品の表示に失敗しました</h1>
      <p>時間をおいて、もう一度お試しください。</p>

      {/* error.message は利用者に見せない。内部の情報が漏れる可能性があるため */}
      {error.digest === undefined ? null : <p>{`問い合わせ番号: ${error.digest}`}</p>}

      <button type="button" onClick={reset}>
        再読み込み
      </button>
    </div>
  );
}
