import { products } from '../../../data/products';
import { CatalogMemo } from '../CatalogMemo';
import { mount } from '../mount';

mount(<CatalogMemo title="商品カタログ（2,000 件・メモ化あり）" products={products} />);
