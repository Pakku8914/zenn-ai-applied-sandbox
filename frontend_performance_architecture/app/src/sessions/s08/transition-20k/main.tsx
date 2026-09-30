import { CatalogTransition } from '../CatalogTransition';
import { mount } from '../mount';
import { PRODUCTS_20K } from '../products20k';

mount(<CatalogTransition title="商品カタログ（20,000 件・useTransition）" products={PRODUCTS_20K} />);
