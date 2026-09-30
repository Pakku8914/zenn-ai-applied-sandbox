import { CatalogMemo } from '../CatalogMemo';
import { mount } from '../mount';
import { PRODUCTS_20K } from '../products20k';

mount(<CatalogMemo title="商品カタログ（20,000 件・メモ化あり）" products={PRODUCTS_20K} />);
