/** この HTML がいつ作られたかを表示する。SSG・ISR・SSR の違いを確かめるための目印 */
export function RenderedAt() {
  return (
    <p>
      この HTML を生成した時刻：<time id="rendered-at">{new Date().toISOString()}</time>
    </p>
  );
}
