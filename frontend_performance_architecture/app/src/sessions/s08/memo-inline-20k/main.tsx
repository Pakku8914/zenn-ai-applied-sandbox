import { CatalogMemoInline } from '../CatalogMemoInline';
import { mount } from '../mount';
import { PRODUCTS_20K } from '../products20k';

mount(<CatalogMemoInline title="商品カタログ（20,000 件・memo だけ）" products={PRODUCTS_20K} />);
