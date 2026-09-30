import { makeProducts } from './makeProducts';

/** 差を見えるようにするための 20,000 件。2,000 件のページはこのファイルを読み込まない */
export const PRODUCTS_20K = makeProducts(20_000);
