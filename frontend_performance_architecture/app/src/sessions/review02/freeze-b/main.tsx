import { products } from '../../../data/products';
import { mount } from '../../s08/mount';
import { ChartOnTypeCatalog } from '../ChartOnTypeCatalog';

// 横断復習②「固まる画面 B」。原因は練習問題5で計測して突き止める（ここには書かない）
mount(<ChartOnTypeCatalog title="商品カタログ" products={products} />);
