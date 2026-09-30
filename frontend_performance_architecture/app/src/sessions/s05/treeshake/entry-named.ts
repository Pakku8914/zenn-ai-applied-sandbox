// Good：使う関数だけを名前付き import する。formatDate はバンドルから消える
import { formatPrice } from './format-utils';

document.title = formatPrice(1200);
