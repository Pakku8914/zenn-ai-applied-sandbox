import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { reportWebVitals } from '../../../vitals';
import { GoodCatalog } from '../GoodCatalog';
import { createCatalogApi, parseOptions } from '../catalogApi';
import '../good.css';

// ?latency=10000・?fail=load・?fail=favorite・?live=eager で待ち時間や失敗を再現する（検証スクリプトが使う）
const options = parseOptions(window.location.search);

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}
createRoot(rootElement).render(
  <StrictMode>
    <GoodCatalog api={createCatalogApi(options)} failLoad={options.failLoad} liveDelayMs={options.liveDelayMs} />
  </StrictMode>,
);
reportWebVitals();
