import { RenderedAt } from '../../lib/s12/RenderedAt';

export const metadata = { title: 'S12 SSG' };

/** 何も指定せず、リクエスト固有の情報も読まない → ビルド時に1回だけ HTML を作る（SSG） */
export default function Page() {
  return (
    <main>
      <h1>SSG：ビルド時に作った HTML</h1>
      <RenderedAt />
    </main>
  );
}
