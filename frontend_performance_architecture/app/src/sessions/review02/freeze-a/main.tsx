import { CatalogBad } from '../../s08/CatalogBad';
import { mount } from '../../s08/mount';
import { PRODUCTS_20K } from '../../s08/products20k';

// 横断復習②「固まる画面 A」。原因は練習問題5で計測して突き止める（ここには書かない）
mount(<CatalogBad title="商品カタログ" products={PRODUCTS_20K} />);
