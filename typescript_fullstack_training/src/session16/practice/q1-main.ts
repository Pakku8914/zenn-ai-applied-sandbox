// 問題1：エントリポイント。1つ上のフォルダのデータを ../ で取り込む。
import { products } from '../shop-data';
import { buildStockReport, formatStockReport } from './q1-stock';

console.log(formatStockReport(buildStockReport(products)));
