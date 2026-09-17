// 問題3：エントリポイント。
import { toCartLines } from '../cart';
import { cartItems } from '../shop-data';
import { formatNullSafety } from './q3-null-safe';

console.log(formatNullSafety(toCartLines(cartItems)));
