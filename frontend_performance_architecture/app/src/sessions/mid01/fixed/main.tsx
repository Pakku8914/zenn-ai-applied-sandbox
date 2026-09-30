import { mountMid01 } from '../mount';
import { FixedCatalog } from '../FixedCatalog';
import { PriceChart } from '../PriceChart';
import { runPageTag } from '../tags';
import { reportWebVitals } from '../../../vitals';

// 模範解答版
mountMid01(<FixedCatalog renderChart={() => <PriceChart />} />);
reportWebVitals();

// 計測タグは外せない（営業上の要件）ため、最初の描画を止めない load の後に回す
window.addEventListener('load', runPageTag, { once: true });
