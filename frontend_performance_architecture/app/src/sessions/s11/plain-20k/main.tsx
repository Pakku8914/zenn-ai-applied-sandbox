import { makeProducts } from '../../s08/makeProducts';
import { Catalog } from '../Catalog';
import { mount } from '../mount';

mount(<Catalog title="商品カタログ（20,000 件・全件描画）" products={makeProducts(20_000)} mode="plain" />);
