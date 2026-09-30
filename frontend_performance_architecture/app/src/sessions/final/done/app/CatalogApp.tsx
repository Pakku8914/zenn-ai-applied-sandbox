import { useState } from 'react';
import type { Product } from '../../../../data/products';
import { PRODUCTS_20K } from '../../../s08/products20k';
import { CampaignBanner } from '../features/campaign';
import { Catalog, SearchBox } from '../features/catalog';
import { ChartToggle } from '../features/chart';
import { PrintPreview } from '../features/print';
import { pageStyle } from '../shared/ui/styles';

/**
 * 最終プロジェクトの模範解答版。app は feature を並べ、feature 同士の受け渡し（選んだ商品 → 印刷）だけを行う。
 * 選んだ商品は catalog と print の両方にかかわるローカルな状態なので、両者の共通の親であるここに置く。
 */
export function CatalogApp() {
  const [selected, setSelected] = useState<Product | null>(null);

  return (
    <main style={pageStyle}>
      <h1>商品カタログ（計測用）</h1>
      <SearchBox />
      <ChartToggle />
      <CampaignBanner />
      <Catalog items={PRODUCTS_20K} onSelect={setSelected} />
      <PrintPreview product={selected} />
    </main>
  );
}
