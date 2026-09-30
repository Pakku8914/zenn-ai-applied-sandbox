import { mountCatalog } from '../mountCatalog';
import { reportWebVitals } from '../../../vitals';

// 要因分解用（Bad 版から同期スクリプトだけを外した版）。CSS と画像の指定は Bad 版のまま
mountCatalog();
reportWebVitals();
