import { mount } from '../../mount';
import { PRODUCTS_20K } from '../../products20k';
import { CatalogMyDeferred } from '../CatalogMyDeferred';

mount(<CatalogMyDeferred title="商品カタログ（20,000 件・問題6の解答）" products={PRODUCTS_20K} />);
