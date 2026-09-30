import { products } from '../../../data/products';
import { CatalogBad } from '../CatalogBad';
import { mount } from '../mount';

// 出発点と同じ 2,000 件（src/data/products.ts をそのまま使う）
mount(<CatalogBad title="商品カタログ（2,000 件・メモ化なし）" products={products} />);
