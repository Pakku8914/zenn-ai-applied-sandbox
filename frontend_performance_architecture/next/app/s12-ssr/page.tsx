import { RenderedAt } from '../../lib/s12/RenderedAt';

export const metadata = { title: 'S12 SSR' };
// リクエストのたびにサーバーで HTML を作る（SSR）
export const dynamic = 'force-dynamic';

export default function Page() {
  return (
    <main>
      <h1>SSR：リクエストごとに作る HTML</h1>
      <RenderedAt />
    </main>
  );
}
