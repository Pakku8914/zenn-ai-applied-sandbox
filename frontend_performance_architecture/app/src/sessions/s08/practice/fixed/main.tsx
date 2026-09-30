import { mount } from '../../mount';
import { PRODUCTS_20K } from '../../products20k';
import { CatalogFixed } from '../CatalogFixed';

mount(<CatalogFixed title="商品カタログ（20,000 件・問題4の解答）" products={PRODUCTS_20K} />);
