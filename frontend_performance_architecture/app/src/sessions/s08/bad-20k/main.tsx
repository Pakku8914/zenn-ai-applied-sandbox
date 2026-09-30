import { CatalogBad } from '../CatalogBad';
import { mount } from '../mount';
import { PRODUCTS_20K } from '../products20k';

mount(<CatalogBad title="商品カタログ（20,000 件・メモ化なし）" products={PRODUCTS_20K} />);
