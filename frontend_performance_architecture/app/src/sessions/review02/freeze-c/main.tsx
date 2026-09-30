import { products } from '../../../data/products';
import { mount } from '../../s08/mount';
import { AutoWidthCatalog } from '../AutoWidthCatalog';

// 横断復習②「固まる画面 C」。原因は練習問題5で計測して突き止める（ここには書かない）
mount(<AutoWidthCatalog title="商品カタログ" products={products} />);
