import { lazy } from 'react';
import { mountMid01 } from '../mount';
import { FixedCatalog } from '../FixedCatalog';
import { runPageTag } from '../tags';
import { reportWebVitals } from '../../../vitals';

// 比較用（おとりの検証）：模範解答版のグラフだけを React.lazy で遅延読み込みにした版。
// 計測すると初期 JS も LCP もほとんど変わらないので、模範解答版には入れていない。
const LazyPriceChart = lazy(() => import('../PriceChart').then((m) => ({ default: m.PriceChart })));

mountMid01(<FixedCatalog renderChart={() => <LazyPriceChart />} />);
reportWebVitals();

window.addEventListener('load', runPageTag, { once: true });
