import { makeProducts } from '../../s08/makeProducts';
import { Catalog } from '../Catalog';
import { mount } from '../mount';

mount(<Catalog title="商品カタログ（2,000 件・全件描画）" products={makeProducts(2000)} mode="plain" />);
