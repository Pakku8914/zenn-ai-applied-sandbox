import { mountMid01 } from '../mount';
import { SlowCatalog } from '../SlowCatalog';
import { reportWebVitals } from '../../../vitals';

// 出題版。計測タグは HTML の <head> に同期スクリプトとして直接書いてある
mountMid01(<SlowCatalog />);
reportWebVitals();
