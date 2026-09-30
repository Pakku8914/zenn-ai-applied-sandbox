import { CatalogDeferred } from '../CatalogDeferred';
import { mount } from '../mount';
import { PRODUCTS_20K } from '../products20k';

mount(<CatalogDeferred title="商品カタログ（20,000 件・useDeferredValue）" products={PRODUCTS_20K} />);
