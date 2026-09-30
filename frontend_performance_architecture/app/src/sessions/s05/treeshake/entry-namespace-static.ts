// 練習問題2 (B)：名前空間 import でも、固定の名前で使う限りは使われる関数を追える
import * as fmt from './format-utils';

document.title = fmt.formatPrice(1200);
