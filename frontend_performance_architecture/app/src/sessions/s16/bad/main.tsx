import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { reportWebVitals } from '../../../vitals';
import { BadCatalog } from '../BadCatalog';
import { createCatalogApi, parseOptions } from '../catalogApi';
import '../bad.css';

const options = parseOptions(window.location.search);

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}
createRoot(rootElement).render(
  <StrictMode>
    <BadCatalog api={createCatalogApi(options)} failLoad={options.failLoad} />
  </StrictMode>,
);
reportWebVitals();
