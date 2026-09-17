// 問題7：エントリポイント。
import { INVALID_ORDER_JSON, SAMPLE_ORDER_JSON } from './q7-input';
import { buildReceiptText } from './q7-receipt';

console.log(buildReceiptText(SAMPLE_ORDER_JSON));
console.log(buildReceiptText(INVALID_ORDER_JSON));
